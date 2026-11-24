"""Rank launches using the shipped roller policy and record the fastest clean runs."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import math
import os
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
TERRAINS = {
    'tiles-450': dict(label='450 mm tiles', tile_m=.45, gap_m=.005, grout_depth_m=.003),
    'tiles-600': dict(label='600 mm tiles', tile_m=.60, gap_m=.005, grout_depth_m=.003),
    'carpet': dict(label='Carpet', axle_damping=.0015),
    'uphill': dict(label='3° uphill', grade_deg=3),
    'downhill': dict(label='3° downhill', grade_deg=-3),
    'cross-left': dict(label='3° cross slope · left side high', cross_deg=3),
    'cross-right': dict(label='3° cross slope · right side high', cross_deg=-3),
}


def surface_model(terrain):
    import mujoco as mj

    terrain = dict(terrain)
    slope, cross = (math.radians(terrain.get(key, 0)) for key in ('grade_deg', 'cross_deg'))
    half_pitch, half_roll = -slope / 2, cross / 2
    ground_quat = [math.cos(half_roll) * math.cos(half_pitch), math.sin(half_roll) * math.cos(half_pitch),
                   math.cos(half_roll) * math.sin(half_pitch), -math.sin(half_roll) * math.sin(half_pitch)]
    ground_slope = (math.tan(slope), math.tan(cross))

    def configure(spec):
        floor = spec.geom('floor')
        floor.quat = ground_quat
        if 'tile_m' in terrain:
            spacing = terrain['tile_m']
            edge = (spacing - terrain['gap_m']) / 2
            depth = terrain['grout_depth_m']
            floor.pos = [0, 0, -depth]
            columns = range(-2, math.ceil(8 / spacing))
            terrain['tile_origin_m'] = .12
            terrain['tile_columns'] = list(columns)
            for row in range(-1, 2):
                for col in columns:
                    spec.worldbody.add_geom(name=f'sprint_tile_{row}_{col}', type=mj.mjtGeom.mjGEOM_BOX,
                        size=[edge, edge, depth / 2], pos=[.12 + (col + .5) * spacing, row * spacing, -depth / 2],
                        contype=1, conaffinity=1, condim=3)
        if 'axle_damping' in terrain:
            floor.solref = [.04, 1]
            floor.priority = 2

    sim = WalkSimulation(0, 0, configure=configure if terrain else None, skates=True)
    if 'axle_damping' in terrain:
        for name in WHEEL_NAMES:
            sim.model.dof_damping[sim.model.joint(name).dofadr[0]] = terrain['axle_damping']
    floor_geoms = {sim.floor, *(i for i in range(sim.model.ngeom)
                               if sim.model.geom(i).name.startswith('sprint_tile_'))}
    return sim, terrain, (floor_geoms, ground_quat, ground_slope)


def run(sim, policy, speed, profile, grip, heading, *, record=False, surface=None):
    model, data, mj = sim.model, sim.data, sim.mj
    mj.mj_resetDataKeyframe(model, data, model.key('home').id)
    ramp, swizzle, steering = PROFILES.get(profile, (0, 0, 0))
    floor_geoms, ground_quat, (rise_x, rise_y) = surface or ({sim.floor}, (1., 0., 0., 0.), (0., 0.))
    model.geom_friction[[*floor_geoms, *sim.feet], 0] = grip
    root = sim.root
    angle = math.radians(heading) / 2
    w, x, y, z = ground_quat
    cosine, sine = math.cos(angle), math.sin(angle)
    data.qpos[root + 3:root + 7] = [w*cosine - z*sine, x*cosine + y*sine, y*cosine - x*sine, z*cosine + w*sine]
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
        if z - x * rise_x - y * rise_y < .085 or 1 - 2 * (qx * qx + qy * qy) < .70:
            failure = 'Lost balance'
        elif any(contact.dist < -.00015 and any(geom in floor_geoms for geom in contact.geom)
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


def sweep(terrain=None):
    sim, terrain, surface = surface_model(terrain or {})
    policy = load_roller_policy()
    ranked = []
    for profile in PROFILES:
        for speed in SPEEDS:
            runs = [run(sim, policy, speed, profile, grip, heading, surface=surface)
                    for grip in GRIPS for heading in HEADINGS]
            clean = [trial for trial in runs if trial['failure'] is None]
            ranked.append(dict(profile=profile, command_m_s=speed, clean=len(clean), total=len(runs),
                               median_m_s=round(median(trial['average_m_s'] for trial in clean), 4) if clean else None,
                               trials=runs))
    ranked.sort(key=lambda row: (row['clean'], row['median_m_s'] if row['median_m_s'] is not None else -math.inf), reverse=True)
    ranked_winner = ranked[0]
    clean = [trial for trial in ranked_winner['trials'] if trial['failure'] is None]
    reference = min(clean, key=lambda trial: (abs(trial['grip'] - .75), abs(trial['heading_deg'])), default=None)
    winner = (run(sim, policy, ranked_winner['command_m_s'], ranked_winner['profile'], reference['grip'],
                  reference['heading_deg'], record=True, surface=surface) if reference else None)
    report = dict(duration_s=DURATION, lane_half_width_m=LANE_HALF_WIDTH, model_sha256=policy.sha256,
                  winner=winner, ranked=ranked)
    if terrain:
        report['terrain'] = terrain
    else:
        report['baseline'] = run(sim, policy, .28, 'Passive push', .75, 0, record=True, surface=surface)
    return report


def sweep_terrain(name):
    report = sweep(TERRAINS[name])
    top = report['ranked'][0]
    print(name, top['profile'], top['command_m_s'], f"{top['clean']}/{top['total']}", top['median_m_s'], flush=True)
    return name, report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recording', type=Path, required=True)
    parser.add_argument('--terrain', action='store_true', help='Sweep all tile, carpet, and slope surfaces')
    args = parser.parse_args()
    if args.terrain:
        with ProcessPoolExecutor(max_workers=min(6, os.cpu_count() or 1)) as pool:
            terrain_report = dict(pool.map(sweep_terrain, TERRAINS))
        args.recording.write_text(json.dumps(terrain_report, separators=(',', ':')) + '\n', encoding='utf-8')
        sys.exit()
    report = sweep()
    args.recording.write_text(json.dumps(report, separators=(',', ':')) + '\n', encoding='utf-8')
    for row in report['ranked']:
        print(row['profile'], row['command_m_s'], f"{row['clean']}/{row['total']}", row['median_m_s'])
    for key in ('winner', 'baseline'):
        print(key, {name:value for name,value in report[key].items() if name != 'trace'})
