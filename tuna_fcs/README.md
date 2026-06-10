# tuna-fcs

Standalone JSON CLI and Python package for flight-controller operations over the FC Bridge or direct USB on the Host Computer.

Examples:

```bash
tuna-fcs inspect --connection bridge --bridge-host tuna-bridge-usb --json
tuna-fcs inspect --connection usb --usb-device /dev/ttyACM0 --json
tuna-fcs blackbox transfer --connection usb --output transferred-logs/current-flight.bbl --json
tuna-fcs blackbox erase --connection bridge --confirm erase-transferred-blackbox-log --json
tuna-fcs cli write --connection usb --cli-file approved.cli --confirm write-fc-cli --json
```

Environment defaults:

- `FCS_CONNECTION`: `bridge` or `usb`
- `FCS_BRIDGE_HOST`: Bridge host name/IP
- `FCS_USB_DEVICE`: USB serial device; omit to auto-detect
