#include <stddef.h>
#include <stdint.h>

#include "bridge_config.h"
#include "bridge_storage.h"
#include "control_server.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "tcp_single_client.h"
#include "usb_msc_blackbox.h"
#include "usb_msp_transport.h"
#include "wifi_station.h"

static const char *TAG = "tuna_usb_bridge";

static esp_err_t msp_tcp_on_data(const uint8_t *data, size_t len, void *ctx) {
  (void)ctx;
  return usb_msp_transport_write(data, len);
}

static void usb_msp_on_rx(const uint8_t *data, size_t len, void *ctx) {
  (void)ctx;
  tcp_single_client_send("msp", data, len);
}

void app_main(void) {
  ESP_ERROR_CHECK(nvs_flash_init());
  ESP_ERROR_CHECK(wifi_station_start());

  bridge_storage_init();
  usb_msp_transport_init();
  usb_msp_transport_set_rx_cb(usb_msp_on_rx, NULL);
  usb_msc_blackbox_init();

  ESP_ERROR_CHECK(tcp_single_client_server_start(BRIDGE_MSP_TCP_PORT, "msp", msp_tcp_on_data, NULL));
  ESP_ERROR_CHECK(control_server_start());

  ESP_LOGI(TAG, "ESP32-S3 USB-host Bridge started host=%s msp_port=%d control_port=%d",
           BRIDGE_HOSTNAME, BRIDGE_MSP_TCP_PORT, BRIDGE_CONTROL_TCP_PORT);
}

