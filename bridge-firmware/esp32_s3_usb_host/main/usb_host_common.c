#include "usb_host_common.h"

#include "board_power.h"
#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "usb/usb_host.h"

static const char *TAG = "usb_host";
static bool s_started;

static void usb_host_task(void *arg) {
  (void)arg;
  while (true) {
    uint32_t event_flags = 0;
    esp_err_t err = usb_host_lib_handle_events(portMAX_DELAY, &event_flags);
    if (err != ESP_OK) {
      ESP_LOGW(TAG, "usb_host_lib_handle_events: %s", esp_err_to_name(err));
      continue;
    }
    if (event_flags & USB_HOST_LIB_EVENT_FLAGS_NO_CLIENTS) {
      usb_host_device_free_all();
    }
  }
}

esp_err_t bridge_usb_host_start(void) {
  if (s_started) return ESP_OK;
  ESP_RETURN_ON_ERROR(bridge_board_enable_usb_otg_power(), TAG, "enable board USB OTG power");

  const usb_host_config_t host_config = {
      .skip_phy_setup = false,
      .intr_flags = ESP_INTR_FLAG_LEVEL1,
  };
  esp_err_t err = usb_host_install(&host_config);
  if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) return err;
  BaseType_t ok = xTaskCreate(usb_host_task, "usb_host", 4096, NULL, 20, NULL);
  if (ok != pdTRUE) return ESP_ERR_NO_MEM;
  s_started = true;
  return ESP_OK;
}
