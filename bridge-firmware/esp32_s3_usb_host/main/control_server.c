#include "control_server.h"

#include <string.h>
#include <stdint.h>
#include <sys/unistd.h>

#include "bridge_config.h"
#include "bridge_storage.h"
#include "esp_log.h"
#include "tcp_single_client.h"
#include "usb_msc_blackbox.h"
#include "usb_msp_transport.h"

static const char *TAG = "control";

static void list_cb(const char *name, size_t size, void *ctx) {
  char line[256];
  snprintf(line, sizeof(line), "LOG %s %u\n", name, (unsigned)size);
  tcp_single_client_send("control", (const uint8_t *)line, strlen(line));
  (void)ctx;
}

static esp_err_t control_on_data(const uint8_t *data, size_t len, void *ctx) {
  (void)ctx;
  char command[160];
  const size_t copy_len = len < sizeof(command) - 1 ? len : sizeof(command) - 1;
  memcpy(command, data, copy_len);
  command[copy_len] = '\0';

  if (strncmp(command, "STATUS", 6) == 0) {
    const char *status = usb_msp_transport_is_connected() ? "STATUS USB_CDC_CONNECTED\n" : "STATUS USB_CDC_DISCONNECTED\n";
    return tcp_single_client_send("control", (const uint8_t *)status, strlen(status));
  }
  if (strncmp(command, "HELP", 4) == 0) {
    const char *help = "OK commands: STATUS LIST GET <name> MSC_SCAN HELP\n";
    return tcp_single_client_send("control", (const uint8_t *)help, strlen(help));
  }
  if (strncmp(command, "LIST", 4) == 0) {
    bridge_storage_list_blackbox_logs(list_cb, NULL);
    return tcp_single_client_send("control", (const uint8_t *)"OK\n", 3);
  }
  if (strncmp(command, "MSC_SCAN", 8) == 0) {
    esp_err_t err = usb_msc_blackbox_scan_and_copy();
    const char *reply = err == ESP_OK ? "OK\n" : "ERR MSC_SCAN not available\n";
    return tcp_single_client_send("control", (const uint8_t *)reply, strlen(reply));
  }
  if (strncmp(command, "GET ", 4) == 0) {
    char *name = command + 4;
    name[strcspn(name, "\r\n")] = '\0';
    int fd = -1;
    size_t size = 0;
    if (bridge_storage_open_blackbox_log(name, &fd, &size) != ESP_OK) {
      return tcp_single_client_send("control", (const uint8_t *)"ERR not found\n", 14);
    }
    char header[64];
    snprintf(header, sizeof(header), "DATA %u\n", (unsigned)size);
    tcp_single_client_send("control", (const uint8_t *)header, strlen(header));
    uint8_t buf[1024];
    ssize_t got;
    while ((got = read(fd, buf, sizeof(buf))) > 0) {
      tcp_single_client_send("control", buf, (size_t)got);
    }
    close(fd);
    return ESP_OK;
  }

  ESP_LOGW(TAG, "unknown command: %s", command);
  return tcp_single_client_send("control", (const uint8_t *)"ERR unknown command\n", 20);
}

esp_err_t control_server_start(void) {
  return tcp_single_client_server_start(BRIDGE_CONTROL_TCP_PORT, "control", control_on_data, NULL);
}

