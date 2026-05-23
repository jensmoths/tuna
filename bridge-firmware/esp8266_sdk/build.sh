#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$ROOT_DIR/project"
SDK_ROOT="${SDK_ROOT:-$HOME/.local/opt/esp8266/ESP8266_NONOS_SDK}"
TOOLCHAIN_BIN="${TOOLCHAIN_BIN:-$HOME/.local/opt/esp8266/toolchain-local/usr/bin}"

export PATH="$TOOLCHAIN_BIN:$PATH"

if [ ! -d "$SDK_ROOT" ]; then
  echo "SDK missing: $SDK_ROOT" >&2
  exit 1
fi

if ! command -v xtensa-lx106-elf-gcc >/dev/null 2>&1; then
  echo "xtensa-lx106-elf-gcc missing on PATH" >&2
  exit 1
fi

make -C "$PROJECT_DIR" \
  SDK_ROOT="$SDK_ROOT" \
  COMPILE=gcc \
  PYTHON=python3 \
  BOOT=new \
  APP=1 \
  SPI_SPEED=40 \
  SPI_MODE=DIO \
  SPI_SIZE_MAP=4 \
  "$@"
