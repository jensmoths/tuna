#include "board_power.h"

#include <stdbool.h>

#include "driver/i2c.h"
#include "esp_check.h"
#include "esp_log.h"

#define SY6970_I2C_PORT I2C_NUM_0
#define SY6970_I2C_ADDR 0x6A
#define SY6970_I2C_SDA GPIO_NUM_7
#define SY6970_I2C_SCL GPIO_NUM_6
#define SY6970_I2C_FREQ_HZ 100000

#define SY6970_REG_INPUT_SRC_CTRL 0x00
#define SY6970_REG_ADC_CTRL 0x02
#define SY6970_REG_POWER_ON_CFG 0x03
#define SY6970_REG_CHARGER_CTRL 0x07
#define SY6970_REG_BOOST_CTRL 0x0A
#define SY6970_REG_SYSTEM_STATUS 0x0B
#define SY6970_REG_FAULT_STATUS 0x0C
#define SY6970_CHG_CONFIG_BIT BIT(4)
#define SY6970_OTG_CONFIG_BIT BIT(5)
#define SY6970_WATCHDOG_MASK (BIT(4) | BIT(5))

static const char *TAG = "board_power";
static bool s_i2c_installed;
static bool s_otg_enabled;
static bridge_board_power_diag_t s_diag = {.last_err = ESP_ERR_INVALID_STATE};

static esp_err_t sy6970_i2c_init(void) {
  if (s_i2c_installed) return ESP_OK;
  const i2c_config_t conf = {
      .mode = I2C_MODE_MASTER,
      .sda_io_num = SY6970_I2C_SDA,
      .scl_io_num = SY6970_I2C_SCL,
      .sda_pullup_en = GPIO_PULLUP_ENABLE,
      .scl_pullup_en = GPIO_PULLUP_ENABLE,
      .master.clk_speed = SY6970_I2C_FREQ_HZ,
      .clk_flags = 0,
  };
  ESP_RETURN_ON_ERROR(i2c_param_config(SY6970_I2C_PORT, &conf), TAG, "configure I2C");
  esp_err_t err = i2c_driver_install(SY6970_I2C_PORT, conf.mode, 0, 0, 0);
  if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) return err;
  s_i2c_installed = true;
  return ESP_OK;
}

static esp_err_t sy6970_read_reg(uint8_t reg, uint8_t *value) {
  return i2c_master_write_read_device(SY6970_I2C_PORT, SY6970_I2C_ADDR, &reg, 1, value, 1, pdMS_TO_TICKS(100));
}

static esp_err_t sy6970_write_reg(uint8_t reg, uint8_t value) {
  const uint8_t bytes[2] = {reg, value};
  return i2c_master_write_to_device(SY6970_I2C_PORT, SY6970_I2C_ADDR, bytes, sizeof(bytes), pdMS_TO_TICKS(100));
}

static void update_diag(esp_err_t last_err) {
  s_diag.last_err = last_err;
  if (sy6970_read_reg(SY6970_REG_POWER_ON_CFG, &s_diag.reg03) == ESP_OK) {
    s_diag.otg_enabled = (s_diag.reg03 & SY6970_OTG_CONFIG_BIT) != 0;
    s_diag.charge_enabled = (s_diag.reg03 & SY6970_CHG_CONFIG_BIT) != 0;
  }
  sy6970_read_reg(SY6970_REG_CHARGER_CTRL, &s_diag.reg07);
  sy6970_read_reg(SY6970_REG_BOOST_CTRL, &s_diag.reg0a);
  sy6970_read_reg(SY6970_REG_FAULT_STATUS, &s_diag.reg0c);
  if (sy6970_read_reg(SY6970_REG_SYSTEM_STATUS, &s_diag.reg0b) == ESP_OK) {
    // REG0B bits 7:5 are VBUS status on the SY6970/BQ25896 family; non-zero means VBUS is detected.
    s_diag.vbus_present = (s_diag.reg0b & 0xE0) != 0;
  }
}

esp_err_t bridge_board_enable_usb_otg_power(void) {
  if (s_otg_enabled) return ESP_OK;
  esp_err_t err = sy6970_i2c_init();
  if (err != ESP_OK) {
    s_diag.last_err = err;
    ESP_RETURN_ON_ERROR(err, TAG, "SY6970 I2C init");
  }

  // Match the LilyGO SY6970 initialization sequence for this board.
  // REG00=0x08 disables the external ILIM pin so register current limits apply.
  err = sy6970_write_reg(SY6970_REG_INPUT_SRC_CTRL, 0x08);
  if (err != ESP_OK) {
    update_diag(err);
    ESP_RETURN_ON_ERROR(err, TAG, "configure SY6970 input source");
  }
  // REG02=0xdd enables continuous ADC measurement.
  err = sy6970_write_reg(SY6970_REG_ADC_CTRL, 0xdd);
  if (err != ESP_OK) {
    update_diag(err);
    ESP_RETURN_ON_ERROR(err, TAG, "enable SY6970 ADC");
  }
  // REG07=0x8d is LilyGO's watchdog-disabled charger-control setup.
  err = sy6970_write_reg(SY6970_REG_CHARGER_CTRL, 0x8d);
  if (err != ESP_OK) {
    update_diag(err);
    ESP_RETURN_ON_ERROR(err, TAG, "disable SY6970 watchdog");
  }
  // REG0A high nibble sets OTG boost voltage. 0x80 ~= 5062 mV, low bits 0 = 500 mA limit.
  err = sy6970_write_reg(SY6970_REG_BOOST_CTRL, 0x80);
  if (err != ESP_OK) {
    update_diag(err);
    ESP_RETURN_ON_ERROR(err, TAG, "configure SY6970 OTG boost");
  }

  uint8_t reg03 = 0;
  err = sy6970_read_reg(SY6970_REG_POWER_ON_CFG, &reg03);
  if (err != ESP_OK) {
    update_diag(err);
    ESP_RETURN_ON_ERROR(err, TAG, "read SY6970 REG03");
  }
  // In OTG mode the charger must not also try to consume VBUS.
  uint8_t new_reg03 = (reg03 & (uint8_t)~SY6970_CHG_CONFIG_BIT) | SY6970_OTG_CONFIG_BIT;
  if (new_reg03 != reg03) {
    err = sy6970_write_reg(SY6970_REG_POWER_ON_CFG, new_reg03);
    if (err != ESP_OK) {
      update_diag(err);
      ESP_RETURN_ON_ERROR(err, TAG, "enable SY6970 OTG");
    }
  }

  uint8_t verify = 0;
  err = sy6970_read_reg(SY6970_REG_POWER_ON_CFG, &verify);
  if (err != ESP_OK) {
    update_diag(err);
    ESP_RETURN_ON_ERROR(err, TAG, "verify SY6970 OTG");
  }
  update_diag(ESP_OK);
  if ((verify & SY6970_OTG_CONFIG_BIT) == 0) {
    ESP_LOGW(TAG, "SY6970 OTG bit did not stay enabled (REG03=0x%02x)", verify);
    s_diag.last_err = ESP_FAIL;
    return ESP_FAIL;
  }

  s_otg_enabled = true;
  ESP_LOGI(TAG, "SY6970 OTG requested reg03=0x%02x reg07=0x%02x reg0b=0x%02x",
           s_diag.reg03, s_diag.reg07, s_diag.reg0b);
  return ESP_OK;
}

void bridge_board_power_get_diag(bridge_board_power_diag_t *diag) {
  if (diag == NULL) return;
  if (s_i2c_installed) update_diag(s_diag.last_err);
  *diag = s_diag;
}
