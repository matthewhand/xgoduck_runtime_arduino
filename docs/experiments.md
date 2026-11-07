# Duck experiments

Keep each experiment on a focused branch so its behavior and hardware evidence
can be reviewed independently before proposing an upstream contribution.

| Experiment | First useful milestone | Needs |
| --- | --- | --- |
| GPU + matrix | Adreno proof passed; live GPU API/card deployed; matrix display confirmed; ~100 Hz feedback under GPU load | UNO Q only; motors and closed-loop policy timing later |
| Duck mood matrix | Blink, idle eyes, listening, dizzy and recovery animations driven by runtime events | UNO Q; some events initially simulated |
| 3D telemetry | Duck Lab has the actual CAD model, target/measured views, missing-data handling, and IMU roll/pitch | Deployed; real motors and IMU needed for hardware comparison |
| Physics simulation | Browser MuJoCo with XGO masses, collisions, gravity, drop/pause/step controls | Deployed sandbox; BAM actuation and closed-loop policy rollouts still pending |
| Vision | Detect a face or gesture, preview proposed head commands | Compatible camera; head motors later |
| ROS 2 bridge | Publish state and accept bounded high-level commands | Compatible ROS 2 host, timestamps and command ownership |
| Voice and sound | Recognize a command and animate a listening/speaking response | Microphone and speaker; local inference performance to measure |
| Web training | Launch, monitor and replay a training run through a web UI | Separate compatible training GPU; existing XGO RL workflow |

The firmware and trained policies remain matched to the XGO Duck hardware.
Graphics acceleration does not establish WebGPU availability or AI-framework
compatibility. Real hardware stays disarmed until assembly and calibration are
complete. Feature demos should record CPU/GPU resources and policy-loop timing.
