# GPU activity on the UNO Q LED matrix

This optional experiment runs a verified compute shader on the UNO Q Adreno GPU
and shows measured GPU activity on its 8 x 13 matrix. ONNX policy inference
continues to use the CPU. The GPU proof runs only when explicitly launched.

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

   A fresh cache file enables the matrix; no file leaves the matrix untouched.
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

The three-by-five digits show 0–100, with a thirteen-pixel gauge along the bottom.
The corner heartbeat alternates each second. `--` means missing, unsupported,
invalid or stale telemetry; it does not mean zero GPU usage. Both Python and the
MCU independently stop showing a numeric value after five seconds without data.
Removing `.cache/gpu-status.json` disables the display. The monitor stops after
the requested duration (1–3600 seconds); its final sample remains as evidence.

The same sample is returned by `GET /api/gpu` and the `gpu` field of
`GET /api/status`.

## What the percentage measures

- With a KGSL `gpubusy` node, it is the device busy-time ratio from that node.
- With mainline MSM DRM, it is the change in `drm-engine-gpu` time divided by
  elapsed time, summed across readable clients. Duplicate/shared descriptors are
  counted once using `drm-client-id`. New clients require two samples. Exited or
  unreadable clients can be missed, so this is **GPU activity for visible
  clients**, not guaranteed whole-device utilization. Kernel accounting can lag
  until work completes. Values are bounded to 0–100 for this single-engine GPU.
- GPU clock speed is not substituted for utilization. If neither source is
  available, the metric remains unavailable.

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
- Host DRM collector measured a peak of **40.7%** for readable clients during
  the experiment. Some processes were inaccessible; this is not whole-device
  utilization. The board clock was not yet synchronized, so raw log timestamps
  are not the date of the experiment.
- All six portable telemetry checks passed on both the board and Windows.
- The matrix C++ harness and C proof syntax check passed on Windows.

Still pending: C proof execution, App Lab cache sharing, full Duck sketch
compilation, matrix orientation, and control-loop timing under GPU load. The
stock board had core 0.51.0 and App CLI 0.6.6; the Duck runtime requires core
1.0.0 and newer Bridge libraries, which need installation before flashing.

When launching Arduino commands from an ADB shell on this image, use
`TMPDIR=/tmp`; ADB's default `/data/local/tmp` does not exist on the board.

References: [UNO Q datasheet](https://docs.arduino.cc/resources/datasheets/ABX00162-ABX00173-datasheet.pdf),
[Linux DRM usage statistics](https://docs.kernel.org/gpu/drm-usage-stats.html),
[MSM GPU accounting](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/msm/msm_gpu.c).
