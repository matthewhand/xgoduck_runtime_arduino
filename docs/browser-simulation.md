# Duck Lab: browser simulation and live view

Open **Duck Lab** from the runtime's navigation, or visit
`http://<board-ip>:9527/simulate.html`.

For WebGPU, use a browser with WebGPU support and a secure origin. The USB
forward is a convenient localhost origin:

```sh
adb forward tcp:19527 tcp:9527
```

Open `http://127.0.0.1:19527/simulate.html` on that PC. Recreate the forward after
reconnecting USB. Plain HTTP at the board's Wi-Fi address uses the WebGL 2
fallback. The renderer badge reports the backend actually initialized.

With SSH enabled on the UNO Q, use the same localhost URL over Wi-Fi by
leaving this tunnel open in a terminal:

```sh
ssh -NT -L 127.0.0.1:19527:127.0.0.1:9527 arduino@<board-ip>
```

## Where the work runs

The UNO Q serves the page, CAD assets and telemetry. The viewing device runs
Three.js graphics on its GPU and the Physics playground on its CPU.
**Walking policy** instead runs both ONNX and MuJoCo on the UNO Q CPU and
streams poses to the viewer. Browser graphics do not load the UNO Q Adreno.
The **Board CPU** and **Board GPU** readings describe the UNO Q. The render FPS
and physics clock describe the viewing device. **Missed Linux slots** counts
board scheduling misses since app start, so it can be compared across a trial.

Browser dependencies are vendored locally: Three.js 0.187.0, official MuJoCo 3.12.0
WASM, and the XGO Duck model from LuwuDynamics/xgoduck_rl commit
`fa621fc77ad9a05d69da13270e86118bdd3603fe`. The runtime bundle is approximately
19 MB. The first page load downloads and compiles WASM. Native MuJoCo is an
optional dependency used only by Walking policy.

## Workspaces

| Mode | Behavior |
| --- | --- |
| Pose | Edit 14 joints within CAD limits; select parts in 3D; load upstream Stand/Sit/Fold poses; save and load local JSON poses. |
| Step cycle | A labelled procedural joint animation in Pose mode. It previews articulation without physics or a trained walking policy. |
| Physics → Walking policy | The default controller in Physics runs the shipped `xgoduck_walk.onnx` against the upstream walking scene on the UNO Q. Choose a forward speed and turn rate, then start a trial of up to 20 seconds. The camera follows the simulated Duck. |
| Physics → Playground | A free-body MuJoCo simulation in the browser. Drop, nudge, pause or step by 20 ms. Adjust gravity, floor friction and playback speed. |
| Explore | Pick a passage and start a beacon hunt. The simulated Duck maps nearby obstacles, chooses where to walk, and reveals the beacon when its range scan hits it. |
| Live Duck | Poll `/api/status` and display commanded targets or measured angles. No motor commands are sent. Targets and partial/unavailable measurements use a translucent model. |
| Demo | Automatically cycle through the pose presets, step preview, drop test, walking and get-up, beacon hunt, and live telemetry. |

Drag the canvas to orbit and scroll to zoom. Collision hulls and joint axes can
be overlaid. Space toggles playback when the canvas has focus. Pose JSON files
are processed locally; invalid schemas, non-finite angles, missing joints and
out-of-range targets are rejected before changing the pose.

In Live Duck, missing measured joints show a dash. Feedback older than 250 ms
is not applied. After a lost connection, the last pose freezes and numerical
readings become unavailable; fresh packets resume the view. IMU gravity supplies
roll and pitch only when the IMU is available. Yaw and world translation are not
measured, and the live model remains anchored in this view.

## Demo circuit

For a hands-free loop, select **Demo** or open `simulate.html?demo=1`.
The walk demonstrates Poke, Nudge, and Bash beside a pond with fixed trail
markers. The scenery gives the viewer a reference for movement. The beacon
hunt alternates north and south passages on successive laps. The policy views retain the
board load graph and both missed-slot counters. Keep the tab visible to see
every scene and leave the hardware in **Shadow** or **Off**. **Stop demo** or
another workspace ends the loop and asks the UNO Q to stop its current demo
trial. Closing the page also ends the loop. Each rollout has a time limit.

## Running a walking trial

Open **Physics** with **Walking policy** selected. Leave the hardware runtime
in **Shadow** or **Off**, pick a command and select **Run 20 s**. The simulation
worker runs at lower priority in a separate process, with one ONNX CPU thread.
It never calls the motor or MCU APIs.
**Stop** ends the worker and keeps the last pose. A walking trial runs until
the time limit, including any time spent getting up.

Use **Poke**, **Nudge**, or **Bash** during a walking trial to add a sideways
velocity impulse of 0.12, 0.30, or 0.80 m/s to the simulated trunk. Bash can
knock the Duck over. After a sustained fall, the simulation holds the recovery
pose, runs the shipped `xgoduck_getup.onnx`, and resumes the original walking
command once the trunk is upright. The panel reports the phase, peak tilt and
recovery time. Use Bash early enough to watch the Duck resume walking before
the 20-second limit. Outcomes depend on the command and phase of the stride.
Pushes only affect the walking simulation.

The board load graph shows total Linux CPU, the busiest core, and the Adreno
GPU. A dash means that a reading is unavailable. **Missed sim slots** counts
expired 20 ms releases that the simulation skips to keep pace with wall time.
**Missed Duck slots** is the separate change in the hardware runtime's Linux
missed-slot counter during the trial, including worker startup. **Slot work
p95** is the 95th percentile over the latest five seconds of ONNX and physics
work. **ONNX average** covers the inference portion alone. The hardware's own
control loop retains its existing settings.

To enable this mode on a new UNO Q, first start the app normally, then run
this in an UNO Q Linux shell. Replace the container name if the app directory
is named differently.

```sh
docker exec xgo-duck-main-1 uv pip install \
  --target /app/.cache/walk-sim-deps --python /app/.cache/.venv/bin/python \
  --no-deps mujoco==3.12.0 absl-py etils glfw PyOpenGL fsspec \
  importlib-resources typing-extensions zipp
```

The app already includes NumPy and ONNX Runtime. Reload Duck Lab after the
installation. Other Lab modes work without the optional package.

**Explore** uses the same walking worker and timing counters. It builds an
occupancy grid from a short-range 360° simulated rangefinder and uses simulated
position and heading to place those readings. The route planner seeks the
edge of the observed space and uses the shipped ONNX policy to walk there.
The 3D view shows the arena, while the range map shows the cells seen so far,
the route taken, and the beacon once detected. A search stops on detection,
a fall, or after 60 seconds.

## Model fidelity

The MJCF has 14 simulated joints. Runtime motor IDs 10–14 and 20–24 map to the
legs; 30–33 map to neck/head. Mouth motor 34 has no joint in the upstream model.
The runtime motor order differs from the MJCF chain order; mapping is by name
and explicit motor ID, not array position.

The physics playground does not run an ONNX walking or balance policy. Falling
without a controller is expected. **Hold joint targets** enables the upstream
model's companion PD actuators; training uses BAM actuator models, which are
not implemented here. Servo delay, electrical behavior, calibration and
sim-to-real agreement remain unvalidated. This is a physics/inspection sandbox,
not an equivalent of the training environment.

The walking trial uses each exported policy's home pose, raw actions and
action scale, with four 5 ms MuJoCo steps per 20 ms policy slot. It builds on
the pinned upstream `scene_walk.xml` and its approximate position actuators.
Physics walking trials enable floor contact on the CAD links and head-to-trunk
contact for get-up. The walking and get-up models are warmed before the clock
starts. The recovery state machine shares the runtime's fall and stand timers.
Results describe the simulated Duck with approximate servo dynamics.

## Reproduction and checks

```sh
python3 tools/prepare-browser-sim.py
node tools/check-browser-sim.mjs
```

The preparation tool verifies npm archive integrity and pinned Git blob hashes.
`assets/sim/vendor-lock.json` records the dependency/model payload checksums;
`.gitattributes` preserves those exact bytes on Windows and Linux. Licenses and
attribution are in `assets/sim/NOTICE.txt` and the bundled license files.

The Node checks load the actual WASM/MJCF, validate meshes and motor mapping,
exercise zero gravity, free fall and floor contacts, reject invalid pose files,
and check missing/stale feedback and IMU attitude. They require Node.js, but
the deployed browser application does not.

With native MuJoCo installed, run `python -B tools/check-walk-sim.py` using the
app's Python and dependency path. This checks the full 20-second straight-ahead
trial with the shipped ONNX file, forward travel, bilateral foot contacts, and
trunk height throughout the run. It also checks balance after Poke and Nudge,
and verifies that Bash causes a fall, the get-up policy runs, and both feet
resume stepping afterwards.

Browser checks on 7 November 2026 confirmed WebGPU at approximately 60 fps on
localhost, the WebGL 2 path over Wi-Fi HTTP, joint editing, the Sit preset,
procedural stepping, physics drop/pause/single-step, overlays, live missing-motor
indicators, and local pose import/export. UNO Q feedback remained approximately
100 Hz with torque disabled. Rendering speed is a local observation, not a
guarantee for other devices.

A controlled USB transport interruption confirmed that the live model freezes,
joint/GPU readings become unavailable, and fresh telemetry resumes when the
forward is restored. The loaded 3D scene kept rendering during the interruption.

References: [Three.js WebGPURenderer](https://threejs.org/docs/pages/WebGPURenderer.html),
[MuJoCo JavaScript bindings](https://github.com/google-deepmind/mujoco/tree/3.12.0/wasm),
[Luwu XGO Duck model](https://github.com/LuwuDynamics/xgoduck_rl/tree/fa621fc77ad9a05d69da13270e86118bdd3603fe/src/mjlab_microduck/robot/xgoduck).
