#pragma once
#include <Arduino_LED_Matrix.h>
#include "matrix_clips.h"

// Only the sketch loop writes pixels. RPC handlers publish a paired sample or
// queue a display request, separately from the motor command and watchdog.
static Arduino_LED_Matrix loadMatrix;
static atomic_t loadReadings = ATOMIC_INIT(0); // Each byte encodes percent + 2.
static atomic_t loadSampleMs = ATOMIC_INIT(0);
static atomic_t matrixTaps = ATOMIC_INIT(0);
static atomic_t matrixAuto = ATOMIC_INIT(0);
static atomic_t matrixScene = ATOMIC_INIT(0);
static atomic_t matrixArtScene = ATOMIC_INIT(0);
static constexpr atomic_val_t sceneIndexMask = 0xff;
static constexpr atomic_val_t scenePending = 0x100;
static_assert(matrixClipCount <= sceneIndexMask + 1, "Scene index must fit in the RPC reply");

static void receiveLoad(int cpu, int gpu) {
  if (cpu < -2 || cpu > 100 || gpu < -2 || gpu > 100) return;
  atomic_set(&loadReadings, (cpu + 2) | ((gpu + 2) << 8));
  atomic_set(&loadSampleMs, static_cast<atomic_val_t>(static_cast<uint32_t>(millis())));
}

// An older host collector can still supply GPU-only readings.
static void receiveGpu(int percent) { receiveLoad(-2, percent); }

static bool receiveMatrix(int request) {
  if (request == 0) atomic_inc(&matrixTaps);
  else if (request == 1 || request == 2) atomic_set(&matrixAuto, request == 2);
  return atomic_get(&matrixAuto) != 0;
}

static int receiveMatrixScene(int request) {
  // -1 reads the current clip, -2 skips, and a nonnegative index selects.
  if (request < -2 || request >= int(matrixClipCount)) return -1;
  atomic_val_t state = atomic_get(&matrixScene);
  if (request != -1) {
    atomic_val_t next;
    do {
      state = atomic_get(&matrixScene);
      const int current = state & sceneIndexMask;
      const int art = current < int(matrixMarqueeFrom) ? current : atomic_get(&matrixArtScene);
      const int index = request == -2 ? (art + 1) % matrixMarqueeFrom : request;
      next = scenePending | index;
    } while (!atomic_cas(&matrixScene, state, next));
    state = next;
  }
  return (matrixCatalogId << 8) | (state & sceneIndexMask);
}

static void drawMatrixClip(unsigned clip, unsigned frame) {
  const uint8_t *packed = matrixClips[clip][frame];
  uint8_t pixels[104];
  for (unsigned i = 0; i < 104; i += 8, packed += 3) {
    uint32_t word = packed[0] | (uint32_t(packed[1]) << 8) | (uint32_t(packed[2]) << 16);
    for (unsigned j = 0; j < 8; ++j, word >>= 3) pixels[i + j] = word & 7u;
  }
  loadMatrix.draw(pixels);
}

static void matrixGlyph(uint8_t *pixels, const uint8_t *rows, int x, uint8_t level) {
  for (int col = 0; col < 3; ++col) {
    const int pixel = x + col;
    if (pixel < 0 || pixel >= 13) continue;
    for (unsigned row = 0; row < 5; ++row)
      if (rows[row] & (4u >> col)) pixels[row * 13 + pixel] = level;
  }
}

static constexpr unsigned readoutEntrySteps = 11;
static constexpr unsigned readoutTitleMs = 384;
static constexpr unsigned readoutSlideStepMs = 48;
static constexpr unsigned readoutExitSteps = 9;
static constexpr unsigned readoutFadeFirst = readoutEntrySteps + readoutExitSteps + 1;
static constexpr unsigned readoutFadeStepMs = 80;
static constexpr unsigned readoutFrameCount = readoutFadeFirst + 4;

static unsigned readoutFrame(unsigned elapsed) {
  const unsigned entryMs = readoutEntrySteps * readoutSlideStepMs;
  if (elapsed < entryMs) return elapsed / readoutSlideStepMs;
  elapsed -= entryMs;
  if (elapsed < readoutTitleMs) return readoutEntrySteps;
  elapsed -= readoutTitleMs;
  const unsigned exitMs = readoutExitSteps * readoutSlideStepMs;
  if (elapsed < exitMs) return readoutEntrySteps + 1 + elapsed / readoutSlideStepMs;
  const unsigned fade = (elapsed - exitMs) / readoutFadeStepMs;
  return readoutFadeFirst + (fade < 3 ? fade : 3);
}

static void drawMatrixLoad(bool cpu, int percent, unsigned frame) {
  uint8_t pixels[104] = {};
  const uint8_t label[5] = {7, 4, uint8_t(cpu ? 4 : 5), uint8_t(cpu ? 4 : 5), 7};
  if (frame < readoutFadeFirst) {
    static const uint8_t p[5] = {6,5,6,4,4};
    static const uint8_t u[5] = {5,5,5,5,7};
    const int offset = int(frame) - int(readoutEntrySteps);
    matrixGlyph(pixels, label, offset < 0 ? offset : 0, 4);
    matrixGlyph(pixels, p, 4 + offset, 4);
    matrixGlyph(pixels, u, 8 + offset, 4);
    loadMatrix.draw(pixels);
    return;
  }
  static const uint8_t digits[10][5] = {
    {7,5,5,5,7}, {2,6,2,2,7}, {7,1,7,4,7}, {7,1,7,1,7}, {5,5,7,1,1},
    {7,4,7,1,7}, {7,4,7,5,7}, {7,1,1,1,1}, {7,5,7,5,7}, {7,5,7,1,7}
  };
  const uint8_t level = frame - readoutFadeFirst + 1;
  matrixGlyph(pixels, label, 0, 4);
  if (percent == 100) matrixGlyph(pixels, digits[1], 3, level);
  if (percent >= 10) matrixGlyph(pixels, digits[(percent / 10) % 10], 6, level);
  matrixGlyph(pixels, digits[percent % 10], 10, level);
  for (int x = 0; x < (percent * 13 + 50) / 100; ++x) pixels[91 + x] = (level + 1) / 2;
  loadMatrix.draw(pixels);
}

enum class MatrixPage { Art, Cpu, Gpu, Auto };
static constexpr unsigned matrixManualMs = 3000;
static constexpr unsigned matrixAutoPageMs = 2400;
static constexpr unsigned matrixCooldownMs = 20000;
static constexpr unsigned matrixClipMs = matrixClipFrames * matrixFrameMs;
static constexpr unsigned matrixNoticeFrameMs = 96;
static constexpr unsigned matrixNoticeMs = matrixClipFrames * matrixNoticeFrameMs;
static constexpr unsigned matrixSlidesPerGlance = 4;
static constexpr int matrixLoadDelta = 15;

static unsigned loadChange(int current, int &reference, unsigned rise, unsigned fall) {
  if (current < 0) return 0;
  if (reference < 0) reference = current;
  if (current - reference >= matrixLoadDelta) return rise;
  if (reference - current >= matrixLoadDelta) return fall;
  return 0;
}

static void updateLoadMatrix(bool bridgeConnected) {
  static bool started = false, autoWasEnabled = false, showedLoad = false;
  static uint32_t clipAt, pageAt, pauseAt, lastLoadAt, seenSample, seenTaps;
  static unsigned clip, slides, previousChange, lastFrame = matrixClipFrames;
  static unsigned returnClip, returnElapsed;
  static int referenceCpu = -1, referenceGpu = -1, shownCpu, shownGpu;
  static MatrixPage page = MatrixPage::Art;
  static int lastReadout = -1;
  const uint32_t now = static_cast<uint32_t>(millis());
  if (!started) {
    loadMatrix.begin();
    loadMatrix.setGrayscaleBits(3);
    clipAt = now;
    started = true;
  }

  const uint32_t stamp = static_cast<uint32_t>(atomic_get(&loadSampleMs));
  const unsigned readings = atomic_get(&loadReadings);
  const bool fresh = bridgeConnected && now - stamp <= 5000u;
  const int cpu = fresh ? int(readings & 0xffu) - 2 : -2;
  const int gpu = fresh ? int((readings >> 8) & 0xffu) - 2 : -2;
  const bool available = cpu >= 0 || gpu >= 0;
  const bool autoEnabled = atomic_get(&matrixAuto) != 0;
  if (autoEnabled && !autoWasEnabled) {
    slides = previousChange = 0;
    referenceCpu = cpu;
    referenceGpu = gpu;
  }
  autoWasEnabled = autoEnabled;

  bool significant = false;
  if (!available) previousChange = 0;
  else if (stamp != seenSample) {
    seenSample = stamp;
    const unsigned change = loadChange(cpu, referenceCpu, 1, 2) |
                            loadChange(gpu, referenceGpu, 4, 8);
    significant = (change & previousChange) != 0;
    previousChange = change;
  }

  const unsigned autoDuration = matrixAutoPageMs * (unsigned(shownCpu >= 0) + unsigned(shownGpu >= 0));
  const bool expired = now - pageAt >= (page == MatrixPage::Auto ? autoDuration : matrixManualMs);
  auto resume = [&] {
    if (page != MatrixPage::Art) {
      clipAt += now - pauseAt;
      lastFrame = matrixClipFrames;
      page = MatrixPage::Art;
    }
  };
  if (expired || !available || (page == MatrixPage::Auto && !autoEnabled)) resume();

  auto show = [&](MatrixPage selected) {
    if (page == MatrixPage::Art) pauseAt = now;
    page = selected;
    pageAt = lastLoadAt = now;
    shownCpu = referenceCpu = cpu;
    shownGpu = referenceGpu = gpu;
    showedLoad = true;
    slides = previousChange = 0;
    lastReadout = -1;
  };

  const uint32_t taps = static_cast<uint32_t>(atomic_get(&matrixTaps));
  // Preserve rapid taps that arrive between two sketch iterations.
  unsigned queued = (taps - seenTaps) % (cpu >= 0 && gpu >= 0 ? 3u : 2u);
  seenTaps = taps;
  for (; available && queued > 0; --queued) {
    if (page == MatrixPage::Gpu || (page == MatrixPage::Cpu && gpu < 0)) resume();
    else if (page == MatrixPage::Cpu || cpu < 0) show(MatrixPage::Gpu);
    else show(MatrixPage::Cpu);
  }

  const atomic_val_t requested = atomic_get(&matrixScene);
  const bool jumped = (requested & scenePending) &&
                      atomic_cas(&matrixScene, requested, requested & sceneIndexMask);
  if (jumped) {
    const unsigned selected = requested & sceneIndexMask;
    if (selected >= matrixMarqueeFrom && clip < matrixMarqueeFrom) {
      returnClip = clip;
      returnElapsed = (page == MatrixPage::Art ? now : pauseAt) - clipAt;
      if (returnElapsed >= matrixClipMs) returnElapsed = matrixClipMs - 1;
    } else if (selected < matrixMarqueeFrom) {
      atomic_set(&matrixArtScene, selected);
      slides = previousChange = 0;
    }
    clip = selected;
    clipAt = now;
    page = MatrixPage::Art;
    lastFrame = matrixClipFrames;
  }

  if (page == MatrixPage::Art && clip >= matrixMarqueeFrom && now - clipAt >= matrixNoticeMs) {
    const unsigned finished = clip;
    clip = returnClip;
    clipAt = now - returnElapsed;
    atomic_cas(&matrixScene, finished, clip);
    lastFrame = matrixClipFrames;
  }

  if (page == MatrixPage::Art && clip < matrixMarqueeFrom) {
    const unsigned completed = (now - clipAt) / matrixClipMs;
    if (completed) {
      clipAt += completed * matrixClipMs;
      const unsigned previous = clip;
      clip = (clip + completed) % matrixMarqueeFrom;
      atomic_set(&matrixArtScene, clip);
      // A scene request may arrive while the natural transition is calculated.
      atomic_cas(&matrixScene, previous, clip);
      slides += completed;
      if (slides > matrixSlidesPerGlance) slides = matrixSlidesPerGlance;
      lastFrame = matrixClipFrames;
    }
    const bool cooled = !showedLoad || now - lastLoadAt >= matrixCooldownMs;
    if (!jumped && autoEnabled && available && cooled && (significant || slides >= matrixSlidesPerGlance))
      show(MatrixPage::Auto);
  }

  if (page != MatrixPage::Art) {
    const bool cpuPage = page == MatrixPage::Cpu || (page == MatrixPage::Auto && shownCpu >= 0
      && (shownGpu < 0 || now - pageAt < matrixAutoPageMs));
    const unsigned elapsed = now - pageAt;
    const unsigned frame = readoutFrame(page == MatrixPage::Auto ? elapsed % matrixAutoPageMs : elapsed);
    const int readout = frame + (cpuPage ? 0 : readoutFrameCount);
    if (lastReadout != readout) {
      drawMatrixLoad(cpuPage, cpuPage ? shownCpu : shownGpu, frame);
      lastReadout = readout;
    }
    return;
  }

  const unsigned frame = (now - clipAt) / (clip < matrixMarqueeFrom ? matrixFrameMs : matrixNoticeFrameMs);
  if (frame != lastFrame) {
    drawMatrixClip(clip, frame);
    lastFrame = frame;
  }
}
