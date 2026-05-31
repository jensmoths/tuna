# ESP32-S3 USB-host Bridge firmware

Experimental future **Bridge** firmware for hardware with ESP32-S3 USB OTG/host.

This exists because the current D1 mini / ESP8266 **Bridge** cannot access Betaflight mass-storage mode: the ESP8266 USB connector is USB-serial only, not USB host.

Goal:

- keep the ESP8266 Bridge Wi-Fi behavior: station mode, stable hostname, one active TCP client for raw MSP passthrough
- talk MSP to the flight controller over USB CDC-ACM when Betaflight is in normal mode
- transfer completed **Blackbox Logs** from Betaflight mass-storage mode when the FC reboots as USB MSC
- retain transferred logs on the **Host Computer**; Bridge-side storage is still useful for future buffering but is not required for the validated raw-MSC path

This is an ESP-IDF project skeleton, not Arduino/PlatformIO.

## Hardware target

- ESP32-S3 or ESP32-S2 board with USB OTG/host wiring to the FC USB port
- Bridge-side storage large enough for **Blackbox Logs**; prefer microSD
- Host Computer reaches the Bridge over Wi-Fi

Important: ESP32-S3 shares the internal USB PHY between USB-OTG and USB-Serial-JTAG. If using USB host and USB debugging/flashing at the same time, ESP-IDF documents that an external PHY or alternate debug path may be required.

Validated board: LilyGO T-Display-S3-AMOLED-1.64.

- SY6970 PMU I2C address: `0x6A`
- PMU I2C SDA: GPIO7
- PMU I2C SCL: GPIO6
- ESP32-S3 internal USB OTG D-/D+: GPIO19/GPIO20

The SY6970 OTG registers can be configured successfully on this board, but the tested board did not provide usable 5V on the measured USB-C VBUS pin when powered from BAT. The current validated hardware setup powers the FC separately and uses the Bridge USB data path plus common ground for MSP over USB CDC.

## TCP services

- `5761`: raw MSP passthrough over USB CDC-ACM, one active client only
- `5762`: line-oriented control service

Control commands:

```text
STATUS
STATUS_VERBOSE
LIST
GET <filename>
MSC_SCAN
MSC_GET_RAW [bytes]
HELP
```

`GET` streams a copied `.bbl` from Bridge storage to the Host Computer. The FC copy is not deleted.

`MSC_SCAN` is for FAT-formatted USB MSC devices with visible `.bbl` files. Betaflight mass-storage mode on the validated FC exposes raw Blackbox storage rather than a FAT filesystem, so the validated command for that path is `MSC_GET_RAW [bytes]`.

## Build

Install ESP-IDF, then:

```bash
cd bridge-firmware/esp32_s3_usb_host
idf.py set-target esp32s3
idf.py build
idf.py flash monitor
```

Configure Wi-Fi in `main/bridge_config.h` or via compile definitions. The build also accepts:

```bash
export BRIDGE_WIFI_SSID='your-ssid'
export BRIDGE_WIFI_PASSWORD='your-password'
```

## Implementation status

Implemented and validated now:

- project layout
- Wi-Fi station setup
- single-client raw TCP server
- control TCP server
- Bridge storage API for copied **Blackbox Logs**
- shared USB host task
- USB CDC-ACM MSP passthrough
- USB MSC detection
- USB MSC raw-sector streaming through the control TCP service
- LilyGO T-Display-S3-AMOLED-1.64 SY6970 setup before USB host startup

Validated with a Betaflight FC powered separately:

- FC enumerates over USB CDC as `2e3c:5740`
- `STATUS` reports `USB_CDC_CONNECTED`
- MSP `MSP_API_VERSION` returns API `1.46`
- FC variant/version discovery through FCS returns `BTFL` / `4.5.2`
- read-only Blackbox Log dataflash discovery works
- 1 KiB read-only Blackbox Log dataflash transfer starts with a valid Blackbox header
- CLI `msc` reboots the FC into USB MSC mode as `2e3c:5720`
- USB MSC device installs and reports raw-sector access
- FAT mount fails for Betaflight MSC (`ESP_ERR_INVALID_SIZE`), which is expected for this FC because the MSC device exposes a raw Blackbox Log image instead of a FAT filesystem
- `MSC_GET_RAW 1048576` transferred 1 MiB in about 4.3 seconds over Wi-Fi; the Blackbox header was found at offset `562176`
- `MSC_GET_RAW 1048576` returns `DATA 1048576` and reads from offset zero
- `MSC_GET_RAW 1048576 1048576` returns `DATA 1048576` and reads a 1 MiB range from offset 1 MiB
- Host resume helper validated by continuing a raw transfer from 1 MiB to 2 MiB and writing a trimmed `.bbl` starting with `H Product:Blackbox`
- `STATUS_VERBOSE` reports full USB MSC diagnostics including `msc_sectors`, `msc_sector_size`, and `msc_err`

Still hardware/API integration work:

- turn `MSC_GET_RAW` into a production **Post-flight Transfer** path with progress display and retry policy
- use FC-reported storage/log bounds to avoid downloading unnecessary leading/trailing raw padding
- decide whether this board needs an external 5V path/switch for FC power from Bridge hardware, or document separate FC power as the required v1 setup
- reduce `STATUS_VERBOSE` diagnostics once hardware bring-up is complete

Information still needed before completing the USB TODOs:

- Bridge-side storage choice beyond the internal FAT partition
- whether all target FCs expose Betaflight mass storage as raw Blackbox storage or whether some expose a FAT filesystem
- whether the target FCs have stable Blackbox header offsets or require scanning each raw transfer

The intended product path is:

1. Use USB CDC-ACM to talk MSP/CLI to the FC in normal Betaflight mode.
2. Trigger or observe Betaflight mass-storage mode.
3. Install the FC as USB MSC from the Bridge.
4. Stream raw MSC sectors to the **Host Computer**.
5. Trim leading padding before the `H Product:Blackbox...` header on the **Host Computer** and retain the resulting `.bbl` as the transferred **Blackbox Log**.

References:

- ESP-IDF USB Host docs: https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/usb_host.html
- ESP-IDF MSC host component: https://components.espressif.com/component/espressif/usb_host_msc

