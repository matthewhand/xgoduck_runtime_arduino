#pragma once
#include <Arduino_LED_Matrix.h>

// The CPU/GPU pair is published atomically; only the low-priority sketch loop
// renders. Neither the RPC nor the display touches motor control or watchdogs.
static Arduino_LED_Matrix loadMatrix;
static atomic_t loadReadings = ATOMIC_INIT(0); // Each byte encodes percent + 2.
static atomic_t loadSampleMs = ATOMIC_INIT(0);

static void receiveLoad(int cpu, int gpu) {
  if (cpu < -2 || cpu > 100 || gpu < -2 || gpu > 100) return;
  atomic_set(&loadSampleMs, static_cast<atomic_val_t>(static_cast<uint32_t>(millis())));
  atomic_set(&loadReadings, (cpu + 2) | ((gpu + 2) << 8));
}

// An older host collector can still drive the GPU-only page.
static void receiveGpu(int percent) { receiveLoad(-2, percent); }

static void updateLoadMatrix(bool bridgeConnected) {
  static bool started = false;
  const unsigned readings = atomic_get(&loadReadings);
  const int cpu = static_cast<int>(readings & 0xffu) - 2;
  const int gpu = static_cast<int>((readings >> 8) & 0xffu) - 2;
  if (cpu == -2 && gpu == -2) {
    if (started) { loadMatrix.clear(); loadMatrix.end(); started = false; }
    return;
  }
  if (!started) { loadMatrix.begin(); started = true; }
  const uint32_t now = static_cast<uint32_t>(millis());
  const bool showCpu = cpu != -2 && (gpu == -2 || (now / 3000u) % 2u == 0);
  const bool fresh = bridgeConnected && now - static_cast<uint32_t>(atomic_get(&loadSampleMs)) <= 5000u;
  const int percent = fresh ? (showCpu ? cpu : gpu) : -1;
  uint32_t frame[4] = {};
  auto pixel = [&](unsigned x, unsigned y) {
    const unsigned i = y * 13 + x;
    frame[i / 32] |= 1u << (31 - i % 32);
  };
  // C/G fits at left, digits use rows 2–6, and row 7 is the percent gauge.
  const uint8_t label[5] = {7, 4, static_cast<uint8_t>(showCpu ? 4 : 5),
                           static_cast<uint8_t>(showCpu ? 4 : 5), 7};
  for (unsigned y = 0; y < 5; ++y)
    for (unsigned x = 0; x < 3; ++x)
      if (label[y] & (4u >> x)) pixel(x, y);
  static const uint8_t digits[10][5] = {
    {7,5,5,5,7}, {2,6,2,2,7}, {7,1,7,4,7}, {7,1,7,1,7}, {5,5,7,1,1},
    {7,4,7,1,7}, {7,4,7,5,7}, {7,1,1,1,1}, {7,5,7,5,7}, {7,5,7,1,7}
  };
  auto digit = [&](unsigned d, unsigned x) {
    for (unsigned y = 0; y < 5; ++y)
      for (unsigned bit = 0; bit < 3; ++bit)
        if (digits[d][y] & (4u >> bit)) pixel(x + bit, y + 2);
  };
  if (percent < 0) {
    for (unsigned x = 6; x < 9; ++x) pixel(x, 4);
    for (unsigned x = 10; x < 13; ++x) pixel(x, 4);
  } else {
    if (percent == 100) digit(1, 3);
    if (percent >= 10) digit((percent / 10) % 10, 6);
    digit(percent % 10, 10);
    for (int x = 0; x < (percent * 13 + 50) / 100; ++x) pixel(x, 7);
    if ((now / 1000u) % 2u) pixel(12, 0);
  }
  // Supply four packed words directly: avoids the core 1.0.0 bitmap helper's
  // three-word internal buffer for this 104-pixel matrix.
  loadMatrix.loadFrame(frame);
}
