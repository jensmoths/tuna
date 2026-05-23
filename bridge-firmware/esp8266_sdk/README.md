# ESP8266 Non-OS SDK Bridge firmware

Current working **Bridge** firmware for the D1 mini / ESP8266 UART-to-Wi-Fi path.

This firmware is validated with the host-side **FCS** MSP client against Betaflight `4.5.2` and supports read-only **Blackbox Log** transfer from FC dataflash through MSP.

## Local setup now present

Installed locally under your user account:

- SDK source: `~/.local/opt/esp8266/ESP8266_NONOS_SDK`
- xtensa toolchain: `~/.local/opt/esp8266/toolchain-local/usr/bin`
- esptool: `~/.local/bin/esptool.py`

No PlatformIO. No Arduino.

## Project layout

- `project/` — actual ESP8266 Non-OS SDK app
- `project/include/` — firmware headers
- `project/user/` — firmware sources
- `build.sh` — build helper
- `flash.sh` — flash helper

## Board wiring assumption

For a **D1 mini** with swapped UART0:

- `system_uart_swap()` moves UART0 to:
  - `TX -> GPIO15 / D8`
  - `RX -> GPIO13 / D7`

Cross-connect to the flight controller:

- `FC TX -> D7`
- `FC RX -> D8`
- `GND -> GND`

Caveat:
- `GPIO15 / D8` is a boot strap pin and must stay low at boot.
- Swapped UART0 is still the right runtime choice here because it keeps the FC stream off the USB flashing UART, but your attached FC UART must not break ESP8266 boot.

## Build

```bash
./bridge-firmware/esp8266_sdk/build.sh
```

Useful overrides:

```bash
SDK_ROOT=/custom/sdk/path ./bridge-firmware/esp8266_sdk/build.sh
TOOLCHAIN_BIN=/custom/toolchain/bin ./bridge-firmware/esp8266_sdk/build.sh
```

Current build assumptions:

- ESP8266 Non-OS SDK
- `BOOT=new`
- `APP=1`
- `SPI_MODE=DIO`
- `SPI_SPEED=40`
- `SPI_SIZE_MAP=4` (4 MB flash, 512KB+512KB map)

## Flash

```bash
./bridge-firmware/esp8266_sdk/flash.sh /dev/ttyUSB0
```

or

```bash
ESP_PORT=/dev/ttyUSB0 ./bridge-firmware/esp8266_sdk/flash.sh
```

## What the firmware does

- joins an existing Wi-Fi network in station mode
- sets a stable hostname
- listens on one fixed TCP port
- permits one active TCP client only
- forwards raw bytes between TCP and swapped UART0
- disconnects the client on internal buffer overflow
- returns to idle after disconnect
- keeps retrying Wi-Fi connection while disconnected

Current tuning for Blackbox transfer:

- FC UART baud: `115200`
- FC-to-client buffer: `8192` bytes
- TCP send chunk: `512` bytes

MSP v2 dataflash reads above roughly `512` bytes per request have been unstable on the current D1 mini/FC path, so the host downloader defaults to stable `512` byte chunks.

## Config knobs

Edit or override macros in `project/include/bridge_config.h`:

- `BRIDGE_WIFI_SSID`
- `BRIDGE_WIFI_PASSWORD`
- `BRIDGE_HOSTNAME`
- `BRIDGE_TCP_PORT`
- `BRIDGE_FC_BAUD`
- `BRIDGE_WIFI_RETRY_MS`
- `BRIDGE_PUMP_INTERVAL_MS`
- `BRIDGE_CLIENT_TO_FC_BUFFER_BYTES`
- `BRIDGE_FC_TO_CLIENT_BUFFER_BYTES`
- `BRIDGE_TCP_CHUNK_BYTES`

Do not commit real Wi-Fi credentials. For local builds, pass credentials as compiler definitions or edit your local working copy only.

## Validation status

Validated so far:
- local SDK and toolchain setup
- host-side `ring_buffer` unit test via `g++`
- full firmware build against the installed SDK
- flash to D1 mini via `/dev/ttyUSB0`
- Wi-Fi join on local network
- Bridge hostname resolution as `tuna-bridge`
- single-client TCP behavior on port `5761`
- TCP/UART MSP passthrough to Betaflight
- FCS Blackbox storage discovery over MSP
- read-only Blackbox byte-range transfer over MSP
- 64 KiB transfer at about `6.4 KB/s` using MSP v2 + 512 byte chunks

Not yet validated:
- complete 16 MiB transfer openable in Blackbox Explorer
- higher UART baud rates
- chunk sizes above 512 bytes without Bridge/FC disconnects

## Current hardware limitations

The D1 mini / ESP8266 **Bridge** cannot read Betaflight mass-storage mode because it is not USB host-capable. It also has only about 3 MiB of practical spare internal flash in the current layout, which is too small for the FC's current 16 MiB Blackbox dataflash image.

For faster future **Post-flight Transfer**, see `../esp32_s3_usb_host/README.md` and `../../docs/future-hardware-notes.md`.
