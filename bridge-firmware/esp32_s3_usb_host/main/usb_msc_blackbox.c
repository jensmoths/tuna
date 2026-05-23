#include "usb_msc_blackbox.h"

#include "esp_log.h"

static const char *TAG = "usb_msc_bb";

esp_err_t usb_msc_blackbox_init(void) {
  ESP_LOGW(TAG, "USB MSC Blackbox copy not bound yet; integrate usb_host_msc mount/copy here");
  return ESP_OK;
}

esp_err_t usb_msc_blackbox_scan_and_copy(void) {
  ESP_LOGW(TAG, "MSC scan requested but USB MSC host copy is not implemented yet");
  return ESP_ERR_NOT_SUPPORTED;
}

