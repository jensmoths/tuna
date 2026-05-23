#pragma once

#include "esp_err.h"

esp_err_t usb_msc_blackbox_init(void);
esp_err_t usb_msc_blackbox_scan_and_copy(void);

