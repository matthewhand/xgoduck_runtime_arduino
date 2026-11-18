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

### Open-edge board shroud

On the stock V5 the UNO Q sits against the battery holder with its matrix
and Arduino headers facing the blue carrier. The carrier plugs into the
headers and has a 27.94 × 16.76 mm matrix opening in the V1.1 STEP. The white
UNO Q button is separate from the carrier power switch. [Luwu assembly photos](https://wiki.xgorobot.com/kb/the-xgo-series-robot/duck-guide-06?model=duck)

The current Duck Lab mock-up puts a removable faceplate outside the carrier.
Four posts leave the edges open for air and cable access. Its optional
translucent window aligns with the carrier opening. **Explode** separates
the faceplate and carrier to show the inner board. The mount positions and
component heights in this preview are approximate. Check finger clearance at
the UNO Q button with the carrier installed and all plugs seated. Upgrades
that need the occupied headers require a breakout or another interface.

### Wireless dock concept

Open [Dock Lab](../assets/simulate.html?dock=1) for the looping landing and
recovery replay. **Hardware → Dock** shows the static guide shapes and the
28 × 44 mm removable receiver cassette beside the matrix.

The tray is 6 mm high with a horizontal transmitter below the V5's back
bumpers. MuJoCo releases the model already tipped 81–90° backwards with motor
torque off. After 1.2 s, the stock get-up and walking policies have 8 s to
stand up and walk at least 100 mm. The shroud and receiver have an estimated
combined mass of 28 g including the bumpers. The geometric alignment screen
requires no cassette impact at the parked pose, an offset of at most 10 mm,
a tilt of at most 5°, and a positive coil gap of at most 8 mm. These bounds
are placeholders for the matched coil pair.

| Tray design | Aligned | Got up and walked | Both |
| --- | ---: | ---: | ---: |
| Bare deck | 4/7 | 0/7 | 0/7 |
| Low rails | 4/7 | 1/7 | 1/7 |
| Corner pads | 4/7 | 0/7 | 0/7 |
| Tall guides | 4/7 | 2/7 | 0/7 |
| Low rails with a head perch | 4/7 | 0/7 | 0/7 |
| Low rails with a 28 mm foot pad | 4/7 | 4/7 | 4/7 |
| Low rails with a 30° foot ramp | 4/7 | 1/7 | 1/7 |
| Low rails with a 45° foot ramp | 4/7 | 1/7 | 1/7 |
| Paired foot pads | 4/7 | 0/7 | 0/7 |
| Wide exit channel | 4/7 | 3/7 | 3/7 |

The centred foot-pad replay shows the left foot planting on the pad before
the Duck pushes out. The tested wedges saw foot contact on the centred entry
without a successful stand. The foot pad missed both angled approaches and
the steeper entry. The trials cover the last part of the fall and exit from
rest. A walking approach and controlled tip need their own trials.

Use **Overhead** to compare the exit paths. The distance readouts measure
trunk displacement from the parked pose to the transition back to walking.
The centred foot-pad run shifts 117 mm toward the foot end of the tray and
136 mm sideways. The nearly flat wide-channel run shifts 394 mm toward the
foot end and 9 mm sideways. The tested designs do not produce a straight
headward exit with the shipped controller.

The low chair uses a 45° backrest, a seat lip under the shroud and a 20 mm
footrest for both the stock feet and the passive four-wheel skate model. The
Duck settles on the lip and both feet or skates, with torque off. Each
footwear setup uses its own two-stage rise before handing off to the shipped
walking policy. The steeper 55° chair is included for comparison.

The chair trials start just clear of the backrest. They include centred
entries, ±8 mm sideways offsets, ±4° pitch changes, and paired yaw and
sideways offsets. Replay the two footwear configurations using **Design**.
**Peak side tilt** measures the body lean to either side from wake to exit.
The coil check measures geometry at rest. Its offset, tilt and gap limits
are the same as in the flat tray trials.

| Chair trial | Aligned | Rose and left | Both |
| --- | ---: | ---: | ---: |
| Low chair, stock feet | 4/7 | 6/7 | 3/7 |
| Low chair, skates | 4/7 | 5/7 | 3/7 |
| Steeper chair, stock feet | 7/7 | 3/7 | 3/7 |
| Steeper chair, skates | 0/7 | 3/7 | 0/7 |

Both low chair configurations passed the centred entry and the two 8 mm
sideways offsets. On the centred entry, peak side tilt dropped from 66.6°
to 0.1° on stock feet and from 70.2° to 1.6° on skates, compared with the flat
tray with a foot pad. The rise stages were tuned in simulation. Test them
again after measuring the built accessories and fitting the coil pair.

The next comparison starts upright outside the dock, with 10 combinations
of distance, speed, sideways offset and heading per footwear setup. Stock
feet back up under the walking policy. Skates start with a set backward
speed and roll with their standing pose held. When the trunk reaches the
seat zone, the model tries a lowering motion and settles with torque off.
A full cycle requires chair contact, the coil geometry screen and an exit
that continues at least 100 mm after recovery. An exit can still tumble
before recovery, so check peak side tilt and the replay as well.

| Approach trial | Reached the seat zone | Seated | Full cycles |
| --- | ---: | ---: | ---: |
| Low chair, feet / skates | 9/10 / 0/10 | 0/10 / 0/10 | 0/10 / 0/10 |
| Floor-level chair, feet / skates | 9/10 / 3/10 | 9/10 / 3/10 | 0/10 / 3/10 |
| Wide floor-level chair, feet / skates | 9/10 / 3/10 | 4/10 / 0/10 | 0/10 / 0/10 |
| Funnel chair, feet / skates | 9/10 / 1/10 | 9/10 / 1/10 | 1/10 / 0/10 |

The centred stock-foot funnel trial finishes with 0.1° of peak side tilt
on exit. The three completed floor-level skate trials pitch or roll through
a fall before recovering, with peak side tilt of 74–83°.

The floor-level version drops the chair 20 mm so wheels approach on the
room floor. The wider chair increases the seat lip from 90 mm to 115 mm and
adds flared shroud guides. The funnel adds 7 mm side rails with a 14° flare.
The plain floor-level chair and funnel use the same tuned lowering motion
for each footwear setup. The tests seed the starting heading directly.
A flat ArUco marker could give a camera the heading before the Duck reverses
or during the approach if the marker stays in view.
[OpenCV marker pose reference](https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html)

The shroud and dock carry the seated load. With the seated trunk fixed in
the kinematic model, extending the neck raises the bill by about 110–120 mm
in the low chair. That gives room to trigger a release lever. A catch that
retains the shroud would carry the load independently of the head. The head
reach check does not model catch forces or release reliability.

Recessed pads and spring contacts can use a second cassette with the same
outer mount as the wireless receiver. Keep the dock contacts de-energized
until seating is confirmed and route power through the approved charging
path. Match the measured mass, centre of mass and contact envelope between
the two backpack versions. In the low-chair mass screen, 7.5 g and 8 g
cassettes passed all three seated entries with both footwear types and the
same motions. The 8.5 g cassette passed on stock feet and failed on skates.
These are sensitivity trials with a rigid cassette. They exclude contact
spring forces, electrical mating and charging.
[Spring contact stroke and force example](https://www.mill-max.com/sites/default/files/external/assets/2020-09/pr697_-_omniball_spring-loaded_contacts_ms_tm.pdf)

The fixed-pad chair uses two contact pairs separated by insulation on the
load-bearing seat lip and shroud edge. It retains the simulated
cassette mass by moving 0.30 g from the package into the two shroud pads.
The pad readouts show the lowest normal force measured in the final 0.2 s
of settling. The mechanical screen requires at least 0.1 N on each pair
through that sample window. That threshold detects paired contact in the
simulation. Electrical continuity, resistance, heating and required pad
pressure need bench measurements before connecting a charger.

| Fixed pad approaches | Loaded both pads | Seated exits within 25° side tilt |
| --- | ---: | ---: |
| 45° with stock feet, 175 mm lowering point | 4/5 | 5/5 |
| 45° with standard skates, 165 mm lowering point | 5/5 | 0/5 |
| 40° with standard skates, 175 mm lowering point | 3/5 | 0/5 |
| 40° with wider skates, 175 mm lowering point | 5/5 | 0/5 |
| 50° with wider skates, 175 mm lowering point | 5/5 | 0/5 |

The wider standing pose increases the nominal wheel centre spacing from
63 mm to 82 mm. The lowering point is a simulated position trigger at the
marked line. A real approach sensor and a seating interlock still need
validation. Clearing the chair after fall recovery does not pass the side
tilt screen. The angle sweep kept the same floor and seat lip.

Export the 40° or 45° one-piece fit-check body with the CAD exporter. Its
underside is flat and the pad pockets and wire channels open upward. The
filled backing and pocket details are print geometry for checking fit.
The dynamics trial uses simplified collision shapes around the same lip
and backrest. Check the printed fit, contact finish and both pad readings
under load before electrical tests.

Each widened seat pad extends 8 mm toward the centre with the outer edge
fixed. After a 2.6 s settling window, both pads loaded in all 30 approaches
tested on the 45° chair with nominal height or a ±0.10 mm right-pad height
mismatch. The weakest pad across those runs carried 1.25 N. A 2 mm lateral
shroud shift still produced a skate approach that missed one pad.

The 40° chair also works with both footwear modes in the nominal approach
set. Stock feet use the walking approach and original rise. The skates
use the wider approach stance, two scripted rise stages, then the shipped
roller policy. All five skate approach trials with wider pads seated and
rolled 280–331 mm away with 0.27–0.30° peak side tilt. An audit at every
5 ms simulation step found no body contact with the floor during those
skate releases. These are simulated contacts and motions.

On that same 40° body, the five nominal feet approaches and all ten feet
approaches with a ±0.10 mm right-pad mismatch completed the cycle. The
skates completed nine of ten mismatched runs, with one failure when the
right pad was 0.10 mm high. The skate motion passed only two of five
independent starts from a preset seated pose. The Duck Lab replay shows
those separately from the cycles that start with a full approach.

The skate stress test ran 105 simulations of that 40° chair. Each approach
speed starts 320 mm back with five entries: centred, 8 mm to either side,
and those same offsets with 5° of yaw. A clean cycle loads both pads and
ends upright after at least 100 mm of travel on the wheels alone under the
roller policy.

| Initial coast speed | 100 mm rise handoff | 3 mm clearance handoff |
| --- | ---: | ---: |
| 0.18 m/s | 0/5 | 0/5 |
| 0.22 m/s | 1/5 | 1/5 |
| 0.25 m/s | 1/5 | 1/5 |
| 0.28 m/s | 5/5 | 5/5 |
| 0.30 m/s | 5/5 | 5/5 |
| 0.32 m/s | 3/5 | 5/5 |
| 0.36 m/s | 5/5 | 5/5 |

The alternative checks actual simulated collision bounds for at least 3 mm
of forward clearance from the chair. It gives an upright Duck within 10 mm
of clearing the chair up to 0.4 s more in the rise pose. At 0.32 m/s this
let two previously stalled releases roll another 160–161 mm after handoff.
This check uses the simulated pose and chair geometry. A physical controller
would need a way to estimate clearance.

At 0.18 m/s none reached the chair. At 0.22 and 0.25 m/s, loading both pads
could leave the knees or trunk in the wrong position to rise. The diagnostic
screen checked trunk attitude, knee tuck, and skate support. It matched
37 of the 45 clean loaded cycles and 1 of the 15 failed loaded cycles, so
the test records it without using it to gate a release. At wheel sliding
friction coefficients of 0.45 and 0.70, respectively 5/10 and 7/10 cycles
completed across 0.28 and 0.32 m/s. These coefficients are model inputs.
After backing in, all five simulated trials at 0.28 m/s still left
after a 10 s parked wait. Preset seating passed 3/5 at both 2.6 s and 10 s;
both angled preset starts failed at both wait times.

For slow skates, the speed-based trigger keeps the same two lowering stages.
At the 175 mm line the simulator checks backward speed. Below 0.06 m/s it
coasts another 22 mm before lowering. The centre 0.22 m/s run changed from
5° of rearward body pitch with reversed knee tuck to 46° of rearward pitch
with both knees tucked, then rolled 169 mm after the rise. Both comparisons
use the same clearance check from the previous test. Duck Lab alternates
between these recordings at `simulate.html?dock=1`.

| Seat lip and trigger | Clean cycles at 0.22–0.25 m/s | Clean cycles at 0.28–0.32 m/s |
| --- | ---: | ---: |
| Flat, fixed trigger | 2/10 | 15/15 |
| Flat, speed based | 10/10 | 15/15 |
| 20°, speed based | 10/10 | 10/15 |
| 25°, speed based | 10/10 | 6/15 |
| 30°, speed based | 9/10 | 7/15 |

The raised lip keeps the back edge at its original height and inclines
both contact pads. The 18 mm lip rises 6.6, 8.4 or 10.4 mm at the front,
respectively. All 15 faster runs loaded both pads at each angle, but the
raised versions prevented some rises from reaching the roll-away handoff.
Stock feet passed all five nominal runs at each angle with the original
feet controller. These tests favour the flat lip for shared use on feet
and skates with the tested rise sequence.

The speed trigger is still sensitive to arrival and grip. At four new speeds
with independently varied heading and offset, it improved from 5/16 to
7/16. At a tire sliding friction coefficient of 0.70, it completed 5/10
slow runs compared with 4/10 for the fixed trigger. With nominal grip and
a 10 s parked wait, it completed all 10 standard slow runs. At 0.18 m/s
none of the nominal coasts reached the trigger. The position and speed
used by the trigger are available directly in the simulation.

An upright Duck can start skating once it releases the chair. The contact
check uses simulated contacts in place of the clearance estimate from a
side projection. At the three faster test speeds, the flat seat stayed at
15/15 clean cycles. Raised lips improved from 10/15 to 12/15 at 20°, from
6/15 to 12/15 at 25°, and from 7/15 to 10/15 at 30°. The roller policy
propels the Duck by moving its legs, with passive wheels. The replay shows
when the policy starts and whether there was any subsequent chair contact.

A lateral recess with two 2 or 5 mm side ramps reduced the score to 2/14
for each shape, versus 10/14 for a flat seat at the same speeds and offsets.
The side ramps intercepted the shroud before the pads loaded in those runs.
A flush pocket for charging pads can preserve the flat surface.

The original two-stage sit actively leans the Duck backward. In the
centred 0.28 m/s skate replay, both skates were still on the floor when
trunk pitch reached 39° back, before the charging pads made contact.
Holding the achieved joint angles and fading torque over 0.10–0.35 s
left the feet and slow skate results at 9/9 and reduced the 0.28 m/s
skate result from 9/9 to 7/9 at all three fade durations.

The printable lip now has the same 18 × 90 mm outline as the original
fixture. A geometric audit checks the extra solid in the print against
sampled robot poses, preserving the pad pockets and wire channels. In the
original 50 runs it found one small remaining overlap of 0.24 mm³ with a
bumper on the 40° standard-skate yaw-right entry. This comparison does
not integrate impacts with the printed solid or model the actual materials.
The revised 40° print with wider pockets had no added-solid overlap in
any of the ten sampled trajectories for the combined skate profile.

```sh
python -B tools/check-floor-dock.py --browser-recordings
python -B tools/check-floor-dock.py --fixed-pad-recordings
python -B tools/check-floor-dock.py --contact-refinements
python -B tools/check-dock-robustness.py --recording assets/sim/contact-stress-recording.json
python -B tools/check-skate-lowering.py --recording assets/sim/skate-lowering-recording.json
python -B tools/check-chair-catch.py --recording assets/sim/chair-catch-recording.json --results chair-catch-results.json
python -B tools/check-chair-catch.py --brace-study --results chair-brace-results.json
python -B tools/check-fixed-pad-print.py
python -B tools/check-floor-dock.py --design "Floor-level chair"
python -B tools/check-floor-dock.py --cassette-mass-g 7.5 8 8.5
python -B tools/export-fixed-pad-chair.py 40 duck-chair-40deg-fit-check.stl --wider-pads
```

Print the pocket and fit the receiver after printing so it can be serviced.
Follow the selected module's allowed coil spacing and shielding. Confirm
coil alignment, output power, heat near the battery, and foreign-object
detection with the assembled robot and fasteners in place.
[Wireless Power Consortium integration guidance](https://www.wirelesspowerconsortium.com/knowledge-base/testing-and-certification/qi-components-and-subsystems/)

Luwu specifies an 8.4 V charger through DC5521 and requires the stock robot
to be off while charging. The receiver supplies power to a pack-compatible
charger. Confirm the pack label and its charge path before choosing the
charger or changing the wiring.
[Luwu charging instructions](https://wiki.xgorobot.com/kb/the-xgo-series-robot/duck-control?model=duck)

For automatic restart, use a controller powered independently of the Duck.
The dock confirms mechanical seating. The Duck releases torque once it is
supported and requests a clean Linux shutdown. The controller waits for a
verified shutdown indication, isolates the robot load, enables charging, and
checks charge status. It disables charging before restoring robot power.
The UNO Q boots automatically when power is supplied. A schedule or network
command received by the dock can request restart. Verify this sequence on the
actual kit with the approved charger before adding the wireless receiver.
[Arduino UNO Q datasheet, section 11.5](https://docs.arduino.cc/resources/datasheets/ABX00162-datasheet.pdf)

### Backward foot trip and skate step-over

Open `simulate.html?dock=1` to alternate the two centred 6 mm trials. The
orange bar is a physical collider on both entry and exit. Choose an offset
or the 12 mm bar under Entry. The centred entries also include the shorter
bar and clear-lane recordings under Design.

```sh
python -B tools/check-trip-entry.py --results trip-results.json --recording assets/sim/trip-entry-recording.json
```

The 40° chair has a flat seat and two fixed metal pad proxies. The walking
policy backs in at a commanded 0.16 m/s. The skate model starts coasting at
0.28 m/s. The foot approach deliberately bends backward and the skate
step-over uses successive left and right joint targets. Both use simulated
position to start the maneuver. These entries use scripted targets. The
shipped policies resume locomotion when the rise succeeds.

Each height has five deterministic entries with lateral offsets up to 8 mm
and headings up to 5°. The full bar is 220 mm wide and 8 mm deep at x = 140 mm.
A foot catch requires at least 5° of backward pitch and 0.1 N against the
approach face before the body touches the seat. A successful step must lift
and move all four tyres behind the bar while avoiding bar contact and finish
upright. The exit check requires both pad loads, a rise within 25° side tilt,
forward clearance of 100 mm past the bar by the trunk, and an upright final
pose. The roller exit also requires a wheels-only departure without fixture
recontact during powered skating.

| Setup | 6 mm, both pads / clean exits | 12 mm, both pads / clean exits |
| --- | --- | --- |
| Feet, lean into full bar | 4/5 · 0/5 | 5/5 · 0/5 |
| Skates, active step over full bar | 0/5 · 0/5 | 0/5 · 0/5 |
| Skates, coast beside 60 mm central stop | 5/5 · 4/5 | 1/5 · 1/5 |

The feet met the loaded-catch criterion on 4/5 and 3/5 entries, respectively.
In the centred 6 mm trial each pad carried 1.80 N, but the subsequent rise
and walk veered sideways. The centred skate step lifted the left skate
1.9 mm and the right 41.0 mm, struck the bar, and missed the chair. The same
step also missed on a clear floor. With the usual lean and a clear lane,
both footwear configurations completed all five entries. Pad loads represent
mechanical seating. Current delivery, charging and wake-up require bench tests.

### Clear-lane qualification

Run the 40° chair with a flat seat, widened pads and the fixed 175 mm
lowering trigger. Each of 100 stratified input rows is used once per footwear
type (seed 20261118). Vary lateral offset within ±15 mm, heading within ±7°,
floor and footwear sliding friction from 0.70 to 1.15, and receiver mass from
6 to 14 g. Feet use backward walking commands of 0.12–0.20 m/s. Skates start
with a backward coast of 0.22–0.34 m/s. Both start 320 mm from the origin
and settle for 2.6 s. The shell and bumpers add a fixed 20 g.

```sh
python -B tools/check-clear-lane.py --results clear-lane-results.json --recording assets/sim/clear-lane-recording.json
```

The clean cycle uses the previous forward exit boundary (trunk x > 240 mm),
the loaded-pad and rise checks, and the wheels-only release check on skates.
After locomotion resumes, reject a recorded loss of upright balance or a
return to recovery, including a later successful stand-up.

| Footwear | Lowering point | Seated | Both pads sustained load | Clean forward exit | Target |
| --- | ---: | ---: | ---: | ---: | ---: |
| Feet | 100 | 94 | 64 | 54 | 95 |
| Skates | 100 | 89 | 64 | 49 | 95 |

Duck Lab loops the first pass and the first example of the most frequent
failure for each footwear type. The two failed clips show loss of sustained
load on both pads. Test revised seating or lowering triggers on these same
inputs for comparison and use a fresh seed for independent qualification.

### Turning to reverse into the chair

```sh
python -B tools/check-turn-seek.py --recording assets/sim/turn-seek-recording.json --results skate-turns.json
```

Duck Lab's **Skate turnaround trials** case loops four MuJoCo recordings using
the shipped roller policy. Each method and direction has nine starts from
rest at x = 600 mm, combining headings of 165°, 175° or 179° from the target
with lateral offsets of −20, 0 or +20 mm. The arc starts with a 0.7 s forward
command before requesting yaw. Steering uses simulator pose relative to the
chair. The teal trace shows the recorded trajectory.

The duck must turn in the requested direction, reach ±9° of the target,
and stay within that band at or below 0.12 m/s for 0.4 s before reversing.
The anticlockwise arc reached and held the heading in 9/9 and met the
combined handoff in 0/9. The clockwise arc and both standing pivots reached
the target in 0/9 each. The recordings show the run closest to handoff
in each group, ranked by clean exit, reverse handoff, acquisition and peak
signed rotation. The **Turn around and seek backwards** case includes two
bare-foot examples which completed the entire cycle and a skate pivot.
The simulation measures are separate from the earlier 200 clear-lane trials
that started with the duck already facing away from the chair.

### Earlier protective backpack trials

The backpack covers the board face and edges. Its only viewing opening is
over the full 8 × 13 matrix. A shallow outward bevel gives the outer pixels
room to be seen slightly off-axis. Keep the rounded rails proud of the display
rim, fasteners and window. Transfer roll contact to the chassis through the
rails and mounts, with clearance for the shell to flex without touching the
PCB or its components.

These tests use simplified envelopes for the earlier shell, with a nominal
23 × 35 mm display opening and 2.5 mm rail clearance beyond the face.
The shroud preview above needs its own contact and recovery check.

In a provisional MuJoCo check, a 21 × 63 × 76 mm shell envelope and two
78 mm rounded rails extending 68 mm behind the trunk origin passed 9 of 10
cases at 22, 30 and 38 g added mass. At each mass the right-side drop
failed to recover. Moving the whole envelope 12 or 14 mm toward the trunk
passed all 10 cases at 30 g in simulation.

The 12 mm inset does not fit the stock V5 mounting geometry. In the pinned
[V5 3MF project](https://github.com/LuwuDynamics/xgoduck_hardware/blob/4496fad52041db1cad36ded6cc49d942e037b4af/3DManufacturingFormat/xgoduckV5.3mf),
`BATTERY`, `ENCLOSURE_FOR_V1`, and `ENCLOSURE_FOR_V1P1` share an assembly
group. The clearance check used the saved part transforms and sampled mesh
intersections along the depth axis on a 0.5 mm lateral and vertical grid.
The stock CAD already shows
0.68 mm of local overlap at an upper mating tab. Shifting either enclosure
12 mm toward the battery holder increases that overlap to 12.68 mm at the
same tab. The 14 mm shift also interferes. This checks the stock holder and
enclosure mount surfaces. A redesigned mount or enclosure needs a new fit
check before using an inset in the walking and get-up trials.

The browser mock-up places the protective face 15.5 mm behind its carrier
plane. That distance describes the shroud and standoffs in the preview.
For a shroud that slides on from above, use a rail adapter on the V5
battery-holder interface or a replacement enclosure with integrated rails.
Keep the UNO Q and the mated carrier fixed while the outer shroud slides.
Check the available insertion path against the upper tab and plugs, and
place the dock contact pads on the rigid shroud with a load path to the
chassis.

The top-entry gauge is 8 mm tall with a 61.79 mm clear width. It leaves
1 mm at either side and at the rear of the stock V1.1 enclosure in the
pinned CAD. An outer shroud following the gauge adds 3.2 mm behind the
enclosure. A slim replacement needs to put its rails within the existing
depth. The battery holder's inboard pilot pattern is 47.104 × 33.400 mm
and can be checked as a structural mounting datum. The gauge clears the
printed part meshes in a vertical pass. Installed screws, plugs, cable
bends and head travel require an assembled check.
[Luwu V5 assembly steps 23–25](https://wiki.xgorobot.com/kb/the-xgo-series-robot/duck-guide-06?model=duck)

The cushioned version keeps the same rear envelope and stock mounting
position of the earlier shell. Its rounded skids sit over proposed TPU pads.
The earlier window was 1.4 mm thick and set back 4.3 mm from the skid tips.
Retain the pads mechanically so a skid can transfer load to the chassis
mounts. The opaque shell and translucent insert can form one multi-tool
print. Check the fit of the skid and pad separately.
[Flexible filament guidance](https://help.prusa3d.com/article/flexible-materials_2057)

The `v5_cushioned_guard_30g` example models the shell and skids as rigid
shapes with 30 g of added mass. It passed nine of ten scenarios and walked
2.44 m in 20 seconds versus 2.59 m for stock. The right-side fall failed
to recover across the 26–36 g range tested. At 34 and 36 g, the late Bash
also missed the forward-distance gate. The trial does not model pad flex or
measure impact forces on the electronics. Use qualification replay to compare
the recorded right-side fall, and weigh the actual assembly before applying
the result to a print.

#### Check before printing the full enclosure

- Measure the assembled board stack, mounting points, tallest components and
  plug overmolds. Check the enclosure for the kit's board revision. Leave
  insertion room at the USB-C edge, route the cables with strain relief and
  a usable bend radius, and check the cable path through neck and leg travel.
  Verify finger access to the white UNO Q button and clearance for plug
  insertion, removal and strain relief with the faceplate fitted.
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
  skids before the window, plug or switch. Check that pads stay captured and
  the skids have clearance from the board and window through pad compression.
  Compare UNO Q temperatures with the shell installed and removed under the same workload and ambient
  conditions. Weigh the complete enclosure and rerun walking and recovery
  qualification with its measured mass, center and contact surfaces.

For example, sweep the square hub's total payload mass and mounting height:

```sh
python -B tools/check-duck-hardware.py tools/duck-hardware-examples.json --variant retail_hub_square_55g --sweep-module usb_hub_tray_and_cables --mass-g 45 55 65 --z-offset-mm -3 0 3
```

## First footwear trials

The [footwear examples](../tools/duck-footwear-examples.json) are rigid
envelopes attached to the stock ankles. With the shipped policies on a flat
floor, the light heel skids passed all ten cases at 4 g total and walked
2.35 m in 20 s versus 2.59 m stock. Heel and toe bumpers passed nine cases,
shallow rocker soles passed six, and wide soles passed one. The results
include turning, falls, and forward travel after standing up.

```sh
python -B tools/check-duck-hardware.py tools/duck-footwear-examples.json --trace-case right > footwear.json
```

Keep the first grass sole close to the original footprint and try shallow,
rounded tread with a removable pad. Verify grip, sinking, and stability on
an uneven test bed before field use. In a roof space, use a supported path
above the insulation. Test an equivalent board path at ground level before
considering the actual site.
[SafeWork NSW ceiling-space guidance](https://www.safework.nsw.gov.au/__data/assets/pdf_file/0008/965861/Guide-to-solar-safe-installation.pdf)

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

## V5 Mods preview and loaded policies

Open the Mods tab to compare the stock V1.1 enclosure with the top-entry fixed-pad charging cover and its integral housing rails. The optional roller skates change the selected loadout. These controls change the local 3D preview. A separate physics qualification run is needed for each assembled layout.

The CAD preview uses the V1.1 enclosure, the added rail volume, and the seated cover generated at 0.25 mm groove clearance. The housing is simplified for display. In the MuJoCo trunk frame, the generator's print coordinates map to millimetres as `(z - 57.33226, x - 0.00628, y - 39.25512)`. The nominal added plastic mass uses 1.24 g/cm³ and solid parts. The preview also carries the robot-side wiring specified in `assets/sim/contact-harness.json`. That file is copied from the V5 hardware fork. Its nominal 30.2 g increase includes 15.4 g of printed plastic. The 19.2–44.5 g planning interval covers both the housing change and the proposed harness. With its connector seated there are six insulated lead segments, two contact strips, two disconnect halves, an isolator, a charge plug, two lead restraints and a tray allowance. The DC1 endpoint is an approximate envelope. Confirm its registration and weigh the build before defining the final training configuration.

The teeth and tusks use distinct layout IDs. With stock feet and a matching loaded policy pair, the small teeth can be a transfer candidate pending walk and get-up tests. A checked fit or a similar mass alone cannot establish policy transfer. Flush cosmetic printing in the original polymer uses the same mass assumption. A relief design, a different polymer or changed print settings need separate mass accounting.

For each qualified training configuration, add the exact SHA-256 digests of its motion and get-up ONNX models to `TRAINED_LAYOUTS` in `assets/sim/mod-policy.mjs`. Use a new layout identifier for a different revision or payload. When reusing an existing pair after a successful transfer test, record its qualification artifact in `transferReport` on that layout. The board reports `loaded_policy_sha256` by role from the sessions successfully loaded by the controller. Missing telemetry, path-only sessions with external weights, and the presence of a familiar filename cannot establish a match. The active filename is shown separately because a loaded get-up policy can be idle until a fall.

### Passive tail backpack

In Mods, the articulated tail uses the two fixed rails in place of the charging assembly. The CAD drawing separates the mount, proximal link and distal link. The pivots are registered to the V5 enclosure datums. The mass estimate includes the enclosure change and both joint pins, and excludes an optional NFC tag.

Open `simulate.html?mods=1&tail=1&trial=1` for the recorded stock-feet trial. Playback interpolates the MuJoCo floating-base pose, fourteen named robot joints and both tail hinge angles from one timeline. The leg policy drives the robot and the tail moves passively. The skates and head accessories remain available to inspect statically. Their mass layouts require separate trials. Selecting the tail uses a separate model profile from both the stock and wired layouts.
