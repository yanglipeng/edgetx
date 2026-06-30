/*
 * Copyright (C) EdgeTX
 *
 * Based on code named
 *   opentx - https://github.com/opentx/opentx
 *   th9x - http://code.google.com/p/th9x
 *   er9x - http://code.google.com/p/er9x
 *   gruvin9x - http://code.google.com/p/gruvin9x
 *
 * License GPLv2: http://www.gnu.org/licenses/gpl-2.0.html
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License version 2 as
 * published by the Free Software Foundation.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 */

#include "debug.h"
#include "edgetx.h"
#include "os/sleep.h"
#include "os/task.h"
#include "os/time.h"
#include "os/timer.h"
#include "timers_driver.h"
#include "hal/abnormal_reboot.h"
#include "hal/watchdog_driver.h"
#include "inactivity_timer.h"
#include "pdm_wav_recorder.h"

#include "tasks.h"
#include "tasks/mixer_task.h"
#include "storage/modelslist.h"

#if defined(CROSSFIRE)
#include "telemetry/crossfire.h"
#endif

#if defined(COLORLCD)
#include "startup_shutdown.h"
#endif

task_handle_t menusTaskId;
TASK_DEFINE_STACK(menusStack, MENUS_STACK_SIZE);

#if defined(AUDIO)
task_handle_t audioTaskId;
TASK_DEFINE_STACK(audioStack, AUDIO_STACK_SIZE);
#endif

mutex_handle_t audioMutex;

#define MENU_TASK_PERIOD (50)  // 50ms

#if defined(COLORLCD) && defined(CLI)
bool perMainEnabled = true;
#endif

// ------------------------------------------------------------------
// Probe model IDs from the model list for CRSF/ELRS modules.
// Returns true if a matching model was found and loaded.
// On non-CRSF / non-modelslist targets this is a no-op stub.
// ------------------------------------------------------------------
#if defined(CROSSFIRE) && defined(STORAGE_MODELSLIST)
static bool tryProbeModelIds()
{
  for (uint8_t module = 0; module < NUM_MODULES; module++) {
    if (!isModuleCrossfire(module)) continue;

    uint8_t origId = g_model.header.modelId[module];
    bool probed[MAX_RXNUM + 1] = {false};
    probed[origId] = true;  // Already tried by the normal connection

    uint8_t foundId = 0;
    bool found = false;

    // Collect unique modelIds from modelslist
    for (auto& cell : modelslist) {
      if (cell->moduleData[module].type !=
          g_model.moduleData[module].type)
        continue;

      uint8_t mid = cell->modelId[module];
      if (mid > MAX_RXNUM || probed[mid]) continue;

      probed[mid] = true;

      // Trigger module resend first, then set modelId, so the
      // pulse task never sees the new modelId with the old counter.
      moduleState[module].counter = CRSF_FRAME_MODELID;
      g_model.header.modelId[module] = mid;

      // Wait for module to process the new ID and receiver to respond
      for (int i = 0; i < 6; i++) {
        telemetryWakeup();
        if (TELEMETRY_STREAMING()) {
          foundId = mid;
          found = true;
          break;
        }
        sleep_ms(50);
      }

      if (found) break;

      // Restore original for next probe
      moduleState[module].counter = CRSF_FRAME_MODELID;
      g_model.header.modelId[module] = origId;
      sleep_ms(80);  // Let restore take effect
    }

    if (!found) {
      g_model.header.modelId[module] = origId;
      continue;
    }

    // Find the full model in modelslist by modelId
    for (auto& cell : modelslist) {
      if (cell->moduleData[module].type !=
          g_model.moduleData[module].type)
        continue;
      if (cell->modelId[module] != foundId) continue;

      // Skip if it's already the current model
      if (cell == modelslist.getCurrentModel()) {
        // Current model's module config works
        moduleState[module].counter = CRSF_FRAME_MODELID;
        g_model.header.modelId[module] = origId;
        return true;
      }

      // Switch to the matching model.
      // loadModel() internally stops pulses (preModelLoad) and
      // restarts them (postModelLoad -> pulsesStart) so the mixer
      // is running after this call.
      storageFlushCurrentModel();
      storageCheck(true);
      strncpy(g_eeGeneral.currModelFilename, cell->modelFilename,
              LEN_MODEL_FILENAME);
      g_eeGeneral.currModelFilename[LEN_MODEL_FILENAME] = '\0';
      modelslist.setCurrentModel(cell);

      // SAFETY: turn on the backlight and use alarms=true so that
      // checkAll() runs throttle / switch / failsafe warnings.
      requiredBacklightBright = g_eeGeneral.getBrightness();
      currentBacklightBright = requiredBacklightBright;
      BACKLIGHT_ENABLE();

      const char* err = loadModel(g_eeGeneral.currModelFilename, true);
      if (err) {
        TRACE("tryProbeModelIds: loadModel error=%s", err);
      }

      storageDirty(EE_GENERAL);
      return true;
    }

    // Found a modelId but no matching model in list -> restore
    moduleState[module].counter = CRSF_FRAME_MODELID;
    g_model.header.modelId[module] = origId;
    return true;  // telemetry is still streaming
  }

  return false;
}
#else
static bool tryProbeModelIds()
{
  return false;
}
#endif

// Periodically probe model IDs during normal (non-standby) operation.
// Called from the main loop every ~50ms; rate-limited internally to
// one probe attempt every 30 seconds.
//
// Conditions:
//   - No telemetry streaming (no receiver connected)
//   - At least 30s since the last probe
//   - Not in the first 5s after boot
static void tryAutoSwitchModel()
{
#if defined(CROSSFIRE) && defined(STORAGE_MODELSLIST)
  // Don't probe while a receiver is connected
  if (TELEMETRY_STREAMING()) return;

  tmr10ms_t now = get_tmr10ms();

  // Wait for things to settle after boot (5 seconds)
  if (now < 500) return;

  // Rate-limit: probe at most once every 10 seconds.
  // During a probe we briefly change modelId (300ms per model); the
  // user does not notice this when no receiver is connected.
  static tmr10ms_t lastProbe = 0;
  if ((now - lastProbe) < 1000) return;  // 1000 * 10ms = 10s
  lastProbe = now;

  tryProbeModelIds();
#endif
}

static void menusTask()
{
  edgeTxInit();

  mixerTaskInit();

#if defined(COLORLCD) && defined(RTC_BACKUP_RAM)
  if (UNEXPECTED_SHUTDOWN())
    drawFatalErrorScreen(STR_EMERGENCY_MODE);
#endif

#if defined(PWR_BUTTON_PRESS)
  // Standby state — persists across loop iterations
  static bool standby_prepared = false;
  static tmr10ms_t standby_start_time = 0;
  static tmr10ms_t last_standby_poll = 0;

  while (task_running()) {
    uint32_t pwr_check = pwrCheck();
    if (pwr_check == e_power_off) {
      break;
    } else if (pwr_check == e_power_press) {
      if (standby_prepared) {
        // Power button pressed during standby — wake up, don't reset
        standby_prepared = false;
        mixerTaskStart();  // Resume mixer
        inactivityTimerReset(ActivitySource::Keys);
        continue;
      }
      sleep_ms(MENU_TASK_PERIOD);
      continue;
    } else if (pwr_check == e_power_standby) {
      if (!standby_prepared) {
        // First entry: flush storage
        storageCheck(false);
        // Stop mixer to save RF module power.
        // Every 10s we restart it to sniff for receiver.
        mixerTaskStop();
        standby_prepared = true;
        standby_start_time = get_tmr10ms();
        last_standby_poll = 0;
      }

      boardEnterStandby();
      boardResumeFromStandby();
      WDG_RESET();  // Feed watchdog (mixer stopped, cannot feed itself)

      // Every 10 seconds: restart mixer and sniff for receiver.
      // Keep the mixer running for up to 2 seconds so the RF protocol
      // has time to re-establish the link (frequency-hopping sync,
      // receiver boot, protocol handshake, etc.).
      // Check telemetry every 50ms and break out as soon as we detect it.
      tmr10ms_t now = get_tmr10ms();
      if ((now - last_standby_poll) > 1000) {  // 1000 * 10ms = 10s
        last_standby_poll = now;
        mixerTaskStart();

        // Sniff loop: up to 40 × 50ms = 2000ms
        for (int i = 0; i < 40; i++) {
          telemetryWakeup();
          if (TELEMETRY_STREAMING()) break;
          sleep_ms(50);
        }

        if (!TELEMETRY_STREAMING()) {
          // Phase 2: Probe model IDs from other models in the list.
          // Needed for CRSF/ELRS with Model Match: if current modelId
          // doesn't match the receiver, telemetry stays silent even
          // though a receiver is present.  We try each unique modelId
          // from modelslist to find one that connects.
          if (tryProbeModelIds()) {
            // A matching model was loaded and mixer restarted.
            // Fall through to wake-up below.
          } else {
            mixerTaskStop();
          }
        }
      }

      // 1. Receiver connected → telemetry detected → wake up
      if (TELEMETRY_STREAMING()) {
        mixerTaskStart();   // Keep mixer running for normal operation
        standby_prepared = false;
        inactivityTimerReset(ActivitySource::Keys);
        continue;
      }

      // 2. Stick / switch / IMU movement → wake up
      //    ADC(DMA) keeps sampling, IMU is polled by mixer task even
      //    when _mixer_running=false, switch GPIO works independently.
      if (inactivityCheckInputs()) {
        mixerTaskStart();
        standby_prepared = false;
        inactivityTimerReset(ActivitySource::Keys);
        continue;
      }

      // Safety shutdown after ~2 hours of standby
      if ((get_tmr10ms() - standby_start_time) > 60u * 100u * 120u) {
        standby_prepared = false;
        break;
      }

      continue;
    }
    // e_power_on: idle cycle — loop back to pwrCheck()
#else
  while (pwrCheck() != e_power_off) {
#endif
    time_point_t next_tick = time_point_now();

    // Auto-switch model when a receiver powers on during normal
    // (non-standby) operation.  Only fires when no receiver is
    // connected; rate-limited to once every 30 seconds.
    tryAutoSwitchModel();

    DEBUG_TIMER_START(debugTimerPerMain);
#if defined(COLORLCD) && defined(CLI)
    if (perMainEnabled) {
      perMain();
    }
#else
    perMain();
#endif
    DEBUG_TIMER_STOP(debugTimerPerMain);

    sleep_until(&next_tick, MENU_TASK_PERIOD);
    resetForcePowerOffRequest();
  }

#if defined(PCBX9E)
  toplcdOff();
#endif

  drawSleepBitmap();
  edgeTxClose();
  boardOff();
}

static void audioTask()
{
  while (!audioQueue.started()) {
    sleep_ms(1);
  }

#if defined(PCBX12S) || defined(RADIO_TX16S) || defined(RADIO_F16) || defined(RADIO_V16)
  // The audio amp needs ~2s to start
  sleep_ms(1000); // 1s
#endif

  time_point_t next_tick = time_point_now();
  while (task_running()) {
    DEBUG_TIMER_SAMPLE(debugTimerAudioIterval);
    DEBUG_TIMER_START(debugTimerAudioDuration);
    audioQueue.wakeup();
#if defined(PDM_CLOCK)
    // Drive microphone recording (if any) at the audio-task cadence.
    // Much shorter than the UI tick interval, so the PDM ring buffer
    // never fills enough to trigger skip-ahead / sample drops.
    PdmWavRecorder::audioTick();
#endif
    DEBUG_TIMER_STOP(debugTimerAudioDuration);
    sleep_until(&next_tick, 4);
  }
}

static timer_handle_t _timer10ms = TIMER_INITIALIZER;

static void _timer_10ms_cb(timer_handle_t* h)
{
  per10ms();
}

static void timer10msStart()
{
  if (!timer_is_created(&_timer10ms)) {
    timer_create(&_timer10ms, _timer_10ms_cb, "10ms", 10, true);
  }

  timer_start(&_timer10ms);
}

#if defined(COLORLCD) && defined(SIMU)
static timer_handle_t _timer1ms = TIMER_INITIALIZER;

static void _timer_1ms_cb(timer_handle_t* h)
{
  // Increment LVGL animation timer
  lv_tick_inc(1);
}

static void timer1msStart()
{
  if (!timer_is_created(&_timer1ms)) {
    timer_create(&_timer1ms, _timer_1ms_cb, "1ms", 1, true);
  }

  timer_start(&_timer1ms);
}
#endif

void tasksStart()
{
  mutex_create(&audioMutex);

#if defined(CLI) && !defined(SIMU)
  cliStart();
#endif

#if defined(COLORLCD) && defined(SIMU)
  timer1msStart();
#endif

  timer10msStart();

  task_create(&menusTaskId, menusTask, "menus", menusStack, MENUS_STACK_SIZE,
              MENUS_TASK_PRIO);

#if defined(AUDIO)
  task_create(&audioTaskId, audioTask, "audio", audioStack, AUDIO_STACK_SIZE,
              AUDIO_TASK_PRIO);
#endif

  RTOS_START();
}
