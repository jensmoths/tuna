# FCS host Bridge tooling

Host-side **FCS** tooling for the Tuna **Bridge**. The currently validated paths are:

Current observed Bridge name/IP on this network: `tuna-bridge-usb` / `192.168.31.117`.

```text
Host Computer --Wi-Fi/TCP--> ESP8266 Bridge --UART/MSP--> Betaflight FC
Host Computer --Wi-Fi/TCP--> ESP32-S3 Bridge --USB CDC/MSP--> Betaflight FC
Host Computer --Wi-Fi/TCP--> ESP32-S3 Bridge --USB MSC/raw sectors--> Betaflight FC
```

This supports **Blackbox Log** discovery and transfer from FC dataflash. After a validated **Post-flight Transfer** and host-side retention/import, Tuna should erase the transferred FC copy through FCS; deletion must not happen before validation succeeds.

## Files

- `fcs_bridge/bridge_transport.py` — host-side Bridge TCP transport that owns connect/disconnect lifecycle
- `fcs_bridge/msp.py` — MSP v1/v2 frame helpers and Betaflight dataflash parsers
- `fcs_bridge/msp_client.py` — reusable synchronous MSP client
- `fcs_bridge/fc_discovery.py` — FC identity and Blackbox storage discovery
- `fcs_bridge/blackbox_transfer.py` — MSP dataflash byte-range transfer and erase helpers
- `fcs_connectivity_tracer.py` — CLI smoke tracer against a real Bridge
- `fc_passthrough_smoke.py` — MSP passthrough smoke test against a real FC
- `fcs_blackbox_storage_probe.py` — read-only Blackbox storage discovery
- `fcs_blackbox_read_probe.py` — small diagnostic byte-range read
- `fcs_blackbox_download.py` — full FC-reported used dataflash download to `.bbl`
- `fcs_blackbox_erase.py` — erase transferred FC Blackbox Log storage after validated host-side transfer/import
- `fcs_msc_raw_download.py` — raw Betaflight USB MSC transfer helper; trims leading padding before the Blackbox header
- `tests/test_bridge_transport.py` — stdlib `unittest` contract tests using a local single-client fake Bridge

## Run the tests

```bash
PYTHONPATH=fcs-host python3 -m unittest discover -s fcs-host/tests -v
```

## Run the tracer against the real Bridge

```bash
PYTHONPATH=fcs-host python3 fcs-host/fcs_connectivity_tracer.py tuna-bridge --probe-single-client
```

or by IP:

```bash
PYTHONPATH=fcs-host python3 fcs-host/fcs_connectivity_tracer.py 192.168.31.209 --probe-single-client
```

The tracer currently proves:
- host can resolve the Bridge hostname
- host can establish and tear down the Bridge TCP connection
- a second client is rejected while the first remains connected

## Run MSP passthrough smoke test

```bash
PYTHONPATH=fcs-host python3 fcs-host/fc_passthrough_smoke.py tuna-bridge
```

Validated result on the current FC:

```text
msp api ok protocol=0 api=1.46
msp fc-variant ok variant=BTFL
msp fc-version ok version=4.5.2
```

## Run Blackbox Log storage discovery

This read-only probe asks the flight controller what **Blackbox Log** storage exists. It does not transfer or delete logs.

```bash
PYTHONPATH=fcs-host python3 fcs-host/fcs_blackbox_storage_probe.py tuna-bridge
```

## Read a small Blackbox Log dataflash range

This read-only probe transfers a small byte range from FC dataflash and retains it on the **Host Computer** as a diagnostic artifact.

```bash
PYTHONPATH=fcs-host python3 fcs-host/fcs_blackbox_read_probe.py tuna-bridge --size 1024
```

## Download a complete Blackbox Log dataflash image

This transfers FC-reported used dataflash bytes over MSP into a `.bbl` file on the **Host Computer**. After validation and retention/import succeed, Tuna should erase the transferred FC copy through FCS. This path is useful as a fallback and diagnostic path, but it is much slower than USB MSC.

```bash
PYTHONPATH=fcs-host python3 fcs-host/fcs_blackbox_download.py tuna-bridge
```

The completed file is written under `transferred-logs/` and should be openable in Blackbox Explorer.

## Erase transferred FC Blackbox Log storage

Only erase after Tuna has a validated retained **Blackbox Log** on the **Host Computer** and **Import** succeeded. The FC must be in USB CDC/MSP mode, so after MSC raw transfer the **Operator** must power-cycle/reset the FC before this command can run.

```bash
PYTHONPATH=fcs-host python3 fcs-host/fcs_blackbox_erase.py tuna-bridge-usb \
  --confirm erase-transferred-blackbox-log
```

The confirmation string is intentionally explicit because this erases FC Blackbox storage.

Current downloader defaults:

- MSP version: `2`
- chunk size: `512` bytes
- progress interval: `262144` bytes

Useful overrides:

```bash
PYTHONPATH=fcs-host python3 fcs-host/fcs_blackbox_download.py tuna-bridge --output transferred-logs/my-flight.bbl
PYTHONPATH=fcs-host python3 fcs-host/fcs_blackbox_download.py tuna-bridge --size 1048576
PYTHONPATH=fcs-host python3 fcs-host/fcs_blackbox_download.py tuna-bridge --msp-version 1 --chunk-size 240
```

## Download from Betaflight USB MSC raw storage

This is the preferred fast path for the ESP32-S3 USB-host Bridge. The FC is first put into Betaflight mass-storage mode, usually via CLI `msc`. The validated FC re-enumerates as `2e3c:5720` and exposes raw Blackbox storage, not a FAT filesystem with `.bbl` files. The Bridge command is therefore `MSC_GET_RAW [bytes]` or `MSC_GET_RAW [offset] [bytes]`, not `MSC_SCAN`.

Once the FC is in MSC mode and `STATUS_VERBOSE` reports `msc_raw=1`, download a raw range and trim leading padding before the Blackbox header:

```bash
PYTHONPATH=fcs-host python3 fcs-host/fcs_msc_raw_download.py tuna-bridge --size 1048576
```

For normal Tuna workflows, prefer the Tuning Agent-facing `tune` command because it validates mode state, can trigger MSC mode, downloads with resume, trims leading padding, and verifies the Blackbox header:

```bash
tune --db tune.sqlite3 log transfer \
  --bridge-host tuna-bridge-usb \
  --timeout 60 \
  --size 2097152 \
  --output transferred-logs/current-flight.bbl \
  --json
```

The lower-level `fcs_msc_raw_download.py` helper writes under `transferred-logs/` by default. It searches for `H Product:Blackbox` and writes a trimmed `.bbl` unless `--keep-leading-padding` is used. It also keeps a `.part` plus `.state.json` sidecar so `--resume` can continue an interrupted transfer.

Current validation on the ESP32-S3 Bridge:

```text
MSC_GET_RAW 1048576
DATA 1048576
raw_bytes=1048576
header_offset=562176
written=486400

MSC_GET_RAW 1048576 1048576
DATA 1048576

resume helper: 1048576 raw bytes -> 2097152 raw bytes
final trimmed output starts with H Product:Blackbox
```

The resulting file started with:

```text
H Product:Blackbox flight data recorder by Nicholas Sherlock
H Data version:2
```

## Current validation status

Validated:

- FCS host unit tests: `25/25 OK`
- Tuna unit tests: `27/27 OK`
- Bridge resolve/connect/disconnect
- single-client rejection behavior
- MSP v1/v2 frame handling
- FC identity discovery: Betaflight `4.5.2`, variant `BTFL`, MSP API `1.46`
- ESP32-S3 USB CDC Bridge path to Betaflight FC `2e3c:5740`
- ESP32-S3 USB MSC raw path to Betaflight FC `2e3c:5720`
- `STATUS_VERBOSE` full diagnostics without truncating MSC sector fields
- `MSC_GET_RAW [bytes]` and `MSC_GET_RAW [offset] [bytes]` raw range reads
- `tune log transfer` end-to-end validation while FC is already in MSC raw mode
- Blackbox dataflash summary:
  - `dataflash_available=1`
  - `dataflash_supported=1`
  - `dataflash_ready=1`
  - `sector_count=256`
  - `total_size=16777216`
  - `used_size=16777216`
- 1 KiB read starts with `H Product:Blackbox flight data recorder`
- MSP 64 KiB download succeeded as fallback
- MSC raw 1 MiB transfer succeeded in about 4.3 seconds and produced a valid trimmed `.bbl` prefix
- MSC raw resume helper validated from 1 MiB to 2 MiB raw bytes with a valid trimmed `.bbl` prefix
- full 16 MiB MSC raw transfer succeeded as `transferred-logs/full-current-flight.bbl`, trimmed the Blackbox header at raw offset `562176`, produced a `16215040` byte `.bbl`, and was manually validated in Blackbox Explorer
- production full-size MSC raw transfer with progress display, chunked range reads, resume sidecars, and per-chunk retry policy

Not yet validated:

- automatic retry/resume after an interrupted full download
- erasing transferred FC logs through FCS after successful validated host-side transfer/import

## Known limitations

- Betaflight Configurator warns MSP flash download is slow/error-prone; our path has the same class of limitation.
- Current D1 mini Bridge cannot use Betaflight USB mass-storage mode because it is not USB host-capable.
- LilyGO T-Display-S3-AMOLED-1.64 bring-up required separate FC power; SY6970 OTG configuration succeeded, but the tested USB-C VBUS measurement stayed around 0.6V unloaded.
- MSP dataflash transfer is slow; use MSC raw transfer where available.
- `MSC_SCAN` expects FAT files and is not suitable for the validated Betaflight MSC target, which exposes raw Blackbox storage.
- Raw MSC still starts by downloading from offset zero when no resume state exists. Future optimization can use metadata, scan results, or known storage/log bounds to avoid transferring unnecessary leading/trailing raw padding.

## Future nice-to-have transfer improvements

- Validate automatic retry/resume after an intentionally interrupted full-size transfer and document the exact recovery procedure.
- Avoid downloading unnecessary leading padding by scanning or caching the Blackbox header offset before full transfer.
- Avoid downloading unnecessary trailing raw storage when reliable FC-reported log bounds are available.
- Keep these as optimizations after the validated v1 path; v1 retains complete raw transfer plus host-side trimming because it is simple and faithful.
