# Duck experiments

Keep each experiment on a focused branch so its behavior and hardware evidence
can be reviewed independently before proposing an upstream contribution.

| Experiment | First useful milestone | Needs |
| --- | --- | --- |
| GPU + matrix | Verified Adreno compute; live measured activity and stale-data indication | UNO Q only; hardware validation pending |
| Duck mood matrix | Blink, idle eyes, listening, dizzy and recovery animations driven by runtime events | UNO Q; some events initially simulated |
| 3D telemetry | Browser Duck showing measured and target joints, IMU tilt and timing | Exact XGO geometry/joint mapping; motors later |
| Physics simulation | Exact XGO dynamics and trained policies in a closed simulation loop | Physics engine and matching actuator model; distinct from a pose viewer |
| Vision | Detect a face or gesture, preview proposed head commands | Compatible camera; head motors later |
| ROS 2 bridge | Publish state and accept bounded high-level commands | Compatible ROS 2 host, timestamps and command ownership |
| Voice and sound | Recognize a command and animate a listening/speaking response | Microphone and speaker; local inference performance to measure |
| Web training | Launch, monitor and replay a training run through a web UI | Separate compatible training GPU; existing XGO RL workflow |

The firmware and trained policies remain matched to the XGO Duck hardware.
Graphics acceleration does not establish WebGPU availability or AI-framework
compatibility. Real hardware stays disarmed until assembly and calibration are
complete. Feature demos should record CPU/GPU resources and policy-loop timing.
