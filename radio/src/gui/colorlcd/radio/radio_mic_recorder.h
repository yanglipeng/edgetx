#pragma once

#include "page.h"
#include "sdcard.h"

#if defined(PDM_CLOCK)
  #include "pdm_wav_recorder.h"
#elif defined(USE_VS1053B)
  #include "vs1053b_recorder.h"
#endif

#if defined(PDM_CLOCK) || defined(USE_VS1053B)

class TextButton;
class StaticText;

class RadioMicRecorder : public Page
{
 public:
  RadioMicRecorder();
  ~RadioMicRecorder() override;

 protected:
  enum class State : uint8_t { IDLE, COUNTDOWN, RECORDING };

  static constexpr uint32_t COUNTDOWN_SECONDS = 5;
  static constexpr int PATH_MAX_LEN = sizeof(SOUNDS_PATH) + 14;

  State state = State::IDLE;
  tmr10ms_t stateStart = 0;
  char filename[PATH_MAX_LEN] = {0};
  char pendingRename[PATH_MAX_LEN] = {0};

#if defined(PDM_CLOCK)
  PdmWavRecorder recorder;
#elif defined(USE_VS1053B)
  Vs1053bRecorder recorder;
#endif

  StaticText* bigLabel = nullptr;
  StaticText* infoLabel = nullptr;
  TextButton* actionButton = nullptr;

  void buildHeader(Window* window);
  void buildBody(Window* window);
  void checkEvents() override;
  void onEvent(event_t event) override;

  void onActionPressed();
  void enterIdle();
  void enterCountdown();
  void enterRecording();
  void stopRecording();
  void processPendingRename();
  void applyRename();
  void refreshUI();
  void pickNextFilename();

  static void asyncProcessPendingRename(void* ctx);
};

#endif
