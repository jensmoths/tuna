#include "tcp_single_client.h"

#include <errno.h>
#include <stdint.h>
#include <string.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>

#include "bridge_config.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

typedef struct {
  uint16_t port;
  const char *name;
  tcp_single_client_data_cb_t on_data;
  void *ctx;
  int active_fd;
} tcp_server_state_t;

static const char *TAG = "tcp_single";
static tcp_server_state_t s_servers[2];

static void tcp_server_task(void *arg) {
  tcp_server_state_t *state = (tcp_server_state_t *)arg;
  int listen_fd = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
  if (listen_fd < 0) {
    ESP_LOGE(TAG, "%s socket failed errno=%d", state->name, errno);
    vTaskDelete(NULL);
    return;
  }

  int yes = 1;
  setsockopt(listen_fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));

  struct sockaddr_in addr = {
      .sin_family = AF_INET,
      .sin_port = htons(state->port),
      .sin_addr.s_addr = htonl(INADDR_ANY),
  };
  if (bind(listen_fd, (struct sockaddr *)&addr, sizeof(addr)) != 0 || listen(listen_fd, 1) != 0) {
    ESP_LOGE(TAG, "%s bind/listen failed errno=%d", state->name, errno);
    close(listen_fd);
    vTaskDelete(NULL);
    return;
  }

  ESP_LOGI(TAG, "%s listening on %u", state->name, state->port);
  uint8_t rx[BRIDGE_TCP_RX_BYTES];

  while (true) {
    int fd = accept(listen_fd, NULL, NULL);
    if (fd < 0) {
      continue;
    }
    if (state->active_fd >= 0) {
      close(fd);
      continue;
    }

    state->active_fd = fd;
    while (true) {
      const ssize_t got = recv(fd, rx, sizeof(rx), 0);
      if (got <= 0) {
        break;
      }
      if (state->on_data != NULL && state->on_data(rx, (size_t)got, state->ctx) != ESP_OK) {
        break;
      }
    }

    close(fd);
    state->active_fd = -1;
  }
}

esp_err_t tcp_single_client_server_start(
    uint16_t port,
    const char *name,
    tcp_single_client_data_cb_t on_data,
    void *ctx) {
  for (size_t i = 0; i < sizeof(s_servers) / sizeof(s_servers[0]); i++) {
    if (s_servers[i].name == NULL) {
      s_servers[i] = (tcp_server_state_t){
          .port = port,
          .name = name,
          .on_data = on_data,
          .ctx = ctx,
          .active_fd = -1,
      };
      xTaskCreate(tcp_server_task, name, 4096, &s_servers[i], 5, NULL);
      return ESP_OK;
    }
  }
  return ESP_ERR_NO_MEM;
}

esp_err_t tcp_single_client_send(const char *name, const uint8_t *data, size_t len) {
  for (size_t i = 0; i < sizeof(s_servers) / sizeof(s_servers[0]); i++) {
    if (s_servers[i].name != NULL && strcmp(s_servers[i].name, name) == 0) {
      if (s_servers[i].active_fd < 0) {
        return ESP_ERR_INVALID_STATE;
      }
      return send(s_servers[i].active_fd, data, len, 0) == (ssize_t)len ? ESP_OK : ESP_FAIL;
    }
  }
  return ESP_ERR_NOT_FOUND;
}

