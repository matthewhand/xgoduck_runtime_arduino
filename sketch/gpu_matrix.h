#pragma once
#include <Arduino_LED_Matrix.h>

// Optional display owns only the sketch's low-priority loop. RPC callbacks
// publish one atomic value; servo/IMU threads never render or wait on the matrix.
static Arduino_LED_Matrix gpuMatrix;
static atomic_t gpuPercent = ATOMIC_INIT(-2); // -2 disabled, -1 unavailable.
static atomic_t gpuSampleMs = ATOMIC_INIT(0);

static void receiveGpu(int percent) {
  if (percent < -2 || percent > 100) return;
  atomic_set(&gpuPercent, percent);
  atomic_set(&gpuSampleMs, millis());
}

static void updateGpuMatrix() {
  static bool started = false;
  int percent = atomic_get(&gpuPercent);
  if (percent == -2) {
    if (started) { gpuMatrix.clear(); gpuMatrix.end(); started = false; }
    return;
  }
  if (!started) { gpuMatrix.begin(); started = true; }
  if (!atomic_get(&bridgeReady) || (uint32_t)(millis() - atomic_get(&gpuSampleMs)) > 5000u) percent = -1;
  uint32_t frame[4] = {};
  auto pixel = [&](unsigned x, unsigned y) {
    const unsigned i = y * 13 + x;
    frame[i / 32] |= 1u << (31 - i % 32);
  };
  // Three-by-five digits fit 0..100; row 7 is a thirteen-pixel load gauge.
  static const uint8_t digits[10][5] = {
    {7,5,5,5,7}, {2,6,2,2,7}, {7,1,7,4,7}, {7,1,7,1,7}, {5,5,7,1,1},
    {7,4,7,1,7}, {7,4,7,5,7}, {7,1,1,1,1}, {7,5,7,5,7}, {7,5,7,1,7}
  };
  auto digit = [&](unsigned d, unsigned x) {
    for (unsigned y = 0; y < 5; ++y)
      for (unsigned bit = 0; bit < 3; ++bit)
        if (digits[d][y] & (4u >> bit)) pixel(x + bit, y);
  };
  if (percent < 0) {
    for (unsigned x = 2; x < 5; ++x) pixel(x, 2);
    for (unsigned x = 7; x < 10; ++x) pixel(x, 2);
  } else {
    if (percent == 100) digit(1, 0);
    if (percent >= 10) digit((percent / 10) % 10, 4);
    digit(percent % 10, 8);
    for (int x = 0; x < (percent * 13 + 50) / 100; ++x) pixel(x, 7);
  }
  if ((millis() / 1000) % 2) pixel(12, 0);
  // Supply four packed words directly: avoids the core 1.0.0 bitmap helper's
  // three-word internal buffer for this 104-pixel matrix.
  gpuMatrix.loadFrame(frame);
}
