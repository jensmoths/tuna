#include "usb_msc_blackbox.h"

#include <dirent.h>
#include <errno.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/unistd.h>

#include "bridge_config.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_vfs_fat.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "usb/msc_host_vfs.h"
#include "usb_host_common.h"

static const char *TAG = "usb_msc_bb";
#define MSC_MOUNT_PATH "/usb0"
#define COPY_BUF_BYTES 4096

typedef enum { MSC_EVENT_CONNECTED, MSC_EVENT_DISCONNECTED } msc_event_id_t;
typedef struct {
  msc_event_id_t id;
  union {
    uint8_t address;
    msc_host_device_handle_t handle;
  } data;
} msc_msg_t;

static QueueHandle_t s_queue;
static SemaphoreHandle_t s_lock;
static msc_host_device_handle_t s_device;
static msc_host_vfs_handle_t s_vfs;
static bool s_mounted;
static bool s_raw_ready;
static usb_msc_blackbox_diag_t s_diag = {.last_mount_err = ESP_ERR_INVALID_STATE};

static bool has_bbl_extension(const char *name) {
  size_t len = strlen(name);
  if (len < 5) return false;
  const char *ext = name + len - 4;
  return strcasecmp(ext, ".bbl") == 0;
}

static esp_err_t copy_file(const char *src_path, const char *name) {
  char dst_path[256];
  int written = snprintf(dst_path, sizeof(dst_path), "%s/%s", BRIDGE_STORAGE_ROOT, name);
  if (written < 0 || written >= (int)sizeof(dst_path)) return ESP_ERR_INVALID_ARG;

  FILE *src = fopen(src_path, "rb");
  if (!src) {
    ESP_LOGW(TAG, "open source failed %s errno=%d", src_path, errno);
    return ESP_FAIL;
  }
  FILE *dst = fopen(dst_path, "wb");
  if (!dst) {
    ESP_LOGW(TAG, "open destination failed %s errno=%d", dst_path, errno);
    fclose(src);
    return ESP_FAIL;
  }

  uint8_t *buf = malloc(COPY_BUF_BYTES);
  if (!buf) {
    fclose(src);
    fclose(dst);
    return ESP_ERR_NO_MEM;
  }
  esp_err_t result = ESP_OK;
  size_t total = 0;
  while (true) {
    size_t got = fread(buf, 1, COPY_BUF_BYTES, src);
    if (got > 0) {
      if (fwrite(buf, 1, got, dst) != got) {
        result = ESP_FAIL;
        break;
      }
      total += got;
    }
    if (got < COPY_BUF_BYTES) {
      if (ferror(src)) result = ESP_FAIL;
      break;
    }
  }
  free(buf);
  fclose(src);
  fclose(dst);
  if (result == ESP_OK) ESP_LOGI(TAG, "copied Blackbox Log %s (%u bytes)", name, (unsigned)total);
  return result;
}

static esp_err_t copy_bbls_from_dir(const char *dir_path, int depth, int *copied) {
  if (depth > 4) return ESP_OK;
  DIR *dir = opendir(dir_path);
  if (!dir) return ESP_FAIL;

  struct dirent *entry;
  while ((entry = readdir(dir)) != NULL) {
    const char *name = entry->d_name;
    if (strcmp(name, ".") == 0 || strcmp(name, "..") == 0) continue;
    char path[256];
    int written = snprintf(path, sizeof(path), "%s/%s", dir_path, name);
    if (written < 0 || written >= (int)sizeof(path)) continue;

    struct stat st;
    if (stat(path, &st) != 0) continue;
    if (S_ISDIR(st.st_mode)) {
      copy_bbls_from_dir(path, depth + 1, copied);
    } else if (S_ISREG(st.st_mode) && has_bbl_extension(name)) {
      if (copy_file(path, name) == ESP_OK) (*copied)++;
    }
  }
  closedir(dir);
  return ESP_OK;
}

static int find_usb_addr_by_handle(msc_host_device_handle_t handle) {
  if (s_device == handle) return 0;
  return -1;
}

static void msc_event_cb(const msc_host_event_t *event, void *arg) {
  (void)arg;
  if (!s_queue) return;
  msc_msg_t msg = {0};
  if (event->event == MSC_DEVICE_CONNECTED) {
    msg.id = MSC_EVENT_CONNECTED;
    msg.data.address = event->device.address;
    s_diag.connected_events++;
    s_diag.last_address = event->device.address;
    xQueueSend(s_queue, &msg, 0);
  } else if (event->event == MSC_DEVICE_DISCONNECTED) {
    msg.id = MSC_EVENT_DISCONNECTED;
    msg.data.handle = event->device.handle;
    s_diag.disconnected_events++;
    xQueueSend(s_queue, &msg, 0);
  }
}

static esp_err_t mount_device(uint8_t address) {
  if (s_device) return ESP_OK;
  esp_err_t install_err = msc_host_install_device(address, &s_device);
  s_diag.last_mount_err = install_err;
  ESP_RETURN_ON_ERROR(install_err, TAG, "install MSC device failed");

  msc_host_device_info_t info = {0};
  if (msc_host_get_device_info(s_device, &info) == ESP_OK) {
    s_diag.sector_count = info.sector_count;
    s_diag.sector_size = info.sector_size;
    s_raw_ready = true;
    s_diag.raw_ready = true;
    ESP_LOGI(TAG, "MSC raw ready sectors=%u sector_size=%u vid=%04x pid=%04x",
             (unsigned)info.sector_count, (unsigned)info.sector_size, info.idVendor, info.idProduct);
  }

  const esp_vfs_fat_mount_config_t mount_config = {
      .format_if_mount_failed = false,
      .max_files = 4,
      .allocation_unit_size = 8192,
  };
  esp_err_t err = msc_host_vfs_register(s_device, MSC_MOUNT_PATH, &mount_config, &s_vfs);
  s_diag.last_mount_err = err;
  if (err != ESP_OK) {
    // Betaflight mass-storage exposes the raw Blackbox Log image, not necessarily a FAT filesystem.
    ESP_LOGW(TAG, "MSC FAT mount failed: %s; keeping raw sector access", esp_err_to_name(err));
    return ESP_OK;
  }
  s_mounted = true;
  s_diag.mounted = true;
  s_diag.last_mount_err = ESP_OK;
  ESP_LOGI(TAG, "MSC mounted at %s", MSC_MOUNT_PATH);
  return ESP_OK;
}

static void unmount_device(void) {
  if (s_vfs) {
    msc_host_vfs_unregister(s_vfs);
    s_vfs = NULL;
  }
  if (s_device) {
    msc_host_uninstall_device(s_device);
    s_device = NULL;
  }
  s_mounted = false;
  s_raw_ready = false;
  s_diag.mounted = false;
  s_diag.raw_ready = false;
}

static void msc_task(void *arg) {
  (void)arg;
  while (true) {
    msc_msg_t msg;
    if (xQueueReceive(s_queue, &msg, portMAX_DELAY) != pdTRUE) continue;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    if (msg.id == MSC_EVENT_CONNECTED) {
      esp_err_t err = mount_device(msg.data.address);
      if (err != ESP_OK) ESP_LOGW(TAG, "mount MSC failed: %s", esp_err_to_name(err));
    } else if (msg.id == MSC_EVENT_DISCONNECTED) {
      if (find_usb_addr_by_handle(msg.data.handle) >= 0) {
        ESP_LOGI(TAG, "MSC disconnected");
      }
      unmount_device();
    }
    xSemaphoreGive(s_lock);
  }
}

esp_err_t usb_msc_blackbox_init(void) {
  if (!s_queue) s_queue = xQueueCreate(4, sizeof(msc_msg_t));
  if (!s_lock) s_lock = xSemaphoreCreateMutex();
  if (!s_queue || !s_lock) return ESP_ERR_NO_MEM;
  ESP_RETURN_ON_ERROR(bridge_usb_host_start(), TAG, "USB host start failed");
  const msc_host_driver_config_t msc_config = {
      .create_backround_task = true,
      .task_priority = 5,
      .stack_size = 4096,
      .callback = msc_event_cb,
  };
  esp_err_t err = msc_host_install(&msc_config);
  if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) return err;
  BaseType_t ok = xTaskCreate(msc_task, "msc_bb", 6144, NULL, 5, NULL);
  return ok == pdTRUE ? ESP_OK : ESP_ERR_NO_MEM;
}

esp_err_t usb_msc_blackbox_scan_and_copy(void) {
  if (!s_lock) return ESP_ERR_INVALID_STATE;
  xSemaphoreTake(s_lock, portMAX_DELAY);
  bool mounted = s_mounted;
  xSemaphoreGive(s_lock);
  if (!mounted) return ESP_ERR_INVALID_STATE;
  int copied = 0;
  esp_err_t err = copy_bbls_from_dir(MSC_MOUNT_PATH, 0, &copied);
  if (err == ESP_OK) ESP_LOGI(TAG, "MSC scan complete, copied %d Blackbox Logs", copied);
  return err;
}

void usb_msc_blackbox_get_diag(usb_msc_blackbox_diag_t *diag) {
  if (diag == NULL) return;
  if (s_lock) xSemaphoreTake(s_lock, portMAX_DELAY);
  s_diag.mounted = s_mounted;
  s_diag.raw_ready = s_raw_ready;
  *diag = s_diag;
  if (s_lock) xSemaphoreGive(s_lock);
}

esp_err_t usb_msc_blackbox_get_raw_size(size_t *size) {
  if (size == NULL) return ESP_ERR_INVALID_ARG;
  if (!s_lock) return ESP_ERR_INVALID_STATE;
  xSemaphoreTake(s_lock, portMAX_DELAY);
  if (!s_device || !s_raw_ready || s_diag.sector_size == 0) {
    xSemaphoreGive(s_lock);
    return ESP_ERR_INVALID_STATE;
  }
  *size = (size_t)s_diag.sector_count * (size_t)s_diag.sector_size;
  xSemaphoreGive(s_lock);
  return ESP_OK;
}

esp_err_t usb_msc_blackbox_read_raw_sector(size_t sector, void *data, size_t size) {
  if (data == NULL) return ESP_ERR_INVALID_ARG;
  if (!s_lock) return ESP_ERR_INVALID_STATE;
  xSemaphoreTake(s_lock, portMAX_DELAY);
  if (!s_device || !s_raw_ready) {
    xSemaphoreGive(s_lock);
    return ESP_ERR_INVALID_STATE;
  }
  esp_err_t err = msc_host_read_sector(s_device, sector, data, size);
  xSemaphoreGive(s_lock);
  return err;
}
