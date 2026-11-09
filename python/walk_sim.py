"""Headless rollout of the shipped walking policy, independent of the MCU."""
import argparse
from collections import deque
import json
import math
import os
from pathlib import Path
import sys
import time

from search_mission import ARENAS, MISSION_S, SearchMission

STEP_S = 0.005
SUBSTEPS = 4
SLOT_S = STEP_S * SUBSTEPS
RUN_S = 20
PUSH_SPEEDS = {'poke': 0.12, 'nudge': 0.30, 'bash': 0.48}
RECOVERY_TILT_DEG = 15
RECOVERY_HOLD_S = 0.5
MODEL = Path(__file__).resolve().parent.parent / 'assets/sim/model/scene_walk.xml'
JOINT_IDS = (10, 11, 12, 13, 14, 30, 31, 32, 33, 20, 21, 22, 23, 24)
JOINT_NAMES = (
    'left_hip_yaw', 'left_hip_roll', 'left_hip_pitch', 'left_knee', 'left_ankle',
    'neck_pitch', 'head_pitch', 'head_yaw', 'head_roll',
    'right_hip_yaw', 'right_hip_roll', 'right_hip_pitch', 'right_knee', 'right_ankle',
)
OBS_NAMES = 'base_ang_vel,projected_gravity,joint_pos,joint_vel,actions,command,head_command,body_command'


class WalkSimulation:
    def __init__(self, vx, yaw, arena=None):
        import mujoco as mj
        import numpy as np
        from policy import Policy

        self.mj, self.np = mj, np
        self.mission = SearchMission(mj, np, MODEL, arena) if arena else None
        self.model = model = self.mission.model if self.mission else mj.MjModel.from_xml_path(str(MODEL))
        model.opt.timestep = STEP_S
        self.data = data = mj.MjData(model)
        self.policy = policy = Policy()
        ok, message = policy.load(use_model_home=True)
        if not ok:
            raise ValueError(message)
        metadata = policy.session.get_modelmeta().custom_metadata_map
        if tuple(metadata.get('joint_names', '').split(',')) != JOINT_NAMES:
            raise ValueError('Walking policy has an unexpected joint order')
        if tuple(metadata.get('observation_names', '').split(',')) != tuple(OBS_NAMES.split(',')):
            raise ValueError('Walking policy has an unexpected observation order')
        self.scale = float(metadata['action_scale'])
        if not math.isfinite(self.scale) or self.scale <= 0:
            raise ValueError('Walking policy has an invalid action scale')
        self.home = np.asarray(metadata['default_joint_pos'].split(','), dtype=np.float32)
        self.obs = np.zeros((1, 61), dtype=np.float32)
        self.obs[0, 48:51] = (vx, 0, yaw)
        self.input = {policy.in_name: self.obs}
        self.qpos = [int(model.joint(name).qposadr[0]) for name in JOINT_NAMES]
        self.qvel = [int(model.joint(name).dofadr[0]) for name in JOINT_NAMES]
        self.actuators = [model.actuator(name).id for name in JOINT_NAMES]
        self.trunk = model.body('trunk_base').id
        root_joint = model.joint('trunk_base_freejoint')
        self.root = int(root_joint.qposadr[0])
        self.root_dof = int(root_joint.dofadr[0])
        gyro = int(model.sensor('imu_ang_vel').adr[0])
        self.gyro = slice(gyro, gyro + 3)
        mj.mj_resetDataKeyframe(model, data, model.key('STAND').id)
        data.qpos[self.qpos] = self.home
        data.ctrl[self.actuators] = self.home
        mj.mj_forward(model, data)
        self.path_m = 0.0
        self.feet = {model.geom(f'{side}_foot_collision').id: side for side in ('left', 'right')}
        self.floor = model.geom('floor').id
        self.last_contact = set()
        self.footfalls = dict(left=0, right=0)
        self.inference_ms = 0.0
        self.push = None
        self.settled_since = None

    def apply_push(self, kind):
        # Use the trunk heading to add a world-frame sideways velocity impulse.
        w, x, y, z = self.data.qpos[self.root + 3:self.root + 7]
        heading = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
        speed = PUSH_SPEEDS[kind]
        self.data.qvel[self.root_dof] -= speed * math.sin(heading)
        self.data.qvel[self.root_dof + 1] += speed * math.cos(heading)
        self.push = dict(kind=kind, time_s=round(self.data.time, 3), peak_tilt_deg=0.0, recovery_s=None)
        self.settled_since = None

    def tick(self):
        d, obs = self.data, self.obs[0]
        # Refresh body frame and gyro at the integrated pose before observing it.
        self.mj.mj_forward(self.model, d)
        if self.mission:
            vx, yaw = self.mission.steer(d, self.root)
            obs[48:51] = (vx, 0, yaw)
            if self.mission.found:
                return False
        obs[:3] = d.sensordata[self.gyro]
        obs[3:6] = -d.xmat[self.trunk, 6:9]
        obs[6:20] = d.qpos[self.qpos] - self.home
        obs[20:34] = d.qvel[self.qvel]
        start = time.perf_counter()
        action = self.policy.session.run(None, self.input)[0][0]
        self.inference_ms = (time.perf_counter() - start) * 1000
        if not self.np.isfinite(action).all():
            raise ValueError('Walking policy emitted a non-finite action')
        obs[34:48] = action
        d.ctrl[self.actuators] = self.home + action * self.scale
        old_xy = d.qpos[self.root:self.root + 2].copy()
        for _ in range(SUBSTEPS):
            self.mj.mj_step(self.model, d)
            contacts = set()
            for contact in d.contact:
                a, b = contact.geom
                foot = self.feet.get(b if a == self.floor else a) if self.floor in (a, b) else None
                if foot:
                    contacts.add(foot)
            for foot in contacts - self.last_contact:
                self.footfalls[foot] += 1
            self.last_contact = contacts
        self.path_m += float(self.np.linalg.norm(d.qpos[self.root:self.root + 2] - old_xy))
        if not self.np.isfinite(d.qpos).all():
            raise ValueError('Walking simulation emitted a non-finite pose')
        # Terminate a fallen trial instead of accumulating misleading floor motion.
        q = d.qpos[self.root:self.root + 7]
        up = 1 - 2 * (q[4] ** 2 + q[5] ** 2)
        if self.push and self.push['recovery_s'] is None:
            tilt = math.degrees(math.acos(max(-1.0, min(1.0, up))))
            self.push['peak_tilt_deg'] = max(self.push['peak_tilt_deg'], round(tilt, 1))
            if tilt > RECOVERY_TILT_DEG or q[2] < 0.10:
                self.settled_since = None
            elif self.settled_since is None:
                self.settled_since = d.time
            elif d.time - self.settled_since >= RECOVERY_HOLD_S - 1e-9:
                self.push['recovery_s'] = round(d.time - self.push['time_s'], 3)
        return q[2] < 0.06 or up < 0.45

    def snapshot(self):
        d = self.data
        sample = dict(time_s=round(d.time, 3), root=d.qpos[self.root:self.root + 7].tolist(),
                      joints_rad=dict(zip(JOINT_IDS, d.qpos[self.qpos].tolist())),
                      contacts=d.ncon, footfalls=self.footfalls, path_m=round(self.path_m, 3))
        if self.mission:
            sample['mission'] = self.mission.snapshot()
        if self.push:
            sample['push'] = self.push.copy()
        return sample


def publish(sample):
    print(json.dumps(sample, separators=(',', ':'), allow_nan=False), flush=True)


def run(sim, push_fd=None):
    slots = missed = 0
    run_slots = round((MISSION_S if sim.mission else RUN_S) / SLOT_S)
    inference, work = deque(maxlen=250), deque(maxlen=250)
    began = deadline = time.monotonic()
    state = 'running'
    while state == 'running':
        now = time.monotonic()
        if now < deadline:
            time.sleep(deadline - now)
            now = time.monotonic()
        # Skip expired release times; do not hammer the CPU with catch-up steps.
        skipped = min(run_slots - slots - missed, max(0, int((now - deadline) / SLOT_S)))
        missed += skipped
        deadline += (1 + skipped) * SLOT_S
        fallen = False
        pushed = False
        if slots + missed < run_slots:
            if push_fd is not None:
                try:
                    command = os.read(push_fd, 16)
                except BlockingIOError:
                    pass
                else:
                    if not command:
                        push_fd = None
                    else:
                        sim.apply_push(command.decode('ascii'))
                        pushed = True
            fallen = sim.tick()
            if not (sim.mission and sim.mission.found):
                slots += 1
                inference.append(sim.inference_ms)
                work.append((time.monotonic() - now) * 1000)
        if sim.mission and sim.mission.found:
            state = 'found'
        elif fallen:
            state = 'fallen'
        elif slots + missed >= run_slots:
            state = 'complete'
        if pushed or slots == 1 or slots % 5 == 0 or state != 'running':
            p95 = sorted(work)[math.ceil(0.95 * len(work)) - 1] if work else None
            elapsed = max(time.monotonic() - began, now - began + SLOT_S)
            publish(dict(state=state, slots=slots, missed=missed, hz=round(slots / elapsed, 1),
                         inference_ms=round(sum(inference) / len(inference), 3) if inference else None,
                         slot_p95_ms=round(p95, 3) if work else None, **sim.snapshot()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vx', type=float, default=0.2)
    parser.add_argument('--yaw', type=float, default=0.0)
    parser.add_argument('--arena', choices=ARENAS)
    parser.add_argument('--interactive', action='store_true', help='Accept a push name from a dedicated stdin pipe')
    args = parser.parse_args()
    try:
        if hasattr(os, 'nice'):
            os.nice(10)
        sim = WalkSimulation(args.vx, args.yaw, args.arena)
        push_fd = None
        if args.interactive and not args.arena:
            push_fd = sys.stdin.fileno()
            os.set_blocking(push_fd, False)
        run(sim, push_fd)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        publish(dict(state='error', detail='Walking simulation could not run. Check the app logs and MuJoCo installation.'))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
