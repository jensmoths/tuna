#pragma once

#include <stddef.h>
#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

typedef void (*usb_msp_rx_cb_t)(const uint8_t *data, size_t len, void *ctx);

esp_err_t usb_msp_transport_init(void);
bool usb_msp_transport_is_connected(void);
esp_err_t usb_msp_transport_set_rx_cb(usb_msp_rx_cb_t cb, void *ctx);
esp_err_t usb_msp_transport_write(const uint8_t *data, size_t len);

