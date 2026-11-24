"""Rank flat-floor launches using the shipped roller policy and record the best run."""

import argparse
import json
import math
from pathlib import Path
from statistics import median
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))

from skate_dock_exit import load_roller_policy, roller_target
from walk_sim import JOINT_IDS, SLOT_S, SUBSTEPS, WHEEL_NAMES, WalkSimulation


DURATION = 6
SPEEDS = (.10, .15, .20, .25, .30, .35, .40)
GRIPS = (.55, .75, .95)
HEADINGS = (-3, 0, 3)
PROFILES = {
    'Direct': (0, 0, 0),
    'Ramp': (.6, 0, 0),
    'Narrow swizzle': (.6, .05, 0),
    'Wide swizzle': (.6, .10, 0),
    'Direct with lane steering': (0, 0, 1.8),
    'Ramp with lane steering': (.6, 0, 1.8),
}
LANE_HALF_WIDTH = .15


def run(sim, policy, speed, profile, grip, heading, *, record=False):
    model, data, mj = sim.model, sim.data, sim.mj
    mj.mj_resetDataKeyframe(model, data, model.key('home').id)
    ramp, swizzle, steering = PROFILES.get(profile, (0, 0, 0))
    model.geom_friction[[sim.floor, *sim.feet], 0] = grip
    root = sim.root
    angle = math.radians(heading) / 2
    data.qpos[root + 3:root + 7] = [math.cos(angle), 0, 0, math.sin(angle)]
    wheels = [int(model.joint(name).qposadr[0]) for name in WHEEL_NAMES]
    # Benchmark the previous demo separately with its original initial shove.
    if profile == 'Passive push':
        data.qvel[sim.root_dof] = speed
    policy.reset_action_filter()
    mj.mj_forward(model, data)
    origin_x, origin_y = map(float, data.qpos[root:root + 2])
    positions, trace = [origin_x], []
    max_side = 0.
    failure = None

    def sample():
        trace.append(dict(time_s=round(float(data.time), 3),
                          root=data.qpos[root:root + 7].round(6).tolist(),
                          joints_rad=dict(zip(JOINT_IDS, data.qpos[sim.qpos].round(6).tolist())),
                          wheels_rad=data.qpos[wheels].round(6).tolist()))

    if record:
        sample()
    total_slots = round(DURATION / SLOT_S)
    for tick in range(total_slots):
        if profile != 'Passive push':
            time = tick * SLOT_S
            gain = min(time / ramp, 1) if ramp else 1
            lateral = gain * swizzle * math.sin(2 * math.pi * time)
            yaw_command = 0.
            if steering:
                w, qx, qy, qz = data.qpos[root + 3:root + 7]
                yaw = math.atan2(2 * (w * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz))
                target = math.atan2(origin_y - data.qpos[root + 1], .35)
                yaw_command = max(-.45, min(.45, steering * (target - yaw)))
            data.ctrl[sim.actuators] = roller_target(sim, policy, [speed * gain, lateral, yaw_command])
        mj.mj_step(model, data, nstep=SUBSTEPS)
        x, y, z, _, qx, qy, _ = map(float, data.qpos[root:root + 7])
        positions.append(x)
        max_side = max(max_side, abs(y - origin_y))
        if not all(math.isfinite(value) for value in (x, y, z, qx, qy)):
            raise RuntimeError('The rollout produced a non-finite pose')
        if z < .085 or 1 - 2 * (qx * qx + qy * qy) < .70:
            failure = 'Lost balance'
        elif any(sim.floor in contact.geom and contact.dist < -.00015
                 and not any(geom in sim.feet for geom in contact.geom) for contact in data.contact):
            failure = 'Body touched floor'
        elif max_side > LANE_HALF_WIDTH:
            failure = 'Left lane'
        if record and (tick % 2 == 1 or tick == total_slots - 1 or failure):
            sample()
        if failure:
            break

    half_second = round(.5 / SLOT_S)
    distance = positions[-1] - origin_x
    peak_speed = max((later - earlier for earlier, later in zip(positions, positions[half_second:])), default=0.) / .5
    result = dict(grip=grip, heading_deg=heading, failure=failure,
                  elapsed_s=round(float(data.time), 3), forward_m=round(distance, 4),
                  average_m_s=round(distance / float(data.time), 4),
                  peak_half_second_m_s=round(peak_speed, 4), max_side_m=round(max_side, 4))
    if record:
        result['trace'] = trace
    return result


def sweep():
    sim = WalkSimulation(0, 0, skates=True)
    policy = load_roller_policy()
    ranked = []
    for profile in PROFILES:
        for speed in SPEEDS:
            runs = [run(sim, policy, speed, profile, grip, heading) for grip in GRIPS for heading in HEADINGS]
            clean = [trial for trial in runs if trial['failure'] is None]
            ranked.append(dict(profile=profile, command_m_s=speed, clean=len(clean), total=len(runs),
                               median_m_s=round(median(trial['average_m_s'] for trial in clean), 4) if clean else None,
                               trials=runs))
    ranked.sort(key=lambda row: (row['clean'], row['median_m_s'] if row['median_m_s'] is not None else -math.inf), reverse=True)
    winner = ranked[0]
    if winner['clean'] != winner['total']:
        raise RuntimeError('No skate move completed every launch cleanly')
    return dict(duration_s=DURATION, lane_half_width_m=LANE_HALF_WIDTH, model_sha256=policy.sha256,
                winner=run(sim, policy, winner['command_m_s'], winner['profile'], .75, 0, record=True),
                baseline=run(sim, policy, .28, 'Passive push', .75, 0, record=True), ranked=ranked)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recording', type=Path, required=True)
    args = parser.parse_args()
    report = sweep()
    args.recording.write_text(json.dumps(report, separators=(',', ':')) + '\n', encoding='utf-8')
    for row in report['ranked']:
        print(row['profile'], row['command_m_s'], f"{row['clean']}/{row['total']}", row['median_m_s'])
    for key in ('winner', 'baseline'):
        print(key, {name:value for name,value in report[key].items() if name != 'trace'})
