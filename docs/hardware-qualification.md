# Screen Duck hardware changes before printing

Run the shipped walking and get-up ONNX policies against the stock Duck and
against proposed rigid attachments. Duck Lab's MuJoCo model uses the runtime's
policy order and recovery state machine with approximate position actuators.
The stock scene comes from the RL revision in
[model-source.json](../assets/sim/model-source.json). It is the reference for
this comparison. Verify the V5 assembly and actual electronics against it
before making claims about the printed robot.

From the repository root, in a Python environment for this test:

```sh
python -m pip install -r python/requirements.txt mujoco==3.12.0
python -B tools/check-duck-hardware.py tools/duck-hardware-examples.json --variant rounded_guard
python -B tools/check-duck-hardware.py tools/duck-hardware-examples.json --trace-case bash > qualification.json
```

The second command screens all examples, including a deliberately unfavorable
box rail design. A nonzero exit means at least one case failed. JSON includes
metrics for every case regardless. Use `--trace-case` to include all 50 Hz
root poses, joint angles and foot contacts for one scenario per variant,
including failed runs. Traced cases include the module definitions and the
names of any modules in contact with the floor at each sample. These are
offline trials. They neither command hardware
nor measure UNO Q scheduler timing.

## Acceptance criteria

Each case runs on flat ground for 20 simulated seconds at 50 Hz.

| Case | Required behavior |
| --- | --- |
| Straight walk at 0.2 m/s | No fall, at least ten contacts per foot, and at least 1.5 m forward or 75% of stock distance, whichever is greater |
| Turning at ±0.6 rad/s | No fall, at least five contacts per foot, and at least 90° in the requested direction or 75% of stock rotation, whichever is greater |
| Sideways Bash at three gait phases | Stay upright and maintain forward progress, or recover as below |
| Front, back and both sideways drops | Enter recovery once, return to walking within 8 seconds, and move at least 0.75 m in the direction faced on standing with at least five contacts per foot |

All cases must end upright in walking mode. Tipped drops start with the
standing joint pose rotated 90° at stock standing height. They exercise
recovery entry and walking again. Additional ground poses, other floors, and
more push directions belong in a later robustness suite.

## Model the next print

The [example variants](../tools/duck-hardware-examples.json) describe each
attachment as a rigid body with mass in grams and a center relative to its
parent in metres. Use `size_m` for the full dimensions of a box or
`capsule_m` for a capsule's radius and total end-to-end length along local Z.
`floor_contact` defaults to true. Set it to false for enclosed items whose
mass matters but which cannot hit the floor. Each shape supplies its own
inertia. The examples use estimated masses and simplified shapes. They do not
contain the V5 PCB, actual brackets, fasteners, plugs, bump stops or cable
paths. The floor collision model does not test clearance against other links.

Measure the selected hub, cable exits and retention hardware, then model their
combined mass and position. Use the actual guard geometry to check that the
electronics and cable plugs stay within the protected envelope through a
roll. Include a mass and location range to catch changes in fit between
prints. Record the hardware revision, the geometry used and the policy
versions with the results.

For example, sweep the square hub's total payload mass and mounting height:

```sh
python -B tools/check-duck-hardware.py tools/duck-hardware-examples.json --variant retail_hub_square_55g --sweep-module usb_hub_tray_and_cables --mass-g 45 55 65 --z-offset-mm -3 0 3
```

## Train changes that need it

[Luwu's XGO Duck training repo](https://github.com/LuwuDynamics/xgoduck_rl)
uses PPO in mjlab with MuJoCo Warp on CUDA. It models the Feetech 1910
actuators with BAM and exports walking and stand-up checkpoints to ONNX.
Start with `Mjlab-Velocity-Flat-XgoDuck` and `Mjlab-StandUp-Flat-XgoDuck`
in that repo.
Carry the measured geometry and inertia into that training model. Run the
stock policy across the planned configurations first. If performance misses
these limits, try a geometry change, or train across the measured ranges for
attachment mass, position, contact friction and starting poses. A passive
accessory can use the same observation and action format. A new joint
participating in balance requires changes to the training and runtime policy
interfaces. Test the exported ONNX files with `--walk-policy` and
`--getup-policy`; the comparison still uses the shipped policy for stock.
Reserve fall poses and pushes that were not used to fit the new policy.

## Training app workflow

The first workflow is to edit a named variant, run the CLI, and load its
report in the browser. A training page can use the same variant fields for
shape, mass, parent link, placement and floor contact. Give each saved run
the source revision, exact variant, task, seed and policy hashes so someone
else can rerun it.

Host the page and run list on the UNO Q. The browser draws and scrubs traces
with WebGPU when available. Use the documented localhost tunnel or HTTPS for
a secure browser origin. Run the CUDA trainer in a local worker on a selected
NVIDIA laptop. Keep large checkpoints on that laptop and send progress and
compact replay files to the board. The page should show the chosen laptop,
its GPU, available memory, training progress and the qualification results.
Pair each worker explicitly. The board should send validated settings and
named actions such as train or cancel. Test a small batch of environments
before scaling up. Keep a separate deliberate step for deploying a checkpoint.

MuJoCo Warp and XGO Duck's training pipeline require a native CUDA
environment. A browser-only trainer would need its own physics and learning
implementation and a comparison against the existing results.
