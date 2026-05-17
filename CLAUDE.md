# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build Commands

```bash
# All build commands from repo root. Ensure toolchain is installed:
#   - arm-none-eabi-gcc for firmware cross-compilation
#   - Qt + SDL for companion/simulator native builds

# Configure firmware build for a specific target
cmake --preset firmware -DPCB="<TARGET>" [-DPCBREV="<REV>"]
# e.g. -DPCB=X10 -DPCBREV=PN65 for Horus X10
# Build firmware
cmake --build --preset firmware

# Build simulator (SDL, native on host)
cmake --preset simu
cmake --build --preset simu

# Build companion desktop app (Qt)
cmake --preset companion
cmake --build --preset companion

# Build and run tests
cmake --preset simu
cmake --build --preset tests-radio
./build/simu/tests/gtests-radio

# Run a single test or test suite
./build/simu/tests/gtests-radio --gtest_filter="TrimsTest.*"
./build/simu/tests/gtests-radio --gtest_filter="MixerTest.testSrcMix"

# Companion tests
cmake --build build/simu --target tests-companion
./build/simu/companion/tests/gtests-companion

# Superbuild (firmware + native in one CMake pass)
cmake -B build -DCMAKE_BUILD_TYPE=Release .
cmake --build build --target arm-none-eabi-configure
cmake --build build/arm-none-eabi --target firmware-size

# Full CI build for a specific radio
./tools/build-gh.sh -b<target>  # e.g. ./tools/build-gh.sh -bx10

# Translations build (Chinese CN in this example)
TRANSLATIONS=cn cmake --preset firmware -DPCB=X10

# Code formatting
./tools/codeformat.sh            # runs uncrustify + copyright + include-guard
clang-format -i <file>           # also available
```

## Project Structure

### Top-Level

- **`radio/src/`** — Main firmware source for RC radio hardware (STM32 targets)
  - `boards/` — Board-specific hardware definitions and drivers (STM32 F2/F4/H7)
    - `generic_stm32/` — Common STM32 board support layer
    - `hw_defs/` — JSON hardware definition files per model (boxer.json, x10.json, etc.)
  - `targets/` — Target-specific implementations (horus/, taranis/, st16/, tx15/, etc.)
  - `hal/` — Hardware abstraction layer (ADC, audio, flash, GPIO, I2C, USB, storage, etc.)
  - `drivers/` — External chip drivers (AW9523B, LSM6DS, TAS2505, WM8904, etc.)
  - `gui/` — User interface
    - `128x64/` — B&W LCD UI (Taranis and similar)
    - `colorlcd/` — Color LCD UI (Horus, NV14, etc.) with LVGL themes/widgets/layouts
      - `radio/` — Radio settings screens
      - `model/` — Model configuration screens
      - `widgets/` — Widgets (gauges, timers, values, etc.)
      - `themes/` — Theme system
      - `controls/` — UI control widgets
    - `navigation/` — Navigation controller
    - `common/` — Shared GUI code (fonts, bitmaps, menus)
  - `io/` — Trainer (PPM, CRSF, SBUS), CPR, and other I/O protocols
  - `os/` — OS-level operations (sdcard, firmware options, translation strings)
  - `pulses/` — Module pulse generation (AFHDS, CRSF, DSM2, Flysky, Ghost, Multi, PPM, SBUS, etc.)
  - `tasks/` — Background and boot tasks
  - `telemetry/` — Telemetry protocol decoders (Flysky, FrSky, HoTT, JETI, MAVLink, MLINK, Multi, etc.)
  - `storage/` — YAML-based model and radio settings persistence
  - `lua/` — Embedded Lua scripting for UI and mixer extensions
  - `translations/` — Multi-language string tables (translations.cpp/h, per-language test_*.cpp)
  - `bootloader/` — STM32 DFU bootloader source
  - `tests/` — Unit tests (Google Test, native build)
- **`companion/`** — Desktop companion application (Qt C++)
  - `src/` — Model editing, firmware flashing, simulator, storage
  - `src/tests/` — Companion unit tests
- **`cmake/`** — CMake modules and toolchain files
  - `toolchain/` — Cross-compilation toolchains (arm-none-eabi, native, wasi)
- **`tools/`** — Build scripts (`build-gh.sh`, `build-common.sh`, `codeformat.sh`, `copyright.py`, etc.)
- **`web/`** — Web interface (Svelte + TypeScript + Vite)
- **`docs/`** — Documentation site (MkDocs)

### CMake Build System

Three build presets defined in `CMakePresets.json`:
| Preset | Binary Dir | Toolchain | Use |
|--------|-----------|-----------|-----|
| `firmware` | `build/fw` | arm-none-eabi | Cross-compiled STM32 firmware |
| `simu` | `build/simu` | native (host) | SDL simulator + tests |
| `companion` | `build/companion` | native (host) | Qt companion app |

The **superbuild** (top-level `CMakeLists.txt`) invokes two ExternalProject builds: `native` (simulator/companion on host) and `arm-none-eabi` (cross-compiled firmware for STM32). When using presets, `EdgeTX_SUPERBUILD=OFF` and you build only one configuration at a time.

## Supported Hardware (41 targets)

Defined in `fw.json`. Radio families:

- **FrSky**: X10, X10 Express, X12S, X7 Access, X9D+ 2019, X9E, X9E Hall
- **RadioMaster**: TX16S, TX16S MK3, TX12MK2, Boxer, Zorro, Pocket, MT12, GX12, TX15
- **Flysky**: NV14, PL18, PL18EV, PL18U, EL18, NB4+, PA01, ST16
- **Jumper**: T12 MAX, T14, T15, T15 Pro, T16, T18, T20, T20 V2, T-Pro S, T-Pro V2, Bumblebee
- **iFlight**: Commando 8
- **Other**: Fatfish F16, HelloRadioSky V14/V16, X9Lite, X9Lite S, T8, TLite

New targets are added via `boards/hw_defs/*.json` (hardware definition) and mapped to PCB/PCBREV in `tools/build-common.sh`.

## Key Architecture

- **Superbuild**: Top-level CMake dispatches to native (host) and arm-none-eabi (cross) builds
- **PCB/PCBREV**: Board selection via `-DPCB=<BOARD> -DPCBREV=<REV>`. Multiple targets share the same PCB with different PCBREV (e.g. PCB=X7 covers Boxer, Zorro, Pocket, MT12, TX12MK2, etc.)
- **Tests**: Native-build Google Test in `radio/src/tests/`. Tests extend `EdgeTxTest` fixture which calls `SYSTEM_RESET()`, `MODEL_RESET()`, `MIXER_RESET()`, `setModelDefaults()`, and `RADIO_RESET()` in SetUp()
- **Test macros** (in `gtests.h`): `CHECK_NO_MOVEMENT`, `CHECK_SLOW_MOVEMENT`, `CHECK_DELAY`, `EXPECT_ZSTREQ`, `EXPECT_STRNEQ`
- **Translations**: Multi-language support via `TRANSLATIONS` env var. Per-language test files follow `test_{lang_code}.cpp` pattern
- **Lua**: Embedded Lua scripting runtime for radio UI and mixer extensions
- **LVGL**: Color LCD GUI uses the LVGL graphics library
- **Storage**: YAML-based persistence for model and radio settings
- **CI**: GitHub Actions (`.github/workflows/` — `build_fw.yml`, `companion.yml`, `nightly.yml`, etc.)

## Coding Conventions

- **License**: GPLv2 (header required in every source file)
- **Code format**: Run `./tools/codeformat.sh` — this applies (in order):
  1. `dos2unix` (line endings)
  2. `uncrustify -c ./tools/uncrustify.cfg`
  3. `./tools/copyright.py` (license header check)
  4. `./tools/include-guard.py` (header guard consistency)
- Additionally, `.clang-format` is available at repo root
- C++ for main source, Python for build/utility scripts
- Hardware definitions in JSON (`boards/hw_defs/*.json`)
- Board-specific defines via cmake `-DPCB=<BOARD>` and `-DPCBREV=<REV>`
- Conventional commits format (enforced in CI)
