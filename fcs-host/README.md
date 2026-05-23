# FCS host Bridge tooling

Host-side **FCS** tooling for the Tuna **Bridge**. The current validated path is:

```text
Host Computer --Wi-Fi/TCP--> ESP8266 Bridge --UART/MSP--> Betaflight FC
```

This supports read-only **Blackbox Log** discovery and transfer from FC dataflash. The FC copy is not deleted.

## Files

- `fcs_bridge/bridge_transport.py` — host-side Bridge TCP transport that owns connect/disconnect lifecycle
- `fcs_bridge/msp.py` — MSP v1/v2 frame helpers and Betaflight dataflash parsers
- `fcs_bridge/msp_client.py` — reusable synchronous MSP client
- `fcs_bridge/fc_discovery.py` — FC identity and Blackbox storage discovery
- `fcs_bridge/blackbox_transfer.py` — read-only MSP dataflash byte-range transfer
- `fcs_connectivity_tracer.py` — CLI smoke tracer against a real Bridge
- `fc_passthrough_smoke.py` — MSP passthrough smoke test against a real FC
- `fcs_blackbox_storage_probe.py` — read-only Blackbox storage discovery
- `fcs_blackbox_read_probe.py` — small diagnostic byte-range read
- `fcs_blackbox_download.py` — full FC-reported used dataflash download to `.bbl`
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

This transfers FC-reported used dataflash bytes into a `.bbl` file on the **Host Computer**. The FC copy is not deleted.

```bash
PYTHONPATH=fcs-host python3 fcs-host/fcs_blackbox_download.py tuna-bridge
```

The completed file is written under `transferred-logs/` and should be openable in Blackbox Explorer.

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

## Current validation status

Validated:

- unit tests: `23/23 OK`
- Bridge resolve/connect/disconnect
- single-client rejection behavior
- MSP v1/v2 frame handling
- FC identity discovery: Betaflight `4.5.2`, variant `BTFL`, MSP API `1.46`
- Blackbox dataflash summary:
  - `dataflash_available=1`
  - `dataflash_supported=1`
  - `dataflash_ready=1`
  - `sector_count=256`
  - `total_size=16777216`
  - `used_size=16777216`
- 1 KiB read starts with `H Product:Blackbox flight data recorder`
- 64 KiB download at about `6.4 KB/s`

Not yet validated:

- full 16 MiB `.bbl` download opened in Blackbox Explorer
- automatic retry/resume after an interrupted full download
- deletion of FC logs; v1 intentionally does not delete through FCS

## Known limitations

- Betaflight Configurator warns MSP flash download is slow/error-prone; our path has the same class of limitation.
- Current D1 mini Bridge cannot use Betaflight USB mass-storage mode because it is not USB host-capable.
- At current measured speed, a 16 MiB transfer takes roughly 40-45 minutes.
- Chunk sizes above `512` bytes have been unstable on current hardware/firmware.
