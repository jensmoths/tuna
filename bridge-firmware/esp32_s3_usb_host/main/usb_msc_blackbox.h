#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#include "esp_err.h"

typedef void (*usb_msc_blackbox_list_cb_t)(const char *name, size_t size, void *ctx);

typedef struct {
  uint32_t connected_events;
  uint32_t disconnected_events;
  uint8_t last_address;
  bool mounted;
  bool raw_ready;
  esp_err_t last_mount_err;
  uint32_t sector_count;
  uint32_t sector_size;
} usb_msc_blackbox_diag_t;

esp_err_t usb_msc_blackbox_init(void);
esp_err_t usb_msc_blackbox_scan_and_copy(void);
esp_err_t usb_msc_blackbox_list_logs(usb_msc_blackbox_list_cb_t cb, void *ctx);
esp_err_t usb_msc_blackbox_open_log(const char *name, FILE **file, size_t *size);
void usb_msc_blackbox_get_diag(usb_msc_blackbox_diag_t *diag);
esp_err_t usb_msc_blackbox_get_raw_size(size_t *size);
esp_err_t usb_msc_blackbox_read_raw_sector(size_t sector, void *data, size_t size);
