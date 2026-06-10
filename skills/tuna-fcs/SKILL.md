---
name: tuna-fcs
description: Use the standalone Tuna FCS CLI for flight-controller operations over the FC Bridge or direct USB.
license: MIT
---

# Tuna FCS

Use this skill when an agent needs flight-controller operations without using the Tuna web Operator Console, Tuning Agent Loop, or SQLite database.

## Boundary

- Use `tuna-fcs` when installed as a console script, or `python3 -m tuna_fcs.cli` from the repository.
- FCS supports two connection types:
  - `bridge`: FC Bridge over TCP/Wi-Fi.
  - `usb`: direct USB serial/MSC on the same **Host Computer**.
- Do not use raw Bridge protocol access from agents. Use the FCS CLI/API.
- Use `--json` for machine-readable output.
- FCS must not read or write Tuna SQLite state.

## Environment defaults

- `FCS_CONNECTION`: `bridge` or `usb`.
- `FCS_BRIDGE_HOST`: Bridge host name/IP.
- `FCS_USB_DEVICE`: USB serial device, e.g. `/dev/ttyACM0`; omit to auto-detect.

## Inspect FC

Bridge:

```bash
tuna-fcs inspect --connection bridge --bridge-host tuna-bridge-usb --json
```

Direct USB:

```bash
tuna-fcs inspect --connection usb --usb-device /dev/ttyACM0 --json
```

If `--usb-device` is omitted, FCS attempts auto-detection. If multiple serial devices are present, pass `--usb-device` explicitly.

## Transfer Blackbox Logs

Bridge:

```bash
tuna-fcs blackbox transfer \
  --connection bridge \
  --bridge-host tuna-bridge-usb \
  --output transferred-logs/current-flight.bbl \
  --json
```

Direct USB:

```bash
tuna-fcs blackbox transfer \
  --connection usb \
  --usb-device /dev/ttyACM0 \
  --output transferred-logs/current-flight.bbl \
  --json
```

Success evidence:

- `download.starts_with_blackbox_header` is `true`.
- `download.written_bytes` is greater than zero.
- The output path points to a retained **Blackbox Log** on the **Host Computer**.

After MSC transfer, the FC may need Operator reset/power-cycle back to USB CDC/MSP before further FC operations.

## Erase transferred FC Blackbox storage

Only erase after transfer validation, Host Computer retention, and any required Import have succeeded.

```bash
tuna-fcs blackbox erase \
  --connection usb \
  --confirm erase-transferred-blackbox-log \
  --json
```

Use `--connection bridge --bridge-host ...` for Bridge.

## Write Betaflight CLI

Only write CLI text after the caller has performed its own safety checks and any required human approval.

```bash
tuna-fcs cli write \
  --connection usb \
  --cli-file approved-change.cli \
  --confirm write-fc-cli \
  --json
```

Use `--command 'set name = value'` for one-off commands. FCS appends `save` through the write helper.
