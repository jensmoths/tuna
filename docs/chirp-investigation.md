# Chirp investigation

## Summary

Betaflight `master` currently contains a gated `USE_CHIRP` implementation. It adds a `CHIRP` aux mode and a `DEBUG_CHIRP` Blackbox debug mode. This can fit Tuna well as a diagnostic **Blackbox Log** capture mode for frequency-response estimation, but it should be introduced as an Operator-approved diagnostic workflow rather than as an automatic tuning action.

## What Betaflight provides

Sources checked in `../betaflight`:

- `src/main/common/chirp.c`: logarithmic chirp generator from `f0` to `f1` over `t1`; output is cosine phase, attenuated below 1 Hz.
- `src/main/flight/pid.c`: when `CHIRP_MODE` is active, Betaflight injects the shaped chirp into `currentPidSetpoint` for the currently selected axis.
- `src/main/flight/pid_init.c`: chirp runtime setup uses `chirp_lag_freq_hz`, `chirp_lead_freq_hz`, amplitudes, start/end frequency, and duration from the PID profile.
- `src/main/build/debug.c` / `debug.h`: debug mode name `CHIRP` / enum `DEBUG_CHIRP`.
- `src/main/flight/pid.c`: `DEBUG_CHIRP` fields are:
  - `debug[0]`: phase `sinarg`, scaled by `5000`.
  - `debug[1]`: active chirp axis, `0=roll`, `1=pitch`, `2=yaw`, `-1=inactive`.
  - `debug[2]`: instantaneous chirp frequency in deci-Hz.
  - `debug[3]`: raw chirp excitation scaled by `1000`.
- `src/main/cli/settings.c` and `src/main/fc/parameter_names.h`: CLI settings exist only under `USE_CHIRP`:
  - `chirp_lag_freq_hz`
  - `chirp_lead_freq_hz`
  - `chirp_amplitude_roll`
  - `chirp_amplitude_pitch`
  - `chirp_amplitude_yaw`
  - `chirp_frequency_start_deci_hz`
  - `chirp_frequency_end_deci_hz`
  - `chirp_time_seconds`
- `src/main/blackbox/blackbox.c`: chirp parameters are emitted in Blackbox headers under `USE_CHIRP`.
- `src/main/msp/msp_box.c`: `BOXCHIRP` aux mode is exposed only under `USE_CHIRP`.
- `src/main/fc/core.c`: `BOXCHIRP` toggles `CHIRP_MODE`, suppressed during failsafe/GPS rescue.

Default values in `src/main/flight/pid.c` are lag `3 Hz`, lead `30 Hz`, roll/pitch amplitude `230 deg/s`, yaw amplitude `180 deg/s`, start `0.2 Hz`, end `600 Hz`, duration `20 s`.

## What bf_controller_tuning does

Sources checked in `../bf_controller_tuning`:

- `README.md` describes the intended workflow: build/flash Betaflight with chirp support, assign `CHIRP` mode to a switch, set `debug_mode = CHIRP`, enable high-resolution Blackbox logging, fly full chirps for roll/pitch/yaw, convert `.bbl` to `.csv`, then run MATLAB analysis.
- `bf_controller_tuning.m` parses Blackbox CSV headers, unscales high-resolution gyro/setpoint fields, unscales `debug[0]` by `5000`, detects chirp-active evaluation windows, and estimates frequency responses.
- `lib/estimate_frequency_response.m` estimates FRF as `S_yu / S_uu` with coherence.
- `lib/get_ind_eval.m` detects chirp windows using `sinarg > 0` plus a variance threshold.
- The script derives:
  - closed-loop tracking `T`: chirp/setpoint to gyro,
  - controller effort `Guw`: chirp/setpoint to axis sum,
  - plant estimate `P = T / Guw`,
  - analytical controller/filter responses for comparing proposed PID/filter settings.

## How Tuna could use this

Recommended integration path:

1. Add a diagnostic setup step in FCS/Tuning Agent workflow:
   - verify firmware has chirp support, preferably from Betaflight build info or by checking that CLI accepts chirp parameters / `debug_mode = CHIRP`;
   - set Blackbox high resolution on;
   - set `debug_mode = CHIRP`;
   - set conservative chirp parameters;
   - ask the **Operator** to assign `CHIRP` aux mode if needed.
2. Add an **Operator Task** for the flight procedure:
   - Pilot flies in open space;
   - activates `CHIRP` switch for full duration per axis;
   - toggles off/on to cycle roll, pitch, yaw;
   - ideally captures each axis twice;
   - avoid motor saturation.
3. Import and analyze the resulting **Blackbox Log**:
   - extend metadata/header extraction to record `debug_mode`, `blackbox_high_resolution`, chirp parameters, and decoded fields;
   - detect chirp logs by `debug[0..3]` plus `debug_mode=CHIRP`/chirp header fields where available;
   - add a chirp analysis module that uses `debug[1]` axis and/or `debug[0]` phase to segment roll/pitch/yaw chirps;
   - estimate FRFs and coherence from setpoint/gyro/axisSum/PID terms;
   - report machine-readable plant/controller/closed-loop metrics and confidence.
4. Use chirp-derived data as evidence for a **Diagnosis** and future Tune Update proposals. Keep final changes absolute and Operator-reviewed.

## Risks and constraints

- Requires Betaflight firmware compiled with `USE_CHIRP`; many normal releases/targets may not have it enabled.
- It is an active excitation injected into setpoint, so it is a flight-safety concern. It must be Operator/Pilot controlled and not automatically triggered by Tuna.
- `debug_mode = CHIRP` consumes the debug fields, so it replaces RPM/filter debug capture for that log.
- `bf_controller_tuning` assumes Feedforward disabled, Dmax/dynamic damping disabled, high-resolution Blackbox on, RPM/dynamic notch already sane, and no motor saturation.
- Current Tuna analysis is CSV-summary based and lacks frequency-response/coherence estimation and Blackbox header setting extraction from decoded CSV. Those are the main implementation gaps.
- I did not find a local Betaflight Configurator checkout one directory above; only `../betaflight` and `../bf_controller_tuning` were present.

## Near-term implementation slice

A small first slice should not attempt automatic tuning. It should add:

- header/settings extraction from decoded Blackbox CSV;
- chirp capability/quality detection in analysis JSON;
- chirp segment summaries by axis using `debug[1]`, with fallback to `debug[0]` phase;
- validation warnings for missing `debug[*]`, not `debug_mode=CHIRP`, insufficient duration, low coherence, or motor saturation.

Only after that should Tuna add FRF/coherence estimation and model-based tune proposal support.

## Betaflight Configurator findings

After adding `../betaflight-configurator`, I found first-class chirp/autotune support there too:

- `src/components/sidebar/sidebar_items.js` exposes an expert `autotune` tab.
- `src/components/tabs/AutotuneTab.vue` wires together import, Bode plot, spectrogram, and gain recommendation UI.
- `src/composables/useAutotune.js` imports a `.bbl`/`.txt` Blackbox Log in-browser, finds log boundaries, parses chirp data, computes per-axis transfer functions, computes sensitivity/step/spectrogram metrics, and can apply proposed simplified tuning sliders through MSP.
- `src/js/blackbox/chirp_bbl_parser.js` is the most useful reference for Tuna because it parses binary `.bbl` directly for chirp fields instead of requiring `blackbox_decode` CSV first.
- `src/js/blackbox/spectral_analysis.js` contains a compact JavaScript implementation of the core algorithms:
  - Hanning window generation;
  - Welch transfer function `H(f)=Sxy/Sxx` from setpoint to gyro;
  - coherence;
  - bandwidth, resonant peak, phase margin, low-frequency error, noise floor;
  - simplified slider recommendations;
  - sensitivity `S = 1 - T`;
  - IFFT-derived step response;
  - spectrogram.
- `src/stores/debug.js` and `test/js/utils/debugModes.test.js` confirm Configurator treats `CHIRP` as API `1.47+`, with `CHIRP` debug mode index `97` for API `1.47` and `1.48`.

Important parser details from Configurator:

- It validates `debug_mode` by comparing the log's numeric `debug_mode` against `getDebugModeIndex("CHIRP", firmwareApiVersion)`.
- It requires `setpoint[0..2]`, `gyroADC[0..2]`, and `debug[0..3]` fields.
- It uses S-frame `flightModeFlags` and `BOXCHIRP_BIT = 6` to collect samples only while chirp mode is active.
- It uses `debug[1]` to split segments by chirp axis.
- It handles `blackbox_high_resolution` by scaling gyro/setpoint values by `0.1`.
- It computes sample rate as `1e6 / (looptime * pid_process_denom * frameIntervalPDenom)`.

Implications for Tuna:

- Prefer borrowing the Configurator algorithm design, not the UI workflow. Tuna should still preserve the **Tuning Agent** / **Operator** split and must not apply changes from an Operator Console automatically.
- A Python port of Configurator's chirp parser/analyzer is a better near-term target than depending only on CSV conversion, because it can extract only the required chirp data from `.bbl` and preserve robust log-boundary handling.
- Configurator's direct “Apply Gains” behavior should not be copied. In Tuna, any proposed slider/PID/filter changes must become a **Tune Update**, require **Operator** review, and then be written by the **Tuning Agent** through **FCS**.
- Configurator currently recommends simplified sliders. Tuna's domain rule says **Tune Updates** are absolute target values. If Tuna uses slider recommendations, it should either store absolute slider setting targets or translate/record the resulting absolute PID/filter settings after validation.
