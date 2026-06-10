# tuna-blackbox

Standalone JSON CLI and Python package for Blackbox Log metadata, decoding, and analysis. It does not require the Tuna web app, Tuning Agent Loop, or SQLite database.

Examples:

```bash
tuna-blackbox metadata flight.bbl --json
tuna-blackbox metadata flight.bbl --full --metadata-json-file metadata.json --json
tuna-blackbox decode flight.bbl --output flight.csv --json
tuna-blackbox analyze flight.csv --output-json-file analysis.json --json
tuna-blackbox decode-analyze flight.bbl --output flight.csv --output-json-file analysis.json --json
tuna-blackbox segment-rows flight.csv --start-row 1000 --end-row 1200 --fields 'time,gyroADC[0],setpoint[0]' --json
```

Environment defaults:

- `TUNA_BLACKBOX_DECODER`: decoder command for `decode` and `decode-analyze` (`blackbox_decode` by default)
