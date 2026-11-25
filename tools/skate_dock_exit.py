"""Simulate a straight release from the fixed-pad chair on passive skates."""

import math

import numpy as np

from policy import Policy
from rl_core import MOTOR_IDS, ROLLER_LEG_DEFAULT_DEG
from walk_sim import JOINT_IDS, SLOT_S, SUBSTEPS


# Tested on the 40-degree backrest with the wide skate approach stance.
# Left hip pitch, knee and ankle targets are mirrored on the right side.
RISE_STAGES = (
    (23, (1.240510052563163, 1.4116352845612399, .22844202514710987), -.0955817181336462),
    (32, (-.15397220485067134, 1.2148564169585516, 1.3543915925740233), .11044602595471537),
)
NOMINAL_ROLL = .31785747722884683
ROLLER_SLOTS = 175
BLEND_SLOTS = 20
MAX_CLEARANCE_WAIT_SLOTS = 20
OBSERVATION_SLOTS = 4
FLOOR_CONTACT_DEPTH_M = .00015

SIM_MOTOR_INDEX = [JOINT_IDS.index(motor) if motor in JOINT_IDS else None for motor in MOTOR_IDS]
POLICY_MOTOR_INDEX = [MOTOR_IDS.index(motor) for motor in JOINT_IDS]


def load_roller_policy(*, pinned=None):
    policy = Policy()
    path, digest = pinned or ('xgoduck_roller.onnx', None)
    ok, message = policy.load(path, use_model_home=True, expected_sha256=digest)
    if not ok:
        raise RuntimeError(message)
    for index, motor_id in enumerate(JOINT_IDS):
        if motor_id in ROLLER_LEG_DEFAULT_DEG:
            policy.home_deg[index] = ROLLER_LEG_DEFAULT_DEG[motor_id]
    policy.action_scale = .8
    policy.set_action_alphas(leg=.4, head=.5)
    return policy


def _mirrored_pose(nominal, angles, hip_roll):
    target = nominal.copy()
    target[1], target[10] = -hip_roll, hip_roll
    target[2:5] = angles
    target[11:14] = -np.asarray(angles)
    return target


def _motor_degrees(sim_values):
    degrees = np.rad2deg(sim_values)
    return [float(degrees[index]) if index is not None else 0. for index in SIM_MOTOR_INDEX]


def roller_target(sim, policy, command):
    data = sim.data
    sim.mj.mj_forward(sim.model, data)
    action = policy.infer(-data.xmat[sim.trunk, 6:9], data.sensordata[sim.gyro],
                          _motor_degrees(data.qpos[sim.qpos]),
                          _motor_degrees(data.qvel[sim.qvel]), command)
    angles = policy.action_to_deg(action)
    return np.deg2rad([angles[index] for index in POLICY_MOTOR_INDEX])


def forward_clearance(sim):
    """Conservative fore-aft gap between robot and all chair collision shapes."""
    model, data = sim.model, sim.data
    sim.mj.mj_kinematics(model, data)
    axes = data.geom_xmat.reshape(-1, 3, 3)[:, 0, :]
    centres = data.geom_xpos[:, 0] + np.sum(axes * model.geom_aabb[:, :3], axis=1)
    radii = np.sum(np.abs(axes) * model.geom_aabb[:, 3:], axis=1)
    robot = (model.geom_bodyid != 0) & (model.geom_contype != 0)
    fixture = (model.geom_bodyid == 0) & (model.geom_conaffinity != 0)
    fixture[sim.floor] = False
    return float(np.min(centres[robot] - radii[robot]) - np.max(centres[fixture] + radii[fixture]))


def roll_off_fixed_pad(sim, record, *, velocity=.12, policy=None, clearance_handoff=False,
                       contact_handoff=False):
    """Advance a parked 40-degree chair simulation through the experimental exit.

    Call after observing the parked frame and restoring the actuator gains.
    The lowering and approach stages must have ended with the skates on the
    floor. The callback records the rise and roller frames in the normal schema.
    The result records both upright travel and any nonwheel floor contacts.
    """
    model, data = sim.model, sim.data
    mj = sim.mj
    root = sim.root
    initial_x = float(data.qpos[root])
    initial_y = float(data.qpos[root + 1])
    policy = policy if policy is not None else load_roller_policy()
    nominal = np.deg2rad(policy.home_deg)
    home = nominal.copy()
    home[1], home[10] = -NOMINAL_ROLL, NOMINAL_ROLL
    stages = [(slots, _mirrored_pose(nominal, angles, roll)) for slots, angles, roll in RISE_STAGES]
    stages.extend(((22, home), (14, home)))
    previous = data.qpos[sim.qpos].copy()
    floor_contacts = set()
    exit_chair_contacts = set()
    chair_geoms = {idx for idx in range(model.ngeom)
                   if idx != sim.floor and model.geom_bodyid[idx] == 0 and model.geom_conaffinity[idx]}
    brace_slots = 0
    max_side = 0.
    minimum_height = math.inf
    after_handoff_up = 1.
    after_handoff_height = math.inf
    elapsed_slots = 0

    def chair_contacts():
        return {model.geom(geom).name for contact in data.contact if contact.dist < 0
                for geom in contact.geom if geom in chair_geoms}

    def advance(phase, *, roller=False):
        nonlocal elapsed_slots, brace_slots, max_side, minimum_height
        nonlocal after_handoff_up, after_handoff_height
        last_xy = data.qpos[root:root + 2].copy()
        if roller and contact_handoff:
            for _ in range(SUBSTEPS):
                mj.mj_step(model, data)
                exit_chair_contacts.update(chair_contacts())
        else:
            mj.mj_step(model, data, nstep=SUBSTEPS)
        sim.path_m += float(np.linalg.norm(data.qpos[root:root + 2] - last_xy))
        elapsed_slots += 1
        w, x, y, z = data.qpos[root + 3:root + 7]
        height = float(data.qpos[root + 2])
        max_side = max(max_side, abs(2 * (w*x + y*z)))
        minimum_height = min(minimum_height, height)
        if roller:
            after_handoff_height = min(after_handoff_height, height)
            after_handoff_up = min(after_handoff_up, 1 - 2*(x*x + y*y))
        touched_floor = set()
        for contact in data.contact:
            a, b = contact.geom
            other = b if a == sim.floor else a if b == sim.floor else None
            if other is not None and other not in sim.feet and contact.dist < -FLOOR_CONTACT_DEPTH_M:
                geom = model.geom(other)
                touched_floor.add(geom.name or model.body(geom.bodyid[0]).name)
        if touched_floor:
            brace_slots += 1
            floor_contacts.update(touched_floor)
        if elapsed_slots % OBSERVATION_SLOTS == 0:
            record(phase)

    for slots, target in stages:
        for tick in range(1, slots + 1):
            u = tick / slots
            data.ctrl[sim.actuators] = previous + u*u*(3 - 2*u)*(target - previous)
            advance('chair_rise')
        previous = target

    def tall_and_upright():
        _, x, y, _ = data.qpos[root + 3:root + 7]
        return data.qpos[root + 2] >= .145 and 1 - 2*(x*x + y*y) >= .95

    clearance = forward_clearance(sim) if clearance_handoff or contact_handoff else None
    if contact_handoff:
        # Allow the old rise to finish. A projection can overlap a fixture even
        # when the upright Duck has released all contacts and can skate away.
        mj.mj_forward(model, data)
        for _ in range(MAX_CLEARANCE_WAIT_SLOTS):
            if not tall_and_upright() or not chair_contacts():
                break
            advance('chair_rise')
            mj.mj_forward(model, data)
        clear_to_roll = not chair_contacts()
        clearance = forward_clearance(sim)
    elif clearance_handoff:
        for _ in range(MAX_CLEARANCE_WAIT_SLOTS):
            if clearance >= .003 or clearance < -.010 or not tall_and_upright():
                break
            advance('chair_rise')
            clearance = forward_clearance(sim)
        clear_to_roll = clearance >= .003
    else:
        clear_to_roll = data.qpos[root] - initial_x >= .10
    handoff = bool(tall_and_upright() and clear_to_roll)
    handoff_x = float(data.qpos[root])
    handoff_s = float(data.time)
    if handoff:
        sim.recovery.phase = 'walk'
        sim.resumed_at_s = round(handoff_s, 3)
        policy.reset_action_filter()
        for tick in range(ROLLER_SLOTS):
            target_angles = roller_target(sim, policy, [velocity, 0., 0.])
            blend = min(1., (tick + 1) / BLEND_SLOTS)
            data.ctrl[sim.actuators] = (1 - blend)*home + blend*target_angles
            advance(None, roller=True)
    record(None if handoff else 'chair_rise')

    _, x, y, _ = data.qpos[root + 3:root + 7]
    upright = float(1 - 2*(x*x + y*y))
    side_tilt = math.degrees(math.asin(min(1., max_side)))
    travelled = float(data.qpos[root] - initial_x)
    after_handoff = float(data.qpos[root] - handoff_x) if handoff else 0.
    upright_exit = handoff and after_handoff >= .10 and side_tilt <= 25.
    upright_exit = bool(upright_exit and upright >= .985 and after_handoff_height >= .12 and after_handoff_up >= .85)
    result = dict(
        elapsed_slots=elapsed_slots,
        handoff=handoff,
        handoff_s=round(handoff_s, 3) if handoff else None,
        chair_clearance_mm=round(clearance * 1000, 2) if clearance is not None else None,
        handoff_x_m=round(handoff_x, 5) if handoff else None,
        upright_exit=upright_exit,
        wheels_only_exit=upright_exit and not floor_contacts,
        travelled_m=round(travelled, 4),
        after_handoff_m=round(after_handoff, 4),
        sideways_m=round(float(data.qpos[root + 1] - initial_y), 4),
        side_tilt_deg=round(side_tilt, 2),
        upright=round(upright, 4),
        minimum_height_m=round(minimum_height, 4),
        post_handoff_minimum_height_m=round(after_handoff_height, 4) if handoff else None,
        floor_contacts=sorted(floor_contacts),
        floor_contact_s=round(brace_slots * SLOT_S, 3),
    )
    if contact_handoff:
        result['exit_chair_contacts'] = sorted(exit_chair_contacts)
        result['wheels_only_exit'] &= not exit_chair_contacts
    return result
