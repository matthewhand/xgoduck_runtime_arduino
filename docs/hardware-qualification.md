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
names of any modules in contact with the floor at each sample. These offline
trials do not command hardware or measure UNO Q scheduler timing.

Select **Replay** in Duck Lab and open the report. The timeline lets you
switch between stock and a variant at the same recorded time. The metrics
include failed trials, and the visualizer highlights accessory floor contacts.
To serve the replay page locally without the board, run
`python -m http.server 19528 --bind 127.0.0.1 --directory assets` and open
`http://127.0.0.1:19528/simulate.html?replay=1`.

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

### Protective backpack

The backpack covers the board face and edges. Its only viewing opening is
over the full 8 × 13 matrix. A shallow outward bevel gives the outer pixels
room to be seen slightly off-axis. Keep the rounded rails proud of the display
rim, fasteners and window. Transfer roll contact to the chassis through the
rails and mounts, with clearance for the shell to flex without touching the
PCB or its components.

Open **Hardware** in Duck Lab or add `?hardware=1` to `simulate.html` to
compare the open cut-out and translucent window. The mounting view shows
how the enclosure attaches. The mock-up uses the stock RL body and approximate
positions for the V5 board stack, cable exits and mounts. Its contact profile
differs from the attachment primitives used in the qualification examples.
The nominal opening at its narrowest is about 23 × 35 mm. The rails stand
about 2.5 mm past the shell face in the mock-up. Both dimensions need a fit
check on the assembled Duck.

In a provisional MuJoCo check, a 21 × 63 × 76 mm shell envelope and two
78 mm rounded rails extending 68 mm behind the trunk origin passed 9 of 10
cases at 22, 30 and 38 g added mass. At each mass the right-side drop
failed to recover. Moving the whole envelope 12 or 14 mm toward the trunk
passed all 10 cases at 30 g in simulation. The inset may overlap the board
or chassis in the physical build, so check fit before adopting it.

#### Check before printing the full enclosure

- Measure the assembled board stack, mounting points, tallest components and
  plug overmolds. Check the enclosure for the kit's board revision. Leave
  insertion room at the USB-C edge, route the cables with strain relief and
  a usable bend radius, and check the cable path through neck and leg travel.
  If using a captive power-button plunger, verify that it returns freely and
  leaves the switch released when the shell is tightened or pressed.
  [Luwu V5 hardware](https://github.com/LuwuDynamics/xgoduck_hardware/tree/4496fad52041db1cad36ded6cc49d942e037b4af/structure/V5_AUDIO_VIDEO_) ·
  [UNO Q pinout](https://docs.arduino.cc/resources/pinouts/ABX00162-full-pinout.pdf) ·
  [UNO Q STEP files](https://docs.arduino.cc/resources/models/ABX00162-step.zip)
- Print a small sample with the same aperture, bevel and window-to-LED gap
  as the proposed shell. Try an edge-pixel pattern and a normal animation
  head-on and slightly off-axis. The physical check should show all 104 pixels,
  with enough contrast to read the animation through the chosen window.
- For a one-piece multi-tool print, import the opaque shell and translucent
  window as two mating volumes in one slicer object and assign each to its
  own tool. Start with compatible opaque and translucent variants
  of the same polymer, such as PETG. Recess the window and give its perimeter
  a retaining step in the shell. Check the sliced seam, then inspect and press
  on a coupon to check for gaps, separation or excessive flex.
  [Multi-material modeling](https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135) ·
  [PETG material guide](https://help.prusa3d.com/article/petg_2059)
- Fit the prototype with power off. Verify that a slow hand roll touches the
  rails before the window, plug or switch. Compare UNO Q temperatures with
  the shell installed and removed under the same workload and ambient
  conditions. Weigh the complete enclosure and rerun walking and recovery
  qualification with its measured mass, center and contact surfaces.

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
