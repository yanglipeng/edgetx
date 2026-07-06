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

#pragma once

#include "edgetx.h"

#if defined(USE_VS1053B)

#include <stdint.h>
#include "ff.h"

// Records 16-bit 16 kHz mono PCM WAV via the VS1053B's analog mic/line input.
// The chip operates in encoding mode: SM_LINE1 enables the analog path, no
// SM_ADPCM produces raw PCM, and we read samples directly from the SDI port.
class Vs1053bRecorder
{
 public:
  static constexpr uint32_t DST_RATE = 16000;

  // expectedSeconds == 0 means open-ended; header is patched on stop().
  FRESULT start(const char* path, uint32_t expectedSeconds);
  FRESULT stop();

  // Called from the audio task every ~4 ms.
  static void audioTick();

  // Trim leading/trailing silence and patch the WAV header.
  static FRESULT trimSilence(const char* path);

  bool isRecording() const { return recording; }
  uint32_t getSamplesWritten() const { return samplesWritten; }
  uint32_t getBytesWritten() const { return samplesWritten * 2U; }
  uint32_t getElapsedSeconds() const { return samplesWritten / DST_RATE; }

 private:
  static constexpr uint32_t PCM_MAX = 256;

  bool tickLocked();

  FIL file;
  int16_t pcm[PCM_MAX];
  volatile uint32_t samplesWritten = 0;
  uint32_t maxSamples = 0;  // 0 = open-ended
  volatile bool recording = false;
};

#endif  // USE_VS1053B
