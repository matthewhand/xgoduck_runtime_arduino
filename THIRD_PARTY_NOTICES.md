# Third-party sources and notices

This document identifies upstream sources used by the runtime. It does not declare a license for the repository as a whole, its original additions, or its ONNX policies.

## Microduck

- Project: [Microduck](https://github.com/pollen-robotics/microduck), Pollen Robotics.
- License: Apache License 2.0; a copy is included in [LICENSES/Apache-2.0.txt](LICENSES/Apache-2.0.txt).
- Use: reference walking-policy deployment, observation/action processing, and IMU filtering adapted for XGO Duck.
- Local adaptations include the XGO Duck joint layout and signs, fixed walking home pose, policy selection and action filtering, QMI8658 body axes, MCU sample timestamps, and the Uno Q control/feedback protocol.

## Arduino RouterBridge and RPClite

- [Arduino_RouterBridge](https://github.com/arduino-libraries/Arduino_RouterBridge), pinned to 0.4.3.
- [Arduino_RPClite](https://github.com/arduino-libraries/Arduino_RPCLite), pinned to 0.3.1.
- Copyright (C) Arduino s.r.l. and/or its affiliated companies. RPClite also credits Lucio Rossi (eigen-value) in its package metadata.
- License: Mozilla Public License 2.0; a copy is included in [LICENSES/MPL-2.0.txt](LICENSES/MPL-2.0.txt).
- `tools/prepare-bridge.py`, `tools/bridge_patch.py`, and `tools/patches/` adapt portions of these libraries. Changes cover the Bridge thread stack, bounded MessagePack framing, bounded RPC waits, retry-safe initialization, UART initialization reuse, and late-response recovery. The helper applies these changes to the installed libraries and retains their original copyright and license headers.

## Browser simulation

- Three.js 0.187.0, Copyright 2010–2026 Three.js Authors, MIT license. Vendored builds and OrbitControls are in `assets/sim/vendor/three/`, including their `LICENSE`.
- MuJoCo 3.12.0, Google DeepMind and contributors, Apache License 2.0. The official single-threaded npm JavaScript/WASM distribution is in `assets/sim/vendor/mujoco/`, with its `LICENSE`.
- XGO Duck MJCF and CAD meshes from [LuwuDynamics/xgoduck_rl](https://github.com/LuwuDynamics/xgoduck_rl), commit `fa621fc77ad9a05d69da13270e86118bdd3603fe`, distributed by that repository under Apache License 2.0. The model, meshes, original scene and upstream license are in `assets/sim/model/`. The browser scene adds floor/simulation options and adapts the upstream Stand/Sit/Fold keyframes.
- `assets/sim/NOTICE.txt` provides browser-visible attribution. `assets/sim/model-source.json` and `assets/sim/vendor-lock.json` record immutable sources and checksums. The bundled compiled engines are required browser runtime assets.

## Other dependencies and policy assets

Arduino libraries are resolved from `sketch/sketch.yaml`; Python packages are listed in `python/requirements.txt`. Their respective upstream licenses continue to apply. Installed SDKs, dependencies, virtual environments, and compiled firmware are not vendored in this repository.

The `python/xgoduck_*.onnx` files are required runtime policy assets. This document does not grant or change their licensing terms. It also does not grant trademark rights in XGO Duck, Arduino, or Microduck.
