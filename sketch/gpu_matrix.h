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

static void drawMatrixClip(unsigned clip, unsigned frame) {
  const uint8_t *packed = matrixClips[clip][frame];
  uint8_t pixels[104];
  for (unsigned i = 0; i < 104; i += 8, packed += 3) {
    uint32_t word = packed[0] | (uint32_t(packed[1]) << 8) | (uint32_t(packed[2]) << 16);
    for (unsigned j = 0; j < 8; ++j, word >>= 3) pixels[i + j] = word & 7u;
  }
  loadMatrix.draw(pixels);
}

static void drawMatrixLoad(bool cpu, int percent) {
  uint8_t pixels[104] = {};
  const uint8_t label[5] = {7, 4, uint8_t(cpu ? 4 : 5), uint8_t(cpu ? 4 : 5), 7};
  static const uint8_t digits[10][5] = {
    {7,5,5,5,7}, {2,6,2,2,7}, {7,1,7,4,7}, {7,1,7,1,7}, {5,5,7,1,1},
    {7,4,7,1,7}, {7,4,7,5,7}, {7,1,1,1,1}, {7,5,7,5,7}, {7,5,7,1,7}
  };
  auto glyph = [&](const uint8_t *rows, unsigned x, unsigned y) {
    for (unsigned row = 0; row < 5; ++row)
      for (unsigned bit = 0; bit < 3; ++bit)
        if (rows[row] & (4u >> bit)) pixels[(y + row) * 13 + x + bit] = 4;
  };
  glyph(label, 0, 0);
  if (percent == 100) glyph(digits[1], 3, 2);
  if (percent >= 10) glyph(digits[(percent / 10) % 10], 6, 2);
  glyph(digits[percent % 10], 10, 2);
  for (int x = 0; x < (percent * 13 + 50) / 100; ++x) pixels[91 + x] = 2;
  loadMatrix.draw(pixels);
}

enum class MatrixPage { Art, Cpu, Gpu, Auto };
static constexpr unsigned matrixManualMs = 3000;
static constexpr unsigned matrixAutoPageMs = 1400;
static constexpr unsigned matrixCooldownMs = 20000;
static constexpr unsigned matrixClipMs = matrixClipFrames * matrixFrameMs;
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

  if (page == MatrixPage::Art) {
    const unsigned completed = (now - clipAt) / matrixClipMs;
    if (completed) {
      clipAt += completed * matrixClipMs;
      clip = (clip + completed) % matrixClipCount;
      slides += completed;
      if (slides > matrixSlidesPerGlance) slides = matrixSlidesPerGlance;
      lastFrame = matrixClipFrames;
    }
    const bool cooled = !showedLoad || now - lastLoadAt >= matrixCooldownMs;
    if (autoEnabled && available && cooled && (significant || slides >= matrixSlidesPerGlance))
      show(MatrixPage::Auto);
  }

  if (page != MatrixPage::Art) {
    const bool cpuPage = page == MatrixPage::Cpu || (page == MatrixPage::Auto && shownCpu >= 0
      && (shownGpu < 0 || now - pageAt < matrixAutoPageMs));
    const int readout = cpuPage ? 0 : 1;
    if (lastReadout != readout) {
      drawMatrixLoad(cpuPage, cpuPage ? shownCpu : shownGpu);
      lastReadout = readout;
    }
    return;
  }

  const unsigned frame = (now - clipAt) / matrixFrameMs;
  if (frame != lastFrame) {
    drawMatrixClip(clip, frame);
    lastFrame = frame;
  }
}
