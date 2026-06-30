# Changelog

## Standby Mode — Feature Overview

This fork adds a comprehensive **standby mode** for supported radios (V16, TX16S, etc.).
Instead of fully powering off after inactivity, the radio enters a low-power standby
state and can automatically wake when a receiver powers on.

### How it works

1. After the inactivity timeout expires, the radio enters **standby** (not full shutdown).
2. In standby, the RF module is turned off to save power.
3. Every **10 seconds**, the radio briefly powers the RF module for **up to 2 seconds**
   to sniff for a receiver signal.
4. When a receiver is detected, the radio wakes up automatically.

### Feature details

#### 0c4765e — Initial standby implementation
- Basic standby mode with WFI sleep
- Power button press wakes the radio
- Display and backlight off during standby

#### 8063d41 — H7 RTC & board resume support
- `boardEnterStandby()` / `boardResumeFromStandby()` for STM32H7
- RTC EX HAL compilation support

#### 03ce45e — Replace STOP mode with WFI + NVIC_SystemReset
- Use WFI (sleep) instead of deeper STOP mode for faster wake
- `NVIC_SystemReset` on resume to restore clock configuration

#### fe33c3c — Stick / switch / IMU movement wake
- Radio can also wake when you touch a stick, flip a switch, or move the radio
  (IMU motion detected)

#### d92f073 — Reliable telemetry wake after WFI
- `telemetryWakeup()` is called explicitly after wake to process buffered frames

#### e4fcbe1 — Keep mixer running for receiver auto-wake
- Mixer stays active during standby so the RF protocol can re-sync
- Replaced `NVIC_SystemReset` with a proper resume path to avoid full reboot

#### 48c2246 — Intermittent sniff mode (power saving)
- RF module turned off between sniff cycles (every 10s)
- Drastically reduces standby power consumption

#### bf209d6 / a891c21 — Tuned sniff timing
- Sniff interval: **10 seconds** (was 2s) — better battery life
- Sniff window: **2 seconds** (was 50ms) — reliable detection of slow-start receivers

#### 2d33ee7 — Auto-detect receiver and switch model (this PR)
When a receiver is detected during standby sniff, the radio now:

1. **Probes model IDs** — If the current model's receiver number (modelId / RX
   num) doesn't match the powered-on receiver (e.g. ELRS with Model Match enabled),
   the radio tries all unique modelId values from the model list via CRSF
   `COMMAND_MODEL_SELECT_ID`. This allows it to connect to a receiver even when
   the wrong model was selected before standby.

2. **Auto-switches to the matching model** — When the correct receiver is
   identified, the radio loads the corresponding model's full configuration
   (mixes, rates, telemetry sensors, etc.).

3. **Full safety checks** — Before the new model activates, the radio runs the
   standard throttle warning, switch check, and failsafe check (`checkAll()`).
   The backlight is turned on so the user can see these warnings. This is the
   **same safety mechanism** used when manually switching models — it respects
   each model's individual settings (e.g. if throttle warning is disabled in
   the model, it won't show).

### Usage

- **Automatic**: Nothing to configure. The radio enters standby after the
  configured inactivity time, and wakes automatically when a receiver powers on.
- **Manual wake**: Press the power button, move a stick, flip a switch, or
  move the radio (IMU).

### Supported radios

- HelloRadio V16 (initial target)
- Any radio with `PWR_BUTTON_PRESS` support and CRSF module
