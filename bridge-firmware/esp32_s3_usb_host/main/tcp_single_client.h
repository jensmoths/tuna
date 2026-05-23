#pragma once

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

typedef esp_err_t (*tcp_single_client_data_cb_t)(const uint8_t *data, size_t len, void *ctx);

esp_err_t tcp_single_client_server_start(
    uint16_t port,
    const char *name,
    tcp_single_client_data_cb_t on_data,
    void *ctx);
esp_err_t tcp_single_client_send(const char *name, const uint8_t *data, size_t len);

