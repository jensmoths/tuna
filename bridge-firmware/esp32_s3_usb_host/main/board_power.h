#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

typedef struct {
  esp_err_t last_err;
  uint8_t reg03;
  uint8_t reg07;
  uint8_t reg0a;
  uint8_t reg0b;
  uint8_t reg0c;
  bool otg_enabled;
  bool charge_enabled;
  bool vbus_present;
} bridge_board_power_diag_t;

esp_err_t bridge_board_enable_usb_otg_power(void);
void bridge_board_power_get_diag(bridge_board_power_diag_t *diag);
