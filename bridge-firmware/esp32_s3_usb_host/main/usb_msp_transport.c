#include "usb_msp_transport.h"

#include <stdbool.h>

#include "esp_log.h"

static const char *TAG = "usb_msp";

static usb_msp_rx_cb_t s_rx_cb;
static void *s_rx_ctx;

esp_err_t usb_msp_transport_init(void) {
  ESP_LOGW(TAG, "USB CDC-ACM MSP transport not bound yet; integrate ESP-IDF cdc_acm_host here");
  return ESP_OK;
}

bool usb_msp_transport_is_connected(void) {
  return false;
}

esp_err_t usb_msp_transport_set_rx_cb(usb_msp_rx_cb_t cb, void *ctx) {
  s_rx_cb = cb;
  s_rx_ctx = ctx;
  (void)s_rx_cb;
  (void)s_rx_ctx;
  return ESP_OK;
}

esp_err_t usb_msp_transport_write(const uint8_t *data, size_t len) {
  (void)data;
  (void)len;
  return ESP_ERR_NOT_SUPPORTED;
}

