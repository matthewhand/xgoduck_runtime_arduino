# UNO Q matrix animations and load readouts

The UNO Q's 8 × 13 matrix cycles through twelve scenes, including two
Mandelbrot dives, cosmic waves, Duckzilla and Duck Regatta, animated impasto,
and miniature nature scenes. A full lap takes about two minutes. Load is
available in Duck Lab and as a brief matrix readout.
An optional compute proof exercises the Adreno and verifies its outputs.
ONNX policy inference continues to use the CPU.

## Deployment

1. Deploy the Duck app through App Lab, following the main README. Leave it in
   **Inference only** until the Duck is assembled and calibrated.
2. In a Linux terminal **on the UNO Q host**, enter the app's source directory.
   The collector runs outside the App Lab container so it can inspect host GPU
   clients. Its `.cache/gpu-status.json` must be in the same source tree mounted
   into the app container.
3. Start a one-minute collector:

   ```sh
   python3 tools/gpu-monitor.py --seconds 60
   ```

   A fresh cache file enables the load readout.
   Run with host permissions that can read the relevant GPU clients. Limited
   `/proc` permissions can restrict coverage. Do not make `/proc` world-readable.
4. Run the Python compute proof in another host terminal. It uses only Python's
   standard library and the installed EGL/GLES driver:

   ```sh
   python3 tools/gpu-proof.py --seconds 10
   ```

   It dispatches on the GPU, then checks all 65,536 outputs on the CPU. The
   reference check takes additional time after the requested dispatch interval.
   It rejects software renderers. This does not require a compiler or pip install.
   On Linux it runs at nice level 10 so this diagnostic and its CPU reference
   have lower scheduling priority than the robot's normal control processes.

   Alternatively, install build dependencies **on the UNO Q** and build the C version:

   ```sh
   sudo apt install build-essential libegl-dev libgles-dev
   mkdir -p .cache
   cc -O2 tools/gpu-proof.c -o .cache/gpu-proof -lEGL -lGLESv2
   .cache/gpu-proof 10
   ```

   This requires working Mesa EGL/GLES drivers. It fails if EGL is unavailable
   or the renderer is not Adreno/FD702, including software rendering. A pass
   requires a completed compute dispatch and all 65,536 results matching a CPU
   reference. It proves GPU compute, not GPU-accelerated ONNX or WebGPU support.

## Reading the display

In Duck Lab, press **Matrix readout** to show **C** (total CPU busy).
Tap again within three seconds for **G** (measured GPU activity), and again
to resume the animation. Each reading times out after three seconds. A gauge
along the bottom shows the same percentage. Unavailable readings are skipped.
Python and the MCU both check sample freshness. Older GPU-only collector samples
still drive the G page.

**Automatic load flashes** is off on boot. When enabled it shows a brief
readout after four clips, or when CPU or GPU changes by at least 15 percentage
points from its reference in the same direction across two fresh samples.
Automatic readouts wait at least 20 seconds between displays. The animations
use a maximum level of 5 out of 7, fade at the ends, and leave a short dark
gap between scenes. Regenerate their packed frames with
`python3 tools/make-matrix-clips.py`.

On an UNO Q configured with `HandlePowerKey=ignore` and
`HandlePowerKeyLongPress=reboot`, the optional `tools/matrix-button.py`
listener gives a quick tap of the power button the same behavior as the web
button. The helper reads the existing input device without grabbing it. Start
it as the `arduino` user with input-device access. To start it on reboot, add:

```cron
@reboot /usr/bin/python3 /home/arduino/ArduinoApps/xgo-duck/tools/matrix-button.py >> /home/arduino/ArduinoApps/xgo-duck/.cache/matrix-button.log 2>&1
```

Removing `.cache/gpu-status.json` disables the load readout. The monitor stops after
the requested duration (1–3600 seconds); its final sample remains as evidence.
Use `--seconds 0 --quiet` for continuous monitoring without per-sample log output.
Only one collector can write a given output file; a second instance exits without
replacing the first instance's samples.

For optional startup on boot, add this line with `crontab -e` on the UNO Q,
adjusting the app path if necessary:

```cron
@reboot /bin/sleep 20 && /usr/bin/python3 /home/arduino/ArduinoApps/xgo-duck/tools/gpu-monitor.py --seconds 0 --quiet >> /home/arduino/ArduinoApps/xgo-duck/.cache/gpu-service.log 2>&1
```

The Duck app must also be running to forward samples to the matrix. App Lab's
default-app setting controls that separately. Stop the collector and remove its
cron entry before removing the cache file to disable load collection permanently.

**Control** shows total CPU, busiest core, GPU activity and **Missed Linux slots**.
Duck Lab also shows board load and misses. The `cpu` and `gpu` fields of
`GET /api/status` carry the load readings; `GET /api/gpu` remains GPU-only.

Use busiest core and the change in missed slots to assess a new workload. One
busy core can be hidden by a modest average across four cores. The missed-slot
counter is cumulative since app start; compare it before and during the test
alongside the feedback rate. Browser rendering runs on the viewing device, so
Duck Lab can show high frame rates while the UNO Q's GPU page reads zero.

If the board's Wi-Fi connection is unreliable, forward the dashboard over USB
from a PC with ADB, then open `http://127.0.0.1:19527` on that PC:

```sh
adb forward tcp:19527 tcp:9527
```

The app and GPU work still run on the board. Recreate the forward after a USB
disconnect or board restart. Select the intended device with `adb -s <serial>`
if more than one ADB device is connected.

## What the percentage measures

- CPU uses changes in Linux `/proc/stat` counters over the sample interval,
  excluding idle and I/O wait from busy time and avoiding double-counted guest
  time. The dashboard shows the aggregate and the busiest reporting core.
- With a KGSL `gpubusy` node, it is the device busy-time ratio from that node.
- With mainline MSM DRM, it is the change in `drm-engine-gpu` time divided by
  elapsed time, summed across readable clients. Duplicate/shared descriptors are
  counted once using `drm-client-id`. New clients require two samples. Exited or
  unreadable clients can be missed, so this is **GPU activity for visible
  clients**, not guaranteed whole-device utilization. Kernel accounting can lag
  until work completes. Values are bounded to 0–100 for this single-engine GPU.
- GPU clock speed is not substituted for utilization. If neither source is
  available, the metric remains unavailable.

The collector keeps an idle render-node descriptor open so MSM can report a
real zero-time client even when no app is rendering. It does not submit GPU
work. This enables an idle reading without inventing data on unsupported drivers.

Sampling and JSON I/O occur outside the 50 Hz policy and 100 Hz hardware loops.
The host collector publishes at 1 Hz. Matrix rendering runs in the existing
low-priority sketch loop; its RPC handler only updates atomics. The new message
does not update the motor-control heartbeat or change arming state.

## Validation status

Run the portable counter/cache checks with:

```sh
python3 tools/check-gpu-telemetry.py
```

Validation on a physical UNO Q 4 GB on 7 November 2026:

- Debian 13, Mesa 25.2.6-1~bpo13+1, renderer `FD702`, OpenGL ES 3.1.
- Python proof: **PASS**, 137 compute batches over a five-second dispatch
  interval; all 65,536 results verified. Dispatch and CPU verification together
  took 21.12 seconds.
- A subsequent ten-second dispatch test measured a **41.0%** peak for readable
  DRM clients, with all outputs verified. Some processes were inaccessible;
  this is not whole-device utilization.
- All six portable telemetry checks passed on both the board and Windows.
- The matrix C++ harness and C proof syntax check passed on Windows.

The full Duck sketch subsequently compiled and flashed with core 1.0.0 and the
runtime's Bridge patches. The Python app started with App CLI 0.6.6 and App
Bricks 0.5.0, loaded all eight ONNX policies, and served fresh host GPU samples
through both status APIs. The hardware reported motor torque disabled. The
factory WebUI fallback was checked to retain same-origin Socket.IO behavior.

After updating Arduino Router to 0.11.0, an end-to-end GPU test on the factory
Python image kept MCU feedback at approximately 100 Hz, with no Bridge
reconnects, bad feedback frames, MCU overruns, or additional missed Linux control
cycles. App CLI was subsequently upgraded to 0.14.1 with App Bricks 0.13.2;
ordinary App CLI startup then worked without a manual router group override.
Its first stress run passed the GPU check and measured a 40.2% peak, with clean
MCU counters, but recorded two missed Linux scheduling slots. The proof now
runs at nice level 10 to reduce interference from background diagnostics.

The final test, after a full board restart, passed all checks: 279 GPU batches,
65,536 verified outputs, a **41.7%** readable-client peak, **99.8 Hz** feedback,
no API failures, no Bridge reconnects, no bad frames or MCU overruns, and zero
additional missed Linux scheduling slots. Dispatch plus CPU verification took
26.19 seconds. Both the Duck app and the GPU collector started automatically
after the restart, with motor torque off. The final dashboard and API test used
USB forwarding because the Wi-Fi link was intermittent.

All samples reported inference-only mode with torque disabled. No motors or IMU
were attached, so these checks verify communication and diagnostics under GPU
load, not walking or 50 Hz policy execution with live observations. Linux
scheduling is not a hard real-time guarantee; measure deadlines again with
actual sensors, policies, and any proposed GPU workload before enabling motion.

The user confirmed readable matrix digits, the blinking dot, and the rising
bottom gauge on the board. Optional C proof execution remains untested; the
Python proof has been exercised on the actual GPU.

The CPU/GPU display update was compiled and flashed on the same board, and
the MCU accepted a paired reading. A low-priority single-core workload raised
aggregate CPU from a 14.1% idle median to 35.0%, with the busiest core at 100%.
The Adreno proof verified all 65,536 results and reached 40.7% measured GPU
activity. Feedback stayed near 100 Hz with no additional Linux scheduling misses,
Bridge reconnects or MCU overruns in these trials. Nine portable telemetry tests
passed on Windows and the board. A matrix harness checked rotation, 100%,
unavailable pages, legacy GPU samples and timer rollover.

When launching Arduino commands from an ADB shell on this image, use
`TMPDIR=/tmp`; ADB's default `/data/local/tmp` does not exist on the board.
Factory router 0.5.3 also lacks the `$/version` probe used by this runtime and
must be updated before use. Merely changing its baud rate causes repeated
Bridge reconnects. Keep App CLI compatible with the router: the older CLI
0.6.6 does not add the new router socket's supplementary group to app containers.
The Python entrypoint handles App Bricks 0.5.0's older WebUI constructor while
keeping Socket.IO restricted to the same origin.

When upgrading App CLI on a factory image, also check `arduino-cli core list`.
The globally installed core 0.51.0 uses a different upload menu from this app's
pinned core 1.0.0; App CLI can otherwise choose the wrong upload method and report
`invalid option 'flash_mode'`. Installing the matching global core resolves that:

```sh
TMPDIR=/tmp arduino-cli core install arduino:zephyr@1.0.0
```

References: [UNO Q datasheet](https://docs.arduino.cc/resources/datasheets/ABX00162-ABX00173-datasheet.pdf),
[Linux DRM usage statistics](https://docs.kernel.org/gpu/drm-usage-stats.html),
[MSM GPU accounting](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/msm/msm_gpu.c).
