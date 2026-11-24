# Duck Lab: browser simulation and live view

Open **Duck Lab** from the runtime's navigation, or visit
`http://<board-ip>:9527/simulate.html`. It opens **Build & Test**, with board
tools, the recorded stock walk and four get-ups, and the two V1.1 backpack
fit-test plates in print order. The stock replays run without a connected
board. **Run live simulation** opens the interactive walking simulation on the
UNO Q.

Tick the physical checklist after checking rail retention, cable clearance,
servo mapping, IMU orientation, stock walking and getting back up. Duck Lab
saves checked timestamps and the installed release in this browser. The live
servo count and IMU status are available alongside the checklist.

**Bench diagnostics** reports controller feedback, torque, exact detected and
missing servo IDs, voltage feedback, and IMU initialization counters. Sensor
vectors and tilt require fresh feedback and an online IMU. Export a JSON
snapshot before changing the bench setup, then open it with **Compare saved
snapshot** to see its readings beside live telemetry. The comparison stays in
the browser and the page only reads from the controller.

After a live simulation, choose **Export trial** in the simulation or **Export
last trial** on Build & Test. The JSON file includes the run ID and release,
board CPU and GPU samples, simulation misses, the change in the board's Linux
missed-slot counter, and recovery times when there was a fall or a push. It also
includes the browser's current physical checklist. The UNO Q retains the most
recent finished trial, including a trial stopped early. Missing measurements
are `null`.

For the real Duck, open **Physical trial** from Build & Test. The recorder
requires all 15 servos, fresh IMU feedback, and torque off at the start. Select
**Start capture**, then use **Walk / get up** from Control. Use **Torque off**
to release the motors. The capture ends when the armed stock policy ends,
when you save it, or at 60 seconds. The recorder samples telemetry on the UNO Q
while the browser may disconnect. The physical and simulation reports are
retained separately and can be exported from Build & Test.

The comparison shows peak board loads, missed Linux slots, and elapsed time
from a controller-detected fall to return to the walk policy. The latter uses
phase timestamps from the controller. Verify actual standing and walking in
the physical checklist. The real Duck has no measured translation in this report.

Use **Experimental** in the footer to reach the full simulation workspace,
attachments, docking, and vision studies. Existing mode links such as
`simulate.html?dock=1`, `simulate.html?mods=1` and `simulate.html?demo=1`
still open their corresponding views. To open the original Pose workspace
directly, use `simulate.html?lab=1`.

On the UNO Q Wi-Fi deployment, `/experiments` serves the working simulator
and its assets. The root simulator and companion page URLs forward to that
same copy, including their query parameters and fragment. The legacy root
`/simulate.html?demo=1` bookmark keeps its older pond demo on boards with that
installation; open the Experimental page for the current Demo circuit.

## Deploy Build & Test over Wi-Fi

Run the following from a checkout with the release committed. The board must
already run the XGO Duck app and have the Duck Lab experiments installed. Use
its saved SSH alias with the host key pinned. Set `--address` to its current Wi-Fi
address when the alias points to an older address.

```sh
python tools/check-build-plates.py assets/sim
node tools/check-browser-sim.mjs
python tools/deploy-duck-lab.py --ref HEAD --host uno-q-duck --address <board-ip>
```

Use `--output build-test-release.zip` to keep the staged bundle. The deployment
checks file hashes and merges the board-tool changes with the installed Python
files using the release's parent as the base. If the backend changes span more
than one commit, pass the commit before those changes as `--base`. A merge
conflict stops the deployment before installation. The installed commit and
hashes are available at `/experiments/build-test-release.json`. The command also
prints the board-side backup directory and identifies any changed Python files.

If Python files changed, confirm torque is already off and no simulation is
running before restarting the XGO Duck app. Check the Build & Test page, both
3MF downloads, the stock replay, and live board status after the restart.

To restore the previous release, use SSH to run the installer saved next to
the reported `backup` directory on the board:

```sh
flock -n "$HOME/.duck-lab-deploy/build-test.lock" python3 -B <release-dir>/install.py --restore <release-dir>/backup
```

Restart the app again if the rollback restored Python files.

For WebGPU, use a browser with WebGPU support and a secure origin. The USB
forward is a convenient localhost origin:

```sh
adb forward tcp:19527 tcp:9527
```

Open `http://127.0.0.1:19527/simulate.html` on that PC. Recreate the forward after
reconnecting USB. Plain HTTP at the board's Wi-Fi address uses the WebGL 2
fallback. The renderer badge reports the backend actually initialized.

## Roller skates and exploded views

Open **Skates** or add `?skates=1` to try the upstream roller MJCF with four
passive wheels. **Roll forward** holds the skate stance with browser position
actuators and gives the Duck a forward push. **Explode wheels** pauses the
simulation and separates the four wheels along their axles. Drag to orbit and
use **Assemble wheels** or **Play** to put them back. Demo includes a skate
glide each lap. Its walking and beacon trials require the UNO Q worker.

The skate controls include 450 mm and 600 mm tiles with 5 mm recessed grout,
a carpet approximation with added axle drag, and 6 mm and 12 mm thresholds.
**Run tow test** compares a rigid mouth mount with a low chassis hitch.
Both use an elastic simulated line and a 1.5 N breakaway threshold.
That value is a simulation setting. The model has no actuated jaw and
cannot establish the grip strength of an actual print.

This browser view uses the upstream roller model without actuator backlash.
For training, use Luwu's full mjlab model with BAM and use
`Mjlab-Velocity-Swizzle-XgoDuck` for skating and
`Mjlab-RollerStandUp-Flat-XgoDuck` for recovery. The registration and asset
source are pinned in [Luwu's RL repository](https://github.com/LuwuDynamics/xgoduck_rl/blob/a4c78aacd5eaa724cf246fe12d24bfe1e837fa50/src/mjlab_microduck/tasks/__init__.py).
Check wheel and floor friction, rolling resistance, installed mass, and
recovery from falls on both sides when adapting the tasks. Keep the four
wheel joints passive and outside the 14 servo action channels.
For a sideways obstacle step, train against varied threshold heights, approach
angles and friction. Check wheel clearance, stable landing, and resuming a
forward roll on terrain and positions excluded from training.

In **Hardware**, **Explode** separates the shroud, blue expansion board and
UNO Q so you can see the display cut-outs and where the boards mate.

## Optional Wi-Fi reboot page

After installation, bookmark `http://<board-wifi-ip>:9528/`. Open that address
directly over Wi-Fi and click **Confirm reboot**. A successful request schedules
a full UNO Q restart in about five seconds. Stop any active trial and turn motor
torque off first. If the Wi-Fi address changes after reboot, look up the board's
current address before reopening Duck Lab.

This is an unauthenticated development tool. **Any client that can reach port
9528 can trigger a reboot.** Use it only on a trusted network and do not expose
it outside that network. The page requires a same-origin POST, with a short
confirmation body and a cooldown for repeated requests. The host service binds
to `wlan0`, follows DHCP address changes, and runs separately from App Lab and
USB. It requires Python 3 and a systemd version with scheduled reboot support
(`systemctl --help` should list `--when`).

To opt in, run these commands from the checkout on the UNO Q Linux host:

```sh
sudo visudo -f /etc/sudoers.d/xgo-wifi-reboot
```

Add this one rule, with no wildcard arguments:

```sudoers
arduino ALL=(root) NOPASSWD: /usr/bin/systemctl --when=+5s reboot
```

Then install the unprivileged service and its script:

```sh
sudo install -D -o root -g root -m 0644 tools/wifi-reboot.py /usr/local/lib/xgo-duck/wifi-reboot.py
sudo install -o root -g root -m 0644 tools/xgo-wifi-reboot.service /etc/systemd/system/xgo-wifi-reboot.service
sudo systemctl daemon-reload
sudo systemctl enable --now xgo-wifi-reboot.service
```

To check the installation without rebooting, open the confirmation page without
submitting it. From the `arduino` account, run `sudo -n -l` and look for
`NOPASSWD: /usr/bin/systemctl --when\=+5s reboot` in the output. The backslash
is how sudo displays the equals sign. Check
`journalctl -u xgo-wifi-reboot.service` if the page is unavailable.
If USB or App Lab is down but SSH is still reachable, an interactive
`sudo systemctl reboot` over SSH remains an alternative.

To remove the POC, disable and stop `xgo-wifi-reboot.service`, remove the unit,
script, and `/etc/sudoers.d/xgo-wifi-reboot`, then run
`sudo systemctl daemon-reload`.

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
The walk demonstrates Poke, Nudge, and Bash. The beacon hunt alternates
north and south passages on successive laps. The policy views retain the
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

## Grove camera comparison

Open [Camera replay](../assets/camera-replay.html) in Duck Lab. In desktop Chrome or Edge on HTTPS or localhost, connect the Grove Vision AI V2 to that computer by USB data cable. Choose **Connect Grove**, select the camera's serial port, then choose **Record up to 20 s**. Capture uses the camera's existing SSCMA firmware and stops after 60 frames or at the time limit. Frames are timestamped on receipt. [Seeed SSCMA sensor sampling protocol](https://github.com/Seeed-Studio/SSCMA-Micro/blob/main/docs/protocol/at-protocol-en_US.md#sample-data-from-current-sensor)

You can also open a Duck Lab JSON recording, up to 60 JPEG or PNG stills, or one browser-decodable video. Video analysis samples up to 60 frames from the clip. Footage and labels stay in the browser unless you save the recording or export the results.

Both detectors run on each selected frame. The MLP sees an aspect-preserving 96 × 72 view and verifies the printed ID using camera detail if needed. The CAD fit scans for known markers and projects a dock box using the print geometry. Both use frame detail capped at 768 px on the long edge. In the comparison view, label visible docks and absent docks. Add a box to count a detection as correctly localized when its intersection-over-union is at least 0.50. The totals exclude unlabelled frames. The review filter can jump through disagreements, misses, incorrect boxes and false alarms. **Load synthetic example** exercises the comparison using the lab's generated imagery.

**Loop MLP misses** plays the labelled synthetic frames rejected by the MLP and shows its score, rejection stage and proposed box. The fallback accepts the first verified MLP result and uses the CAD result when the MLP rejects the frame. Accepted MLP boxes can still be inaccurate. The standalone CAD column shows how the geometric fit performed on those frames.

Run `python -B tools/check-dock-marker.py` for the original synthetic sweep and add `--seed 762400` for the repeat sweep. Each has 48 frames per condition. At 50% box overlap, the fallback correctly localized 42/48 and 40/48 fully marked docks, compared with 40/48 and 35/48 for the MLP with camera detail. CAD alone localized 48/48 in both runs. The fallback accepted 0/96 look-alikes across the two runs. The browser loop uses JPEG frames resized from the detail atlas. The sweep uses the generator's native low-resolution RGB view plus the high-resolution sensor frame.

**Loop wrong boxes** plays the paired results for the 14 fully marked cases where MLP-first accepted a box with less than 50% overlap. CAD-first takes the CAD box when a verified fit is available and uses the verified MLP result on a CAD rejection. Across both sweeps, CAD-first localized 96/96 fully marked and 73/96 partly obscured docks. It accepted 0/96 look-alikes. The loop draws the original run's box coordinates over JPEG previews of the same frames. Regenerate the replay with `python -B tools/check-dock-marker.py --also-seed 762400 --export-order-loop assets/sim/dock-order-replay.json`.

**Loop occlusion misses** compares CAD-first with a second marker scan on the 23 partly obscured docks it missed. The second scan runs when both original detectors reject the frame. It tries darker segmentation thresholds and allows seven white-border samples to fail the contrast check. It still checks at least 15 of 16 ink-ring samples, all nine exact payload bits, and the CAD fit. It improved partial-occlusion localization from 73/96 to 76/96 in the two original sweeps and from 41/48 to 42/48 on seed 913100. Both versions accepted 0/144 look-alikes across the three sweeps. Regenerate the loop with `python -B tools/check-dock-marker.py --also-seed 762400 --export-occlusion-loop assets/sim/dock-occlusion-replay.json`.
