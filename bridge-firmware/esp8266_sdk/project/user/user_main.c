#include "osapi.h"
#include "mem.h"
#include "user_interface.h"
#include "espconn.h"
#include "driver/uart.h"
#include "eagle_soc.h"
#include "driver/uart_register.h"

#include "bridge_config.h"
#include "ring_buffer.h"

#if SPI_FLASH_SIZE_MAP == 4
#define SYSTEM_PARTITION_OTA_SIZE 0x6A000
#define SYSTEM_PARTITION_OTA_2_ADDR 0x81000
#define SYSTEM_PARTITION_RF_CAL_ADDR 0x3fb000
#define SYSTEM_PARTITION_PHY_DATA_ADDR 0x3fc000
#define SYSTEM_PARTITION_SYSTEM_PARAMETER_ADDR 0x3fd000
#elif SPI_FLASH_SIZE_MAP == 6
#define SYSTEM_PARTITION_OTA_SIZE 0x6A000
#define SYSTEM_PARTITION_OTA_2_ADDR 0x101000
#define SYSTEM_PARTITION_RF_CAL_ADDR 0x3fb000
#define SYSTEM_PARTITION_PHY_DATA_ADDR 0x3fc000
#define SYSTEM_PARTITION_SYSTEM_PARAMETER_ADDR 0x3fd000
#else
#error "This firmware currently expects SPI_FLASH_SIZE_MAP=4 or 6 on 4 MB flash."
#endif

static const partition_item_t g_partition_table[] = {
    {SYSTEM_PARTITION_BOOTLOADER, 0x0, 0x1000},
    {SYSTEM_PARTITION_OTA_1, 0x1000, SYSTEM_PARTITION_OTA_SIZE},
    {SYSTEM_PARTITION_OTA_2, SYSTEM_PARTITION_OTA_2_ADDR, SYSTEM_PARTITION_OTA_SIZE},
    {SYSTEM_PARTITION_RF_CAL, SYSTEM_PARTITION_RF_CAL_ADDR, 0x1000},
    {SYSTEM_PARTITION_PHY_DATA, SYSTEM_PARTITION_PHY_DATA_ADDR, 0x1000},
    {SYSTEM_PARTITION_SYSTEM_PARAMETER, SYSTEM_PARTITION_SYSTEM_PARAMETER_ADDR, 0x3000},
};

static struct espconn g_server_conn;
static esp_tcp g_server_tcp;
static struct espconn* g_active_conn = NULL;

static os_timer_t g_wifi_retry_timer;
static os_timer_t g_pump_timer;
static os_timer_t g_diag_timer;

static bool g_tcp_send_inflight = false;
static uint8_t g_fc_to_client_quiet_ticks = 0U;
static uint8_t g_client_to_fc_storage[BRIDGE_CLIENT_TO_FC_BUFFER_BYTES];
static uint8_t g_fc_to_client_storage[BRIDGE_FC_TO_CLIENT_BUFFER_BYTES];
static uint8_t g_tcp_send_chunk[BRIDGE_TCP_CHUNK_BYTES];

static ring_buffer_t g_client_to_fc;
static ring_buffer_t g_fc_to_client;

void ICACHE_FLASH_ATTR user_pre_init(void) {
  if (!system_partition_table_regist(g_partition_table,
                                     sizeof(g_partition_table) / sizeof(g_partition_table[0]),
                                     SPI_FLASH_SIZE_MAP)) {
    while (1) {
    }
  }
}

static void ICACHE_FLASH_ATTR bridge_release_active_client(struct espconn* conn) {
  if (conn != NULL && conn == g_active_conn) {
    g_active_conn = NULL;
    g_tcp_send_inflight = false;
    g_fc_to_client_quiet_ticks = 0U;
    ring_buffer_clear(&g_client_to_fc);
    ring_buffer_clear(&g_fc_to_client);
  }
}

static void ICACHE_FLASH_ATTR bridge_disconnect_active_client(void) {
  if (g_active_conn != NULL) {
    espconn_disconnect(g_active_conn);
  }
}

static uint16_t ICACHE_FLASH_ATTR bridge_uart_available(void) {
  return (READ_PERI_REG(UART_STATUS(UART0)) >> UART_RXFIFO_CNT_S) & UART_RXFIFO_CNT;
}

static int ICACHE_FLASH_ATTR bridge_uart_read_byte(void) {
  if (bridge_uart_available() == 0U) {
    return -1;
  }

  return READ_PERI_REG(UART_FIFO(UART0)) & 0xFF;
}

static void ICACHE_FLASH_ATTR bridge_uart_write_byte(uint8_t byte) {
  uart_tx_one_char(UART0, byte);
}

static void ICACHE_FLASH_ATTR bridge_drain_uart_when_idle(void) {
  while (bridge_uart_available() > 0U) {
    (void)bridge_uart_read_byte();
  }
}

static void ICACHE_FLASH_ATTR bridge_flush_fc_to_client(void) {
  uint16_t chunk_len;
  sint8 send_status;

  if (g_active_conn == NULL || g_tcp_send_inflight || ring_buffer_empty(&g_fc_to_client)) {
    return;
  }

  chunk_len =
      (uint16_t)ring_buffer_read(&g_fc_to_client, g_tcp_send_chunk, sizeof(g_tcp_send_chunk));
  if (chunk_len == 0U) {
    return;
  }

  send_status = espconn_sent(g_active_conn, g_tcp_send_chunk, chunk_len);
  if (send_status == ESPCONN_OK) {
    g_tcp_send_inflight = true;
    return;
  }

  bridge_disconnect_active_client();
}

static void ICACHE_FLASH_ATTR bridge_pump_client_to_fc(void) {
  uint8_t byte;
  uint16_t budget = BRIDGE_TCP_CHUNK_BYTES;

  while (budget > 0U && ring_buffer_read(&g_client_to_fc, &byte, 1U) == 1U) {
    bridge_uart_write_byte(byte);
    budget--;
  }
}

static uint16_t ICACHE_FLASH_ATTR bridge_fill_fc_to_client_buffer(void) {
  uint8_t byte;
  uint16_t bytes_read = 0U;

  while (g_active_conn != NULL && ring_buffer_available(&g_fc_to_client) > 0U &&
         bridge_uart_available() > 0U) {
    byte = (uint8_t)bridge_uart_read_byte();
    (void)ring_buffer_write(&g_fc_to_client, &byte, 1U);
    bytes_read++;
  }

  return bytes_read;
}

static void ICACHE_FLASH_ATTR bridge_pump_cb(void* arg) {
  uint16_t fc_bytes_read;
  size_t fc_buffered;
  (void)arg;

  if (g_active_conn == NULL) {
    g_fc_to_client_quiet_ticks = 0U;
    bridge_drain_uart_when_idle();
    return;
  }

  bridge_pump_client_to_fc();
  fc_bytes_read = bridge_fill_fc_to_client_buffer();
  fc_buffered = ring_buffer_size(&g_fc_to_client);

  if (fc_bytes_read > 0U) {
    g_fc_to_client_quiet_ticks = 0U;
  } else if (fc_buffered > 0U && g_fc_to_client_quiet_ticks < BRIDGE_FC_TO_CLIENT_QUIET_TICKS) {
    g_fc_to_client_quiet_ticks++;
  }

  /*
   * Short MSP replies are only a few bytes.  Do not flush them while bytes are
   * still arriving; wait for several quiet 1 ms pump ticks or flush immediately
   * once a normal TCP chunk is full.
   */
  if (fc_buffered > 0U && fc_buffered < BRIDGE_TCP_CHUNK_BYTES &&
      g_fc_to_client_quiet_ticks < BRIDGE_FC_TO_CLIENT_QUIET_TICKS) {
    return;
  }

  bridge_flush_fc_to_client();
}

static const char* ICACHE_FLASH_ATTR bridge_wifi_status_name(uint8 status) {
  switch (status) {
    case STATION_IDLE:
      return "IDLE";
    case STATION_CONNECTING:
      return "CONNECTING";
    case STATION_WRONG_PASSWORD:
      return "WRONG_PASSWORD";
    case STATION_NO_AP_FOUND:
      return "NO_AP_FOUND";
    case STATION_CONNECT_FAIL:
      return "CONNECT_FAIL";
    case STATION_GOT_IP:
      return "GOT_IP";
    default:
      return "UNKNOWN";
  }
}

static void ICACHE_FLASH_ATTR bridge_wifi_event_cb(System_Event_t* event) {
#if BRIDGE_DIAGNOSTIC_BUILD
  if (event == NULL) {
    os_printf("[diag] wifi event null\r\n");
    return;
  }

  switch (event->event) {
    case EVENT_STAMODE_CONNECTED:
      os_printf("[diag] wifi connected ssid=%s channel=%d\r\n", BRIDGE_WIFI_SSID,
                event->event_info.connected.channel);
      break;
    case EVENT_STAMODE_DISCONNECTED:
      os_printf("[diag] wifi disconnected reason=%d\r\n",
                event->event_info.disconnected.reason);
      break;
    case EVENT_STAMODE_GOT_IP:
      os_printf("[diag] wifi got ip %d.%d.%d.%d gw %d.%d.%d.%d\r\n",
                IP2STR(&event->event_info.got_ip.ip), IP2STR(&event->event_info.got_ip.gw));
      break;
    case EVENT_STAMODE_DHCP_TIMEOUT:
      os_printf("[diag] wifi dhcp timeout\r\n");
      break;
    default:
      os_printf("[diag] wifi event=%lu\r\n", (unsigned long)event->event);
      break;
  }
#else
  (void)event;
#endif
}

static void ICACHE_FLASH_ATTR bridge_wifi_connect(void) {
  struct station_config station_config;
  bool configured;

  os_memset(&station_config, 0, sizeof(station_config));
  os_memcpy(station_config.ssid, BRIDGE_WIFI_SSID, sizeof(BRIDGE_WIFI_SSID) - 1U);
  os_memcpy(station_config.password, BRIDGE_WIFI_PASSWORD,
            sizeof(BRIDGE_WIFI_PASSWORD) - 1U);

  wifi_station_disconnect();
  wifi_set_opmode_current(STATION_MODE);
  wifi_station_set_auto_connect(TRUE);
  wifi_station_set_hostname(BRIDGE_HOSTNAME);
  configured = wifi_station_set_config_current(&station_config);
#if BRIDGE_DIAGNOSTIC_BUILD
  os_printf("[diag] wifi config ssid=%s host=%s set=%d\r\n", BRIDGE_WIFI_SSID,
            BRIDGE_HOSTNAME, configured ? 1 : 0);
#endif
  wifi_station_connect();
}

static void ICACHE_FLASH_ATTR bridge_wifi_retry_cb(void* arg) {
  uint8 status;
  (void)arg;

  status = wifi_station_get_connect_status();
#if BRIDGE_DIAGNOSTIC_BUILD
  os_printf("[diag] wifi retry status=%s(%d)\r\n", bridge_wifi_status_name(status), status);
#endif
  if (status == STATION_GOT_IP || status == STATION_CONNECTING) {
    return;
  }

#if BRIDGE_DIAGNOSTIC_BUILD
  os_printf("[diag] wifi reconnect attempt\r\n");
#endif
  bridge_wifi_connect();
}

static void ICACHE_FLASH_ATTR bridge_diag_timer_cb(void* arg) {
#if BRIDGE_DIAGNOSTIC_BUILD
  struct ip_info ip;
  uint8 status;
  (void)arg;

  status = wifi_station_get_connect_status();
  os_printf("[diag] poll status=%s(%d)\r\n", bridge_wifi_status_name(status), status);

  if (wifi_get_ip_info(STATION_IF, &ip)) {
    os_printf("[diag] poll ip=%d.%d.%d.%d gw=%d.%d.%d.%d mask=%d.%d.%d.%d\r\n",
              IP2STR(&ip.ip), IP2STR(&ip.gw), IP2STR(&ip.netmask));
  }
#else
  (void)arg;
#endif
}

static void ICACHE_FLASH_ATTR bridge_tcp_recv_cb(void* arg, char* data,
                                                  unsigned short len) {
  struct espconn* conn = (struct espconn*)arg;
  size_t written;

  if (conn != g_active_conn) {
    espconn_disconnect(conn);
    return;
  }

  written = ring_buffer_write(&g_client_to_fc, (const uint8_t*)data, (size_t)len);
  if (written != (size_t)len) {
    bridge_disconnect_active_client();
    return;
  }

  bridge_pump_client_to_fc();
}

static void ICACHE_FLASH_ATTR bridge_tcp_sent_cb(void* arg) {
  struct espconn* conn = (struct espconn*)arg;

  if (conn != g_active_conn) {
    return;
  }

  g_tcp_send_inflight = false;
  bridge_flush_fc_to_client();
}

static void ICACHE_FLASH_ATTR bridge_tcp_discon_cb(void* arg) {
  bridge_release_active_client((struct espconn*)arg);
}

static void ICACHE_FLASH_ATTR bridge_tcp_connect_cb(void* arg) {
  struct espconn* conn = (struct espconn*)arg;

  if (g_active_conn != NULL && g_active_conn != conn) {
    espconn_regist_disconcb(conn, bridge_tcp_discon_cb);
    espconn_disconnect(conn);
    return;
  }

  g_active_conn = conn;
  g_tcp_send_inflight = false;
  g_fc_to_client_quiet_ticks = 0U;
  ring_buffer_clear(&g_client_to_fc);
  ring_buffer_clear(&g_fc_to_client);

  espconn_regist_recvcb(conn, bridge_tcp_recv_cb);
  espconn_regist_sentcb(conn, bridge_tcp_sent_cb);
  espconn_regist_disconcb(conn, bridge_tcp_discon_cb);
}

static void ICACHE_FLASH_ATTR bridge_tcp_server_init(void) {
  os_memset(&g_server_conn, 0, sizeof(g_server_conn));
  os_memset(&g_server_tcp, 0, sizeof(g_server_tcp));

  g_server_conn.type = ESPCONN_TCP;
  g_server_conn.state = ESPCONN_NONE;
  g_server_conn.proto.tcp = &g_server_tcp;
  g_server_conn.proto.tcp->local_port = BRIDGE_TCP_PORT;

  espconn_regist_connectcb(&g_server_conn, bridge_tcp_connect_cb);
  espconn_accept(&g_server_conn);
  espconn_regist_time(&g_server_conn, 0, 0);
}

void user_init(void) {
  ring_buffer_init(&g_client_to_fc, g_client_to_fc_storage, sizeof(g_client_to_fc_storage));
  ring_buffer_init(&g_fc_to_client, g_fc_to_client_storage, sizeof(g_fc_to_client_storage));

#if BRIDGE_DIAGNOSTIC_BUILD
  uart_init(BRIDGE_DIAGNOSTIC_SERIAL_BAUD, BRIDGE_DIAGNOSTIC_SERIAL_BAUD);
  system_set_os_print(1);
  os_printf("\r\n[diag] boot bridge diagnostic build\r\n");
#else
  uart_init(BRIDGE_FC_BAUD, BRIDGE_FC_BAUD);
  system_set_os_print(0);
  /*
   * The SDK UART driver installs an RX interrupt/task that consumes UART0 FIFO
   * bytes.  The Bridge owns UART0 RX by polling the FIFO directly, so disable
   * the SDK UART interrupts after using uart_init() for baud/FIFO setup.
   */
  WRITE_PERI_REG(UART_INT_ENA(UART0), 0);
  WRITE_PERI_REG(UART_INT_CLR(UART0), 0xffff);
  system_uart_swap();
#endif

  wifi_set_sleep_type(NONE_SLEEP_T);
  wifi_set_event_handler_cb(bridge_wifi_event_cb);
  bridge_tcp_server_init();
  bridge_wifi_connect();

  os_timer_disarm(&g_wifi_retry_timer);
  os_timer_setfn(&g_wifi_retry_timer, bridge_wifi_retry_cb, NULL);
  os_timer_arm(&g_wifi_retry_timer, BRIDGE_WIFI_RETRY_MS, 1);

  os_timer_disarm(&g_pump_timer);
  os_timer_setfn(&g_pump_timer, bridge_pump_cb, NULL);
  os_timer_arm(&g_pump_timer, BRIDGE_PUMP_INTERVAL_MS, 1);

#if BRIDGE_DIAGNOSTIC_BUILD
  os_timer_disarm(&g_diag_timer);
  os_timer_setfn(&g_diag_timer, bridge_diag_timer_cb, NULL);
  os_timer_arm(&g_diag_timer, 2000, 1);
#endif
}
