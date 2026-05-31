#include "usb_msp_transport.h"

#include <stdbool.h>
#include <string.h>

#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "usb/cdc_acm_host.h"
#include "usb/usb_host.h"
#include "usb_host_common.h"

static const char *TAG = "usb_msp";

static usb_msp_rx_cb_t s_rx_cb;
static void *s_rx_ctx;
static cdc_acm_dev_hdl_t s_cdc_dev;
static SemaphoreHandle_t s_lock;
static usb_msp_transport_diag_t s_diag = {.last_open_err = ESP_ERR_NOT_FOUND};

typedef struct {
  uint16_t vid;
  uint16_t pid;
} usb_id_t;

static const usb_id_t COMMON_FC_CDC_IDS[] = {
    {0x0483, 0x5740}, // STM32 Virtual COM Port, common Betaflight normal-mode USB CDC
    {0x0483, 0x5741},
    {0x2E3C, 0x5740}, // Betaflight USB CDC observed on target FC
    {0x2E8A, 0x000A}, // RP2040 CDC variants sometimes used by FCs
    {0x303A, 0x4001}, // Espressif TinyUSB CDC test/device
    {0x303A, 0x4002},
};

static bool handle_rx(const uint8_t *data, size_t data_len, void *arg) {
  (void)arg;
  usb_msp_rx_cb_t cb = s_rx_cb;
  if (cb != NULL && data_len > 0) cb(data, data_len, s_rx_ctx);
  return true;
}

static void handle_event(const cdc_acm_host_dev_event_data_t *event, void *user_ctx) {
  (void)user_ctx;
  switch (event->type) {
    case CDC_ACM_HOST_ERROR:
      ESP_LOGW(TAG, "CDC-ACM error: %d", event->data.error);
      break;
    case CDC_ACM_HOST_DEVICE_DISCONNECTED:
      ESP_LOGI(TAG, "CDC-ACM device disconnected");
      if (s_lock) xSemaphoreTake(s_lock, portMAX_DELAY);
      cdc_acm_host_close(event->data.cdc_hdl);
      if (s_cdc_dev == event->data.cdc_hdl) s_cdc_dev = NULL;
      if (s_lock) xSemaphoreGive(s_lock);
      break;
    case CDC_ACM_HOST_SERIAL_STATE:
      ESP_LOGD(TAG, "serial state 0x%04x", event->data.serial_state.val);
      break;
    default:
      break;
  }
}


static void handle_new_dev(usb_device_handle_t usb_dev) {
  const usb_device_desc_t *desc = NULL;
  usb_device_info_t info = {0};
  esp_err_t desc_err = usb_host_get_device_descriptor(usb_dev, &desc);
  esp_err_t info_err = usb_host_device_info(usb_dev, &info);

  if (s_lock) xSemaphoreTake(s_lock, portMAX_DELAY);
  s_diag.new_dev_count++;
  if (info_err == ESP_OK) s_diag.last_dev_addr = info.dev_addr;
  if (desc_err == ESP_OK && desc != NULL) {
    s_diag.last_vid = desc->idVendor;
    s_diag.last_pid = desc->idProduct;
    s_diag.last_dev_class = desc->bDeviceClass;
    s_diag.last_dev_subclass = desc->bDeviceSubClass;
    s_diag.last_dev_protocol = desc->bDeviceProtocol;
    ESP_LOGI(TAG, "USB device addr=%u vid=%04x pid=%04x class=%02x/%02x/%02x",
             s_diag.last_dev_addr, s_diag.last_vid, s_diag.last_pid,
             s_diag.last_dev_class, s_diag.last_dev_subclass, s_diag.last_dev_protocol);
  } else {
    ESP_LOGW(TAG, "USB device detected but descriptor read failed: %s", esp_err_to_name(desc_err));
  }
  if (s_lock) xSemaphoreGive(s_lock);
}

static esp_err_t open_known_cdc(cdc_acm_dev_hdl_t *out) {
  const cdc_acm_host_device_config_t dev_config = {
      .connection_timeout_ms = 100,
      .out_buffer_size = 512,
      .in_buffer_size = 512,
      .user_arg = NULL,
      .event_cb = handle_event,
      .data_cb = handle_rx,
  };
  for (size_t i = 0; i < sizeof(COMMON_FC_CDC_IDS) / sizeof(COMMON_FC_CDC_IDS[0]); i++) {
    esp_err_t err = cdc_acm_host_open(COMMON_FC_CDC_IDS[i].vid, COMMON_FC_CDC_IDS[i].pid, 0, &dev_config, out);
    s_diag.last_open_err = err;
    s_diag.last_open_interface = 0;
    if (err == ESP_OK) {
      ESP_LOGI(TAG, "opened CDC-ACM device %04x:%04x", COMMON_FC_CDC_IDS[i].vid, COMMON_FC_CDC_IDS[i].pid);
      goto configure;
    }
  }

  // Flight controllers do not all use the same USB VID/PID. Let the CDC host
  // driver match unknown CDC-class devices, but do not let its bulk-endpoint
  // fallback claim Betaflight mass-storage mode.
  if (s_diag.last_dev_class != 0x02 && s_diag.last_dev_class != 0xef) {
    s_diag.last_open_err = ESP_ERR_NOT_FOUND;
    return ESP_ERR_NOT_FOUND;
  }
  for (uint8_t interface_idx = 0; interface_idx < 4; interface_idx++) {
    esp_err_t err = cdc_acm_host_open(CDC_HOST_ANY_VID, CDC_HOST_ANY_PID, interface_idx, &dev_config, out);
    s_diag.last_open_err = err;
    s_diag.last_open_interface = interface_idx;
    if (err == ESP_OK) {
      ESP_LOGI(TAG, "opened CDC-ACM device with wildcard VID/PID interface %u", interface_idx);
      goto configure;
    }
  }
  return ESP_ERR_NOT_FOUND;

configure:
  cdc_acm_line_coding_t line_coding = {
      .dwDTERate = 115200,
      .bCharFormat = 0,
      .bParityType = 0,
      .bDataBits = 8,
  };
  cdc_acm_host_line_coding_set(*out, &line_coding);
  cdc_acm_host_set_control_line_state(*out, true, false);
  return ESP_OK;
}

static void cdc_open_task(void *arg) {
  (void)arg;
  while (true) {
    if (!usb_msp_transport_is_connected()) {
      cdc_acm_dev_hdl_t dev = NULL;
      if (open_known_cdc(&dev) == ESP_OK) {
        xSemaphoreTake(s_lock, portMAX_DELAY);
        s_cdc_dev = dev;
        xSemaphoreGive(s_lock);
      }
    }
    vTaskDelay(pdMS_TO_TICKS(1000));
  }
}

esp_err_t usb_msp_transport_init(void) {
  if (s_lock == NULL) s_lock = xSemaphoreCreateMutex();
  if (s_lock == NULL) return ESP_ERR_NO_MEM;
  ESP_RETURN_ON_ERROR(bridge_usb_host_start(), TAG, "USB host start failed");
  const cdc_acm_host_driver_config_t driver_config = {
      .driver_task_stack_size = 4096,
      .driver_task_priority = 10,
      .xCoreID = tskNO_AFFINITY,
      .new_dev_cb = handle_new_dev,
  };
  esp_err_t err = cdc_acm_host_install(&driver_config);
  if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) return err;
  BaseType_t ok = xTaskCreate(cdc_open_task, "cdc_open", 4096, NULL, 6, NULL);
  return ok == pdTRUE ? ESP_OK : ESP_ERR_NO_MEM;
}

bool usb_msp_transport_is_connected(void) {
  bool connected;
  if (s_lock) xSemaphoreTake(s_lock, portMAX_DELAY);
  connected = s_cdc_dev != NULL;
  if (s_lock) xSemaphoreGive(s_lock);
  return connected;
}


void usb_msp_transport_get_diag(usb_msp_transport_diag_t *diag) {
  if (diag == NULL) return;
  if (s_lock) xSemaphoreTake(s_lock, portMAX_DELAY);
  *diag = s_diag;
  if (s_lock) xSemaphoreGive(s_lock);
}

esp_err_t usb_msp_transport_set_rx_cb(usb_msp_rx_cb_t cb, void *ctx) {
  s_rx_cb = cb;
  s_rx_ctx = ctx;
  return ESP_OK;
}

esp_err_t usb_msp_transport_write(const uint8_t *data, size_t len) {
  if (data == NULL || len == 0) return ESP_OK;
  if (s_lock) xSemaphoreTake(s_lock, portMAX_DELAY);
  cdc_acm_dev_hdl_t dev = s_cdc_dev;
  if (s_lock) xSemaphoreGive(s_lock);
  if (dev == NULL) return ESP_ERR_INVALID_STATE;
  return cdc_acm_host_data_tx_blocking(dev, data, len, 1000);
}
