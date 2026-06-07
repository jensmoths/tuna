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

- `fcs.py` / `fcs_cli.py` — first-class JSON CLI for FC/Bridge hardware operations
- `fcs_bridge/bridge_transport.py` — host-side Bridge TCP transport that owns connect/disconnect lifecycle
- `fcs_bridge/msp.py` — MSP v1/v2 frame helpers and Betaflight dataflash parsers
- `fcs_bridge/msp_client.py` — reusable synchronous MSP client
- `fcs_bridge/fc_discovery.py` — FC identity and Blackbox storage discovery
- `fcs_bridge/blackbox_transfer.py` — MSP erase helper for post-import FC Blackbox storage cleanup
- `fcs_bridge/blackbox_download.py` — MSC file/raw Blackbox Log transfer helpers
- `fcs_connectivity_tracer.py` — CLI smoke tracer against a real Bridge
- `fc_passthrough_smoke.py` — MSP passthrough smoke test against a real FC
- `fcs_blackbox_storage_probe.py` — read-only Blackbox storage discovery
- `fcs_blackbox_erase.py` — erase transferred FC Blackbox Log storage after validated host-side transfer/import
- `fcs_write_cli.py` — apply Betaflight CLI text through FCS after Operator-approved **Tune Update** write-back
- `fcs_msc_raw_download.py` — raw Betaflight USB MSC transfer helper; trims leading padding before the Blackbox header
- `tests/test_bridge_transport.py` — stdlib `unittest` contract tests using a local single-client fake Bridge


## Common environment variables

Set `FCS_BRIDGE_HOST` to avoid repeating `--bridge-host` on normal FCS commands:

```bash
export FCS_BRIDGE_HOST=tuna-bridge-usb
PYTHONPATH=fcs-host python3 fcs-host/fcs.py inspect --json
PYTHONPATH=fcs-host python3 fcs-host/fcs.py blackbox transfer --output transferred-logs/current-flight.bbl --json
```

Explicit `--bridge-host` arguments override `FCS_BRIDGE_HOST`.

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
PYTHONPATH=fcs-host python3 fcs-host/fcs.py inspect --bridge-host tuna-bridge --json
```

## Erase transferred FC Blackbox Log storage

Only erase after Tuna has a validated retained **Blackbox Log** on the **Host Computer** and **Import** succeeded. The FC must be in USB CDC/MSP mode, so after MSC raw transfer the **Operator** must power-cycle/reset the FC before this command can run.

```bash
PYTHONPATH=fcs-host python3 fcs-host/fcs.py blackbox erase \
  --bridge-host tuna-bridge-usb \
  --confirm erase-transferred-blackbox-log \
  --json
```

The confirmation string is intentionally explicit because this erases FC Blackbox storage.

## Apply approved Betaflight CLI text

Only use this after the Operator Console has approved a **Tune Update** and the **Tuning Agent** has verified state and FC identity. The helper sends Betaflight CLI text through FCS and appends `save` when needed.

```bash
PYTHONPATH=fcs-host python3 fcs-host/fcs.py cli write \
  --bridge-host tuna-bridge-usb \
  --command "set d_pitch = 48" \
  --confirm write-fc-cli \
  --json
```

For generated CLI artifacts:

```bash
PYTHONPATH=fcs-host python3 fcs-host/fcs.py cli write \
  --bridge-host tuna-bridge-usb \
  --cli-file approved-tune-update.cli \
  --confirm write-fc-cli \
  --json
```

After success, the **Tuning Agent** records `python3 -m tune update apply --update-id ... --json`; after failure it records `python3 -m tune update record-write-failure --update-id ... --failure ... --json`.

## Download from Betaflight USB MSC raw storage

This is the preferred fast path for the ESP32-S3 USB-host Bridge. The FC is first put into Betaflight mass-storage mode, usually via CLI `msc`. When the Bridge can mount the Betaflight MSC filesystem, Tuna prefers the actual `.bbl` file exposed by Betaflight (typically one combined Blackbox Log artifact such as `btfl_all.bbl`). Raw sector transfer with `MSC_GET_RAW [bytes]` or `MSC_GET_RAW [offset] [bytes]` remains the fallback/debug path.

Once the FC is in MSC mode and `STATUS_VERBOSE` reports `msc_raw=1`, download a raw range and trim leading padding before the Blackbox header:

```bash
PYTHONPATH=fcs-host python3 fcs-host/fcs_msc_raw_download.py tuna-bridge --size 1048576
```

For normal Tuna workflows, use the FCS JSON CLI for Post-flight Transfer; it validates mode state, can trigger MSC mode, prefers a mounted MSC `.bbl` file when available, falls back to raw download with resume, trims leading padding, and verifies the Blackbox header:

```bash
PYTHONPATH=fcs-host python3 fcs-host/fcs.py blackbox transfer \
  --bridge-host tuna-bridge-usb \
  --timeout 60 \
  --output transferred-logs/current-flight.bbl \
  --json
```

When starting from USB CDC/MSP mode, omit `--size`; the command probes FC Blackbox storage through FCS/MSP and uses the reported `used_size` before triggering MSC mode. Keep `--size` as an override/debug option when the Bridge is already in MSC raw mode and MSP storage discovery is unavailable.

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

Additional Tuna-facing validation on 2026-06-06 with `tuna-bridge-usb`:

```text
FC CDC/MSP identity before transfer:
  variant=BTFL
  version=25.12.3
  msp_api=1.47

Blackbox storage before transfer:
  dataflash_available=1
  dataflash_supported=1
  dataflash_ready=1
  sector_count=256
  total_size=16777216
  used_size=868352

PYTHONPATH=fcs-host python3 fcs-host/fcs.py blackbox transfer --no-trigger-msc --size 868352 --chunk-size 262144:
  raw_bytes_downloaded=868352
  retries=1
  header_offset=562176
  written_bytes=306176
  starts_with_blackbox_header=true

python3 -m tune log import:
  log_id=2
  parse_status=readable
  firmware=Betaflight 2025.12.3-alpha (db7df6e48) AT32F435G

python3 -m tune analysis decode-analyze:
  csv_path=tune-data/decoded-logs/log-2.csv
  analysis_id=3
  row_count=184
  duration_seconds=0.090817
  usable=false; warning=Blackbox Log duration is short for tuning analysis
```

During that run, an initial `PYTHONPATH=fcs-host python3 fcs-host/fcs.py blackbox transfer` from USB CDC/MSP mode successfully caused the FC to re-enumerate into MSC raw mode, but the command timed out while polling status. Re-running `PYTHONPATH=fcs-host python3 fcs-host/fcs.py blackbox transfer --no-trigger-msc` completed the **Post-flight Transfer** from the already-ready MSC raw state. After transfer, the FC remained in MSC mode and required Operator reset/power-cycle before further USB CDC/MSP operations.

Follow-up hardware validation on 2026-06-06 cleared the remaining v1 FCS gates:

```text
FCS write-back smoke:
  command: fcs.py cli write --command "set d_pitch = 46" --confirm write-fc-cli --json
  result: write ok
  transcript: FC entered CLI, accepted d_pitch set to 46, accepted save
  post-write MSP smoke: variant=BTFL version=25.12.3 msp_api=1.47

One-shot CDC/MSP -> MSC raw Post-flight Transfer:
  initial_status: USB_CDC_CONNECTED, msc_raw=0
  trigger_transcript: entered CLI, sent msc, FC restarted in mass storage mode
  msc_status: USB_CDC_DISCONNECTED, msc_raw=1
  raw_bytes_downloaded=868352
  retries=0
  header_offset=562176
  written_bytes=306176
  starts_with_blackbox_header=true

Erase after validated transfer/import:
  pre-erase storage: total_size=16777216 used_size=868352
  command: fcs.py blackbox erase --confirm erase-transferred-blackbox-log --json
  result: erase ok before_used_bytes=868352 after_used_bytes=0
  follow-up storage probe: total_size=16777216 used_size=0
```

## Current validation status

Validated:

- FCS host unit tests: `23/23 OK`
- Tuna unit tests: `89/89 OK` with `pytest -q`
- Bridge resolve/connect/disconnect
- single-client rejection behavior
- MSP v1/v2 frame handling
- FC identity discovery: Betaflight `4.5.2`, variant `BTFL`, MSP API `1.46`
- FC identity discovery: Betaflight `25.12.3`, variant `BTFL`, MSP API `1.47`
- ESP32-S3 USB CDC Bridge path to Betaflight FC `2e3c:5740`
- ESP32-S3 USB MSC raw path to Betaflight FC `2e3c:5720`
- `STATUS_VERBOSE` full diagnostics without truncating MSC sector fields
- `MSC_GET_RAW [bytes]` and `MSC_GET_RAW [offset] [bytes]` raw range reads
- `fcs blackbox transfer` end-to-end validation while FC is already in MSC raw mode
- `fcs blackbox transfer` of a real FC **Blackbox Log** from MSC raw mode, followed by Tuna **Import**, decode, and analysis
- `fcs blackbox transfer` one-shot from USB CDC/MSP mode through automatic `msc` trigger into MSC raw transfer
- Blackbox dataflash summary:
  - `dataflash_available=1`
  - `dataflash_supported=1`
  - `dataflash_ready=1`
  - `sector_count=256`
  - `total_size=16777216`
  - `used_size=16777216`
- MSC raw 1 MiB transfer succeeded in about 4.3 seconds and produced a valid trimmed `.bbl` prefix
- MSC raw resume helper validated from 1 MiB to 2 MiB raw bytes with a valid trimmed `.bbl` prefix
- full 16 MiB MSC raw transfer succeeded as `transferred-logs/full-current-flight.bbl`, trimmed the Blackbox header at raw offset `562176`, produced a `16215040` byte `.bbl`, and was manually validated in Blackbox Explorer
- production full-size MSC raw transfer with progress display, chunked range reads, resume sidecars, and per-chunk retry policy
- partial real-log MSC raw transfer with one retry, `306176` byte trimmed `.bbl`, `log_id=2`, `analysis_id=3`
- real FC write-back using `fcs cli write` with a no-op approved-value CLI command, followed by successful MSP smoke test
- erasing transferred FC logs through FCS after successful validated host-side transfer/import, followed by storage probe showing `used_size=0`

Not yet validated:

- automatic retry/resume after an interrupted full download

## Known limitations

- MSP dataflash transfer is intentionally not supported as a Tuna **Post-flight Transfer** fallback because it is too slow for the normal workflow.
- Current D1 mini Bridge cannot use Betaflight USB mass-storage mode because it is not USB host-capable.
- LilyGO T-Display-S3-AMOLED-1.64 bring-up required separate FC power; SY6970 OTG configuration succeeded, but the tested USB-C VBUS measurement stayed around 0.6V unloaded.
- Raw MSC fallback still starts by downloading from offset zero when no resume state exists. Future optimization can use metadata, scan results, or known storage/log bounds to avoid transferring unnecessary leading/trailing raw padding.

## Future nice-to-have transfer improvements

- Validate automatic retry/resume after an intentionally interrupted full-size transfer and document the exact recovery procedure.
- Avoid downloading unnecessary leading padding by scanning or caching the Blackbox header offset before full transfer.
- Avoid downloading unnecessary trailing raw storage when reliable FC-reported log bounds are available.
- Keep these as optimizations after the validated v1 path; v1 retains complete raw transfer plus host-side trimming because it is simple and faithful.
