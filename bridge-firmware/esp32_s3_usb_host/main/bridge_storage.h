#pragma once

#include <stddef.h>

#include "esp_err.h"

typedef void (*bridge_storage_list_cb_t)(const char *name, size_t size, void *ctx);

esp_err_t bridge_storage_init(void);
esp_err_t bridge_storage_list_blackbox_logs(bridge_storage_list_cb_t cb, void *ctx);
esp_err_t bridge_storage_open_blackbox_log(const char *name, int *fd, size_t *size);

