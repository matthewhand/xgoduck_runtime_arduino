"""Record the shipped XGO Duck skill policies on the simulated stock robot."""

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import sys

import mujoco as mj
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))

from controller import KICK_S, PICK_PERIOD_S, ROULADE_ALPHA, ROULADE_S
from policy import Policy
from rl_core import MOTOR_IDS
from walk_sim import JOINT_IDS, JOINT_NAMES, OBS_NAMES, SLOT_S, SUBSTEPS, WalkSimulation


BALL_RADIUS = .035
BALL_X, BALL_Y = .10, .042
SETTLE_S = .6
STAND_AFTER_S = 1.5
SIT_HOLD_S, RISE_S = 2.6, 2.0
SERVO_INDICES = [MOTOR_IDS.index(motor) for motor in JOINT_IDS]
MOTIONS = {
    'Forward roll': 'roulade',
    'Sit and stand': 'sitstand',
    'Ground reach': 'pick',
    'Left-foot ball kick': 'ballkick_left',
    'Right-foot ball kick': 'ballkick_right',
}
COMMUNITY = {
    'Polite bow': ('polite-bow', 'GinDuck/microduck-polite-bow', '6dd2ad21ef9a105945c0af826f68f9d62b0a6415',
                   '19c4270d0f835b54a4f8cae4863cdb80cd174906cb1bb33a534b4c3df83beb67'),
    'Flamingo balance': ('flamingo-cycle', 'RemiFabre/microduck-flamingo-cycle', 'a69e4f6103a70e355983eb5d4e919da76778a40f',
                        'df77929c39d7695092bdaf810c2075e20a9ba91abd8192b4073d3de593d56904'),
}


def load_skill(skill, path=None):
    policy = Policy()
    ok, message = policy.load(path or f'xgoduck_{skill}.onnx', use_model_home=path is not None)
    if not ok:
        raise RuntimeError(message)
    metadata = policy.session.get_modelmeta().custom_metadata_map
    if tuple(metadata.get('joint_names', '').split(',')) != JOINT_NAMES or metadata.get('observation_names') != OBS_NAMES:
        raise RuntimeError(f'{policy.file} has an unexpected model interface')
    if skill.startswith('ballkick_'):
        policy.action_scale = .8
        policy.set_action_alphas(leg=0, head=0)
    if skill == 'roulade':
        policy.set_action_alphas(leg=ROULADE_ALPHA, head=ROULADE_ALPHA)
    if path is not None:
        policy.set_action_alphas(leg=0, head=0)
    return policy


def skill_command(skill, elapsed):
    if skill == 'sitstand':
        return ((1, 0, 0), 'Sit') if elapsed < SIT_HOLD_S else ((0, 0, 0), 'Stand')
    if skill in ('pick', 'polite-bow'):
        phase = math.tau * elapsed / PICK_PERIOD_S
        return (math.cos(phase), math.sin(phase), 0), 'Reach' if skill == 'pick' else 'Bow'
    if skill == 'flamingo-cycle':
        return ((1, 1, 0), 'Lift and balance') if elapsed < 2.6 else ((0, 0, 0), 'Lower foot')
    return (0, 0, 0), 'Roll' if skill == 'roulade' else 'Kick'


def add_ball(spec):
    ball = spec.worldbody.add_body(name='motion_ball', pos=[BALL_X, BALL_Y, BALL_RADIUS],
                                  mass=.015, inertia=[1.225e-5]*3, explicitinertial=1)
    ball.add_freejoint(name='motion_ball_free')
    ball.add_geom(name='motion_ball_collision', type=mj.mjtGeom.mjGEOM_SPHERE, size=[BALL_RADIUS, 0, 0],
                  friction=[.5,.005,.0001], contype=1, conaffinity=1)


def record(sim, stand, policy, skill, *, ball_position=None):
    d, m = sim.data, sim.model
    mj.mj_resetDataKeyframe(m, d, m.key('STAND').id)
    stand.reset_action_filter()
    policy.reset_action_filter()
    ball, ball_geom = None, None
    if ball_position is not None:
        ball = int(m.joint('motion_ball_free').qposadr[0])
        ball_geom = m.geom('motion_ball_collision').id
        d.qpos[ball:ball + 3] = [*ball_position, BALL_RADIUS]
    head_mesh = m.mesh('head_roll').id
    head = next(i for i, mesh in enumerate(m.geom_dataid)
                if mesh == head_mesh and m.geom_type[i] == mj.mjtGeom.mjGEOM_MESH and m.geom_contype[i])
    first_vertex = m.mesh_vertadr[head_mesh]
    head_vertices = m.mesh_vert[first_vertex:first_vertex + m.mesh_vertnum[head_mesh]]
    angles, velocities = np.zeros(len(MOTOR_IDS)), np.zeros(len(MOTOR_IDS))
    limits = {'sitstand':SIT_HOLD_S + RISE_S, 'pick':PICK_PERIOD_S, 'roulade':ROULADE_S,
              'polite-bow':2.8, 'flamingo-cycle':4.2, 'dance':4.0}
    skill_s = limits.get(skill, KICK_S)
    start_tick = round(SETTLE_S / SLOT_S)
    action_ticks = round(skill_s / SLOT_S)
    total_ticks = start_tick + action_ticks + round(STAND_AFTER_S / SLOT_S)
    trace, height, tilt, pitch = [], [], [], []
    head_clearance = math.inf
    ball_contact = None
    touched_by_foot = set()
    right_only_ticks = longest_right_only = 0

    def sample(phase):
        frame = dict(time_s=round(float(d.time), 3), root=d.qpos[sim.root:sim.root + 7].round(6).tolist(),
                     joints_rad=dict(zip(JOINT_IDS, d.qpos[sim.qpos].round(6).tolist())), contacts=d.ncon,
                     motion_phase=phase)
        if ball is not None:
            frame['ball'] = d.qpos[ball:ball + 7].round(6).tolist()
        trace.append(frame)

    mj.mj_forward(m, d)
    sample('Settle')
    for tick in range(total_ticks):
        mj.mj_forward(m, d)
        elapsed = (tick - start_tick) * SLOT_S
        if start_tick <= tick < start_tick + action_ticks:
            command, phase = ((0, 0, 0), 'Head dance') if skill == 'dance' else skill_command(skill, elapsed)
            current = policy
        else:
            command, phase = (0, 0, 0), 'Settle' if tick < start_tick else 'Return to idle'
            current = stand
        if tick == start_tick + action_ticks:
            stand.reset_action_filter()
        angles[SERVO_INDICES] = np.rad2deg(d.qpos[sim.qpos])
        velocities[SERVO_INDICES] = np.rad2deg(d.qvel[sim.qvel])
        head = None
        if phase == 'Head dance':
            beat = math.tau * elapsed
            ease = min(1., elapsed * 4, (skill_s - elapsed) * 4)
            head = [0, .16 * ease * math.sin(2 * beat), .30 * ease * math.sin(beat), .10 * ease * math.cos(beat)]
        action = current.infer(-d.xmat[sim.trunk, 6:9], d.sensordata[sim.gyro], angles, velocities, command, head)
        d.ctrl[sim.actuators] = np.deg2rad(np.asarray(current.action_to_deg(action))[SERVO_INDICES])
        for _ in range(SUBSTEPS):
            mj.mj_step(m, d)
            if ball_geom is not None:
                for contact in d.contact:
                    a, b = contact.geom
                    if ball_geom in (a, b) and (a in sim.feet or b in sim.feet):
                        ball_contact = ball_contact if ball_contact is not None else round(float(d.time), 3)
                        touched_by_foot.add(sim.feet[b if a == ball_geom else a])
        if not np.isfinite(d.qpos).all():
            raise RuntimeError(f'{skill} produced a non-finite pose')
        w, x, y, z = d.qpos[sim.root + 3:sim.root + 7]
        up = 1 - 2*(x*x + y*y)
        height.append(float(d.qpos[sim.root + 2]))
        tilt.append(math.degrees(math.acos(min(1., max(-1., up)))))
        pitch.append(math.atan2(2*(w*y + x*z), up))
        if skill == 'pick':
            head_clearance = min(head_clearance, float(d.geom_xpos[head, 2] + (head_vertices @ d.geom_xmat[head, 6:9]).min()))
        if skill == 'flamingo-cycle' and phase == 'Lift and balance':
            feet = {sim.feet.get(b if a == sim.floor else a) for a, b in (contact.geom for contact in d.contact)
                    if sim.floor in (a, b)}
            right_only_ticks = right_only_ticks + 1 if feet == {'right'} else 0
            longest_right_only = max(longest_right_only, right_only_ticks)
        if tick % 2 == 1 or tick == total_ticks - 1:
            sample(phase)

    tail = round(.35 / SLOT_S)
    upright = min(height[-tail:]) >= .105 and max(tilt[-tail:]) <= 25
    motion = dict(policy=policy.file, sha256=policy.sha256, idle_sha256=stand.sha256, upright=bool(upright),
                  torso_drop_m=round(height[0]-min(height), 4), peak_tilt_deg=round(max(tilt), 1))
    if skill == 'pick':
        motion['lowest_head_m'] = round(max(0., head_clearance), 4)
    if skill == 'roulade':
        motion['pitch_travel_deg'] = round(float(np.ptp(np.rad2deg(np.unwrap(pitch)))), 1)
    if skill == 'flamingo-cycle':
        motion['one_foot_s'] = round(longest_right_only * SLOT_S, 2)
    if ball is not None:
        motion.update(ball_radius_m=BALL_RADIUS, ball_contact_s=ball_contact, ball_feet=sorted(touched_by_foot),
                      ball_forward_m=round(float(d.qpos[ball]-ball_position[0]), 4))
    return dict(motion=motion, trace=trace)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recording', required=True, type=Path)
    parser.add_argument('--community-dir', type=Path, help='Directory with the pinned Microduck ONNX files')
    args = parser.parse_args()
    stand = load_skill('walk')
    sim = WalkSimulation(0, 0)
    kick_sim = WalkSimulation(0, 0, configure=add_ball)
    cases = {}
    for label, skill in MOTIONS.items():
        policy = load_skill(skill)
        side = 1 if skill.endswith('_left') else -1
        ball_position = (BALL_X, side*BALL_Y) if skill.startswith('ballkick_') else None
        result = record(kick_sim if ball_position else sim, stand, policy, skill, ball_position=ball_position)
        cases[label] = result
        print(label, {k: v for k,v in result['motion'].items() if 'sha256' not in k}, flush=True)
    report = {'XGO Duck policy':cases}
    if args.community_dir:
        community = report['Microduck transfer trial'] = {}
        for label, (skill, repo, revision, digest) in COMMUNITY.items():
            path = args.community_dir / f'microduck-{skill}.onnx'
            if sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError(f'Checksum mismatch for {path.name}')
            result = record(sim, stand, load_skill(skill, path), skill)
            result['motion'].update(source=f'https://huggingface.co/{repo}/tree/{revision}', author=repo.split('/')[0])
            community[label] = result
            print(label, {k: v for k,v in result['motion'].items() if 'sha256' not in k}, flush=True)
    args.recording.write_text(json.dumps(report, separators=(',', ':')) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
