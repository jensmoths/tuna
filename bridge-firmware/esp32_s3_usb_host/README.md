# ESP32-S3 USB-host Bridge firmware

Experimental future **Bridge** firmware for hardware with ESP32-S3 USB OTG/host.

This exists because the current D1 mini / ESP8266 **Bridge** cannot access Betaflight mass-storage mode: the ESP8266 USB connector is USB-serial only, not USB host.

Goal:

- keep the ESP8266 Bridge Wi-Fi behavior: station mode, stable hostname, one active TCP client for raw MSP passthrough
- talk MSP to the flight controller over USB CDC-ACM when Betaflight is in normal mode
- copy completed **Blackbox Logs** from Betaflight mass-storage mode when the FC reboots as USB MSC
- retain copied logs on Bridge-side storage for later **Post-flight Transfer** to the **Host Computer**

This is an ESP-IDF project skeleton, not Arduino/PlatformIO.

## Hardware target

- ESP32-S3 or ESP32-S2 board with USB OTG/host wiring to the FC USB port
- Bridge-side storage large enough for **Blackbox Logs**; prefer microSD
- Host Computer reaches the Bridge over Wi-Fi

Important: ESP32-S3 shares the internal USB PHY between USB-OTG and USB-Serial-JTAG. If using USB host and USB debugging/flashing at the same time, ESP-IDF documents that an external PHY or alternate debug path may be required.

## TCP services

- `5761`: raw MSP passthrough over USB CDC-ACM, one active client only
- `5762`: line-oriented control service

Control commands planned/implemented by this skeleton:

```text
STATUS
LIST
GET <filename>
MSC_SCAN
HELP
```

`GET` streams a copied `.bbl` from Bridge storage to the Host Computer. The FC copy is not deleted.

## Build

Install ESP-IDF, then:

```bash
cd bridge-firmware/esp32_s3_usb_host
idf.py set-target esp32s3
idf.py build
idf.py flash monitor
```

Configure Wi-Fi in `main/bridge_config.h` or via compile definitions.

## Implementation status

Implemented now:

- project layout
- Wi-Fi station setup
- single-client raw TCP server scaffold
- control TCP server scaffold
- Bridge storage API for copied **Blackbox Logs**
- USB host role separation for CDC/MSP and MSC copy workflow

Still hardware/API integration work:

- bind USB CDC-ACM callbacks to `usb_msp_transport.c`
- bind ESP-IDF USB MSC host mount/copy calls in `usb_msc_blackbox.c`
- validate with a real FC in normal USB CDC mode and Betaflight mass-storage mode

Information still needed before completing the USB TODOs:

- exact ESP32-S2/S3 board
- USB D+/D- wiring and VBUS power/sense design
- Bridge-side storage choice and pinout, preferably microSD
- fixed ESP-IDF version
- whether mass storage is triggered by CLI `msc`, a physical/manual action, or both
- whether the target FC re-enumerates from CDC to MSC or exposes a composite device

The intended product path is:

1. Use USB CDC-ACM to talk MSP/CLI to the FC in normal Betaflight mode.
2. Trigger or observe Betaflight mass-storage mode.
3. Mount the FC as USB MSC from the Bridge.
4. Copy completed **Blackbox Logs** to Bridge-side storage.
5. Serve copied logs to the **Host Computer** over Wi-Fi.

References:

- ESP-IDF USB Host docs: https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/usb_host.html
- ESP-IDF MSC host component: https://components.espressif.com/component/espressif/usb_host_msc

