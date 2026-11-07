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

## Where the work runs

The UNO Q serves the HTML, JavaScript, WebAssembly, CAD assets and existing
read-only telemetry API. The viewing device runs Three.js graphics on its GPU
and single-threaded MuJoCo physics on its CPU. This does not accelerate the
board's ONNX policies or use the board's Adreno for browser rendering on a PC.
The **Board GPU** reading is a separate metric from browser graphics activity.

All dependencies are vendored locally: Three.js 0.187.0, official MuJoCo 3.12.0
WASM, and the XGO Duck model from LuwuDynamics/xgoduck_rl commit
`fa621fc77ad9a05d69da13270e86118bdd3603fe`. The runtime bundle is approximately
19 MB. No Node installation, compiler, CDN or Python dependency is needed on
the board for this feature. The first page load downloads and compiles WASM.

## Workspaces

| Mode | Behavior |
| --- | --- |
| Pose | Edit 14 joints within CAD limits; select parts in 3D; load upstream Stand/Sit/Fold poses; save and load local JSON poses. |
| Step cycle | A labelled procedural joint animation in Pose mode. It previews articulation without physics or a trained walking policy. |
| Physics | A free-body MuJoCo simulation using upstream masses, inertia, collision meshes and joint limits, with gravity and floor contacts. Drop, nudge, pause or step by 20 ms; adjust gravity, floor friction and playback speed. |
| Live Duck | Poll `/api/status` and display commanded targets or measured angles. No motor commands are sent. Targets and partial/unavailable measurements use a translucent model. |

Drag the canvas to orbit and scroll to zoom. Collision hulls and joint axes can
be overlaid. Space toggles playback when the canvas has focus. Pose JSON files
are processed locally; invalid schemas, non-finite angles, missing joints and
out-of-range targets are rejected before changing the pose.

In Live Duck, missing measured joints show a dash. Feedback older than 250 ms
is not applied. After a lost connection, the last pose freezes and numerical
readings become unavailable; fresh packets resume the view. IMU gravity supplies
roll and pitch only when the IMU is available. Yaw and world translation are not
measured, and the live model remains anchored in this view.

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

Future work can add matched BAM actuation and closed-loop policy rollouts,
record/replay of joint and IMU telemetry, and additional scenes. Browser WebGPU
graphics do not imply GPU-accelerated physics or in-browser training.

## Reproduction and checks

```sh
python3 tools/prepare-browser-sim.py
node tools/check-browser-sim.mjs
```

The preparation tool verifies npm archive integrity and pinned Git blob hashes.
`assets/sim/vendor-lock.json` records all 27 dependency/model payload checksums;
`.gitattributes` preserves those exact bytes on Windows and Linux. Licenses and
attribution are in `assets/sim/NOTICE.txt` and the bundled license files.

The Node checks load the actual WASM/MJCF, validate meshes and motor mapping,
exercise zero gravity, free fall and floor contacts, reject invalid pose files,
and check missing/stale feedback and IMU attitude. They require Node.js, but
the deployed browser application does not.

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
