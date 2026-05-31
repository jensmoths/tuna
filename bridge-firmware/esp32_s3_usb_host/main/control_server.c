#include "control_server.h"

#include <string.h>
#include <stdint.h>
#include <sys/unistd.h>
#include <stdlib.h>
#include <ctype.h>

#include "bridge_config.h"
#include "board_power.h"
#include "bridge_storage.h"
#include "esp_log.h"
#include "esp_err.h"
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

  if (strncmp(command, "STATUS_VERBOSE", 14) == 0) {
    usb_msp_transport_diag_t diag;
    bridge_board_power_diag_t power;
    usb_msc_blackbox_diag_t msc;
    usb_msp_transport_get_diag(&diag);
    bridge_board_power_get_diag(&power);
    usb_msc_blackbox_get_diag(&msc);
    char status[512];
    snprintf(status, sizeof(status),
             "STATUS %s usb_new=%u last=%04x:%04x addr=%u class=%02x/%02x/%02x open_err=%s if=%u pmu=%s r03=%02x r07=%02x r0a=%02x r0b=%02x r0c=%02x otg=%u chg=%u vbus=%u msc_events=%u msc_disc=%u msc_addr=%u msc_mounted=%u msc_raw=%u msc_sectors=%u msc_sector_size=%u msc_err=%s\n",
             usb_msp_transport_is_connected() ? "USB_CDC_CONNECTED" : "USB_CDC_DISCONNECTED",
             (unsigned)diag.new_dev_count, diag.last_vid, diag.last_pid, diag.last_dev_addr,
             diag.last_dev_class, diag.last_dev_subclass, diag.last_dev_protocol,
             esp_err_to_name(diag.last_open_err), diag.last_open_interface,
             esp_err_to_name(power.last_err), power.reg03, power.reg07, power.reg0a, power.reg0b, power.reg0c,
             power.otg_enabled ? 1 : 0, power.charge_enabled ? 1 : 0, power.vbus_present ? 1 : 0,
             (unsigned)msc.connected_events, (unsigned)msc.disconnected_events, msc.last_address,
             msc.mounted ? 1 : 0, msc.raw_ready ? 1 : 0, (unsigned)msc.sector_count, (unsigned)msc.sector_size,
             esp_err_to_name(msc.last_mount_err));
    return tcp_single_client_send("control", (const uint8_t *)status, strlen(status));
  }
  if (strncmp(command, "STATUS", 6) == 0) {
    const char *status = usb_msp_transport_is_connected() ? "STATUS USB_CDC_CONNECTED\n" : "STATUS USB_CDC_DISCONNECTED\n";
    return tcp_single_client_send("control", (const uint8_t *)status, strlen(status));
  }
  if (strncmp(command, "HELP", 4) == 0) {
    const char *help = "OK commands: STATUS STATUS_VERBOSE LIST GET <name> MSC_SCAN MSC_GET_RAW [bytes] HELP\n";
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
  if (strncmp(command, "MSC_GET_RAW", 11) == 0) {
    size_t raw_size = 0;
    esp_err_t err = usb_msc_blackbox_get_raw_size(&raw_size);
    if (err != ESP_OK) {
      return tcp_single_client_send("control", (const uint8_t *)"ERR MSC raw not available\n", 26);
    }
    usb_msc_blackbox_diag_t msc;
    usb_msc_blackbox_get_diag(&msc);
    char *arg = command + 11;
    while (isspace((unsigned char)*arg)) arg++;
    size_t offset = 0;
    size_t requested = raw_size;
    if (*arg) {
      char *next = NULL;
      size_t first = (size_t)strtoul(arg, &next, 10);
      while (isspace((unsigned char)*next)) next++;
      if (*next) {
        offset = first;
        requested = (size_t)strtoul(next, NULL, 10);
      } else {
        requested = first;
      }
      if (offset > raw_size) offset = raw_size;
      if (requested > raw_size - offset) requested = raw_size - offset;
    }
    char header[64];
    snprintf(header, sizeof(header), "DATA %u\n", (unsigned)requested);
    tcp_single_client_send("control", (const uint8_t *)header, strlen(header));
    uint8_t *buf = malloc(msc.sector_size ? msc.sector_size : 512);
    if (!buf) return ESP_ERR_NO_MEM;
    size_t sector_size = msc.sector_size ? msc.sector_size : 512;
    size_t sent = 0;
    size_t sector = offset / sector_size;
    size_t sector_offset = offset % sector_size;
    if (sector_offset != 0) {
      err = usb_msc_blackbox_read_raw_sector(sector, buf, sector_size);
      if (err != ESP_OK) {
        free(buf);
        return err;
      }
      size_t n = sector_size - sector_offset;
      if (n > requested) n = requested;
      if (tcp_single_client_send("control", buf + sector_offset, n) != ESP_OK) {
        free(buf);
        return ESP_FAIL;
      }
      sent += n;
      sector++;
    }
    for (; sent < requested; sector++) {
      err = usb_msc_blackbox_read_raw_sector(sector, buf, sector_size);
      if (err != ESP_OK) break;
      size_t n = requested - sent;
      if (n > sector_size) n = sector_size;
      if (tcp_single_client_send("control", buf, n) != ESP_OK) break;
      sent += n;
    }
    free(buf);
    return ESP_OK;
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

