#pragma once

#include <stddef.h>
#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

typedef void (*usb_msp_rx_cb_t)(const uint8_t *data, size_t len, void *ctx);

typedef struct {
  uint32_t new_dev_count;
  uint8_t last_dev_addr;
  uint16_t last_vid;
  uint16_t last_pid;
  uint8_t last_dev_class;
  uint8_t last_dev_subclass;
  uint8_t last_dev_protocol;
  esp_err_t last_open_err;
  uint8_t last_open_interface;
} usb_msp_transport_diag_t;

esp_err_t usb_msp_transport_init(void);
bool usb_msp_transport_is_connected(void);
void usb_msp_transport_get_diag(usb_msp_transport_diag_t *diag);
esp_err_t usb_msp_transport_set_rx_cb(usb_msp_rx_cb_t cb, void *ctx);
esp_err_t usb_msp_transport_write(const uint8_t *data, size_t len);
