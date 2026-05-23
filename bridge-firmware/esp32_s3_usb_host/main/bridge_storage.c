#include "bridge_storage.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/unistd.h>

#include "bridge_config.h"
#include "esp_log.h"

static const char *TAG = "bridge_storage";

esp_err_t bridge_storage_init(void) {
  if (mkdir(BRIDGE_STORAGE_ROOT, 0775) != 0 && errno != EEXIST) {
    ESP_LOGW(TAG, "storage root not ready: %s", strerror(errno));
    return ESP_FAIL;
  }
  return ESP_OK;
}

esp_err_t bridge_storage_list_blackbox_logs(bridge_storage_list_cb_t cb, void *ctx) {
  DIR *dir = opendir(BRIDGE_STORAGE_ROOT);
  if (dir == NULL) {
    return ESP_FAIL;
  }

  struct dirent *entry;
  while ((entry = readdir(dir)) != NULL) {
    const char *name = entry->d_name;
    const size_t len = strlen(name);
    if (len < 5 || strcmp(name + len - 4, ".bbl") != 0) {
      continue;
    }

    char path[256];
    snprintf(path, sizeof(path), "%s/%s", BRIDGE_STORAGE_ROOT, name);
    struct stat st;
    if (stat(path, &st) == 0 && cb != NULL) {
      cb(name, (size_t)st.st_size, ctx);
    }
  }

  closedir(dir);
  return ESP_OK;
}

esp_err_t bridge_storage_open_blackbox_log(const char *name, int *fd, size_t *size) {
  if (strstr(name, "/") != NULL || strstr(name, "..") != NULL) {
    return ESP_ERR_INVALID_ARG;
  }

  char path[256];
  snprintf(path, sizeof(path), "%s/%s", BRIDGE_STORAGE_ROOT, name);

  struct stat st;
  if (stat(path, &st) != 0) {
    return ESP_FAIL;
  }

  int opened = open(path, O_RDONLY);
  if (opened < 0) {
    return ESP_FAIL;
  }

  *fd = opened;
  *size = (size_t)st.st_size;
  return ESP_OK;
}

