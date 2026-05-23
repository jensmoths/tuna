#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$ROOT_DIR/bin"
SDK_ROOT="${SDK_ROOT:-$HOME/.local/opt/esp8266/ESP8266_NONOS_SDK}"
PORT="${1:-${ESP_PORT:-}}"
BAUD="${ESP_BAUD:-460800}"
ESPTOOL_BIN="${ESPTOOL_BIN:-$(command -v esptool.py || command -v esptool || true)}"

if [ -z "$PORT" ]; then
  echo "usage: $0 <serial-port>" >&2
  exit 1
fi

if [ ! -x "$ESPTOOL_BIN" ]; then
  echo "esptool missing" >&2
  exit 1
fi

APP_BIN="${APP_BIN:-$BIN_DIR/upgrade/user1.4096.new.4.bin}"

if [ ! -f "$APP_BIN" ]; then
  echo "firmware bin missing; run build.sh first" >&2
  exit 1
fi

if [ ! -f "$SDK_ROOT/bin/boot_v1.7.bin" ] || [ ! -f "$SDK_ROOT/bin/esp_init_data_default_v08.bin" ] || [ ! -f "$SDK_ROOT/bin/blank.bin" ]; then
  echo "sdk flash support bins missing under $SDK_ROOT/bin" >&2
  exit 1
fi

"$ESPTOOL_BIN" --port "$PORT" --baud "$BAUD" write_flash \
  --flash_mode dio \
  --flash_freq 40m \
  --flash_size 4MB \
  0x00000 "$SDK_ROOT/bin/boot_v1.7.bin" \
  0x01000 "$APP_BIN" \
  0x3fc000 "$SDK_ROOT/bin/esp_init_data_default_v08.bin" \
  0x3fe000 "$SDK_ROOT/bin/blank.bin"
