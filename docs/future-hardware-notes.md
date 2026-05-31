# Future hardware notes

## Try USB OTG/host Bridge hardware for Blackbox Log transfer

The current D1 mini / ESP8266 **Bridge** cannot read Betaflight mass storage mode because it is not USB host-capable. It only provides USB-serial for programming/power.

Future **Bridge** hardware should evaluate USB OTG/host support so the **Bridge** can connect to the FC USB port, trigger or observe Betaflight mass storage mode, copy completed **Blackbox Logs**, and expose them to the **Host Computer** over Wi-Fi.

Candidate directions:

- ESP32-S2/S3 USB OTG/host Bridge design.
- Raspberry Pi Zero / small SBC Bridge design.
- Compare reliability and transfer speed against MSP dataflash transfer and serial Blackbox logging.

Keep this as future work; current v1 remains **Post-flight Transfer** over the existing UART Bridge/FCS path unless hardware changes.

## Investigate returning FC from MSC mode to USB CDC mode

When Betaflight is put into mass-storage mode, the FC re-enumerates as USB MSC and the normal USB CDC/MSP/CLI command channel disappears. Investigate whether Tuna can return the FC to normal USB CDC mode without a manual power cycle/reset.

Candidate directions:

- Check whether Betaflight or common bootloaders expose a safe MSC eject/reset mechanism.
- Test whether USB detach/reattach from the ESP32-S3 host side causes the FC to reboot into normal mode.
- Evaluate whether target FCs expose a reset line/pad that future **Bridge** hardware can control.
- Document whether manual FC reset/power-cycle is required after MSC **Post-flight Transfer** in v1.

Until this is understood, assume that entering MSC mode is one-way from the FCS perspective and requires a physical reset/power-cycle to regain USB CDC/MSP access.

## Current state as of this repo snapshot

- ESP8266 UART Bridge works for MSP passthrough and read-only Blackbox dataflash transfer.
- Current measured MSP transfer speed is about `6.4 KB/s` with MSP v2 and 512 byte chunks.
- The FC currently reports 16 MiB dataflash and it is full.
- D1 mini internal flash is too small to store a full FC Blackbox dataflash image.
- Betaflight mass-storage transfer remains the preferred future direction for speed/reliability, but requires USB host-capable Bridge hardware.
