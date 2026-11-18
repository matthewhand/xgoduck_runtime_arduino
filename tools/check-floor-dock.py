"""Screen floor docks with the shipped XGO Duck walking and get-up policies."""
import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import sys

import mujoco as mj
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))
from walk_sim import SLOT_S, STEP_S, WHEEL_NAMES, WalkSimulation

DESIGNS = json.loads((ROOT / 'assets/sim/floor-dock-designs.json').read_text(encoding='utf8'))
PARK_S = 1.2
RECOVERY_S = 8
PAD_SIDES = ('Left', 'Right')
CASES = {
    'Nearly flat': (90, 0, 0),
    'Centred entry': (85, 0, 0),
    '8 mm left': (85, .008, 0),
    '8 mm right': (85, -.008, 0),
    'Angled left': (85, .014, 8),
    'Angled right': (85, -.014, -8),
    'Steeper entry': (81, 0, 0),
}
CHAIR_CASES = {
    'Centred entry': (0, 0, 0),
    '8 mm left': (0, .008, 0),
    '8 mm right': (0, -.008, 0),
    'Shallower entry': (-4, 0, 0),
    'Steeper entry': (4, 0, 0),
    'Angled left': (-2, .006, 5),
    'Angled right': (-2, -.006, -5),
}
APPROACH_CASES = {
    'Approach · centred': (.32, 0, 0, .16),
    'Approach · left': (.32, .008, 0, .16),
    'Approach · right': (.32, -.008, 0, .16),
    'Approach · yaw left': (.32, .008, 5, .16),
    'Approach · yaw right': (.32, -.008, -5, .16),
    'Approach · slow': (.32, 0, 0, .09),
    'Approach · fast': (.32, 0, 0, .28),
    'Approach · longer': (.42, 0, 0, .16),
    'Approach · wide left': (.32, .027, 4, .26),
    'Approach · wide right': (.32, -.027, -4, .26),
}
APPROACH_CHAIRS = ('Low chair', 'Floor-level chair', 'Wide floor-level chair', 'Funnel chair')
FIXED_PAD_PROFILES = (
    ('Fixed pad chair', False, 45, None, .175),
    ('Fixed pad chair · Skates', True, 40, None, .175),
    ('Fixed pad chair · Wide skates', True, 40, .08, .175),
    ('Fixed pad chair · Wide skates 50°', True, 50, .08, .175),
    ('Fixed pad chair · Skates, later tuck', True, 45, None, .165),
)
SHROUD = [
    {'name': 'Shroud', 'parent': 'trunk_base', 'center_m': [-.07675, 0, -.020],
     'size_m': [.0025, .068, .076], 'mass_kg': .014},
    {'name': 'Receiver', 'parent': 'trunk_base', 'center_m': [-.0794, -.015, -.021],
     'size_m': [.0028, .028, .044], 'mass_kg': .008},
    *[{'name': f'{side} bumper', 'parent': 'trunk_base', 'center_m': [-.078, y, -.020],
       'capsule_m': [.004, .072], 'mass_kg': .003} for side, y in [('Left', .033), ('Right', -.033)]],
]


def dock_modules(design):
    if design in DESIGNS.get('chairs', {}):
        for module in DESIGNS['chairs'][design]['modules']:
            yield {'parent': 'world', **module}
        return
    yield {'name': 'Deck', 'parent': 'world', **DESIGNS['deck']}
    for index, guide in enumerate(DESIGNS['designs'][design], start=1):
        yield {'name': f'Guide {index}', 'parent': 'world', **guide}


def build_scene(spec, modules):
    spec.geom('floor').conaffinity |= 4
    for module in modules:
        params = {'name': module['name'], 'pos': module['center_m']}
        if 'capsule_m' in module:
            radius, length = module['capsule_m']
            params.update(type=mj.mjtGeom.mjGEOM_CAPSULE, size=[radius, length / 2 - radius, 0])
        elif 'ramp_deg' in module:
            run, width, height = np.array(module['size_m']) / 2
            rise = 2 * run * math.tan(math.radians(module['ramp_deg']))
            direction = math.copysign(1, rise)
            low = height - abs(rise)
            vertices = [(x, y, z) for x, top in [(-run * direction, low), (run * direction, height)]
                        for y in (-width, width) for z in (-height, top)]
            mesh = spec.add_mesh(name=module['name'], uservert=np.asarray(vertices).ravel())
            params.update(type=mj.mjtGeom.mjGEOM_MESH, meshname=mesh.name)
        else:
            params.update(type=mj.mjtGeom.mjGEOM_BOX, size=np.array(module['size_m']) / 2)
        if module['parent'] == 'world':
            roll = math.radians(module.get('roll_deg', 0)) / 2
            pitch = math.radians(module.get('pitch_deg', 0)) / 2
            rotation = [math.cos(pitch) * math.cos(roll), math.cos(pitch) * math.sin(roll),
                        math.sin(pitch) * math.cos(roll), -math.sin(pitch) * math.sin(roll)]
            if module.get('yaw_deg'):
                yaw = math.radians(module['yaw_deg']) / 2
                rotated = np.empty(4)
                mj.mju_mulQuat(rotated, np.array([math.cos(yaw), 0, 0, math.sin(yaw)]), np.asarray(rotation))
                rotation = rotated
            friction = [.66, .006, .0001] if module['name'] == 'Deck' else [.46, .004, .0001]
            spec.worldbody.add_geom(**params, quat=rotation,
                                     contype=0, conaffinity=5, priority=1, friction=friction)
        else:
            parent = spec.body(module['parent']).add_body(name=module['name'], pos=params.pop('pos'))
            parent.add_geom(**params, mass=module['mass_kg'], contype=4, conaffinity=0)


def minimum_height(model, data):
    lowest = 0.
    for geom in range(model.ngeom):
        if model.geom_bodyid[geom] == 0 or not model.geom_contype[geom]:
            continue
        axis = data.geom_xmat[geom].reshape(3, 3)[2]
        centre = data.geom_xpos[geom, 2]
        size = model.geom_size[geom]
        kind = model.geom_type[geom]
        if kind == mj.mjtGeom.mjGEOM_MESH:
            mesh = model.geom_dataid[geom]
            first = model.mesh_vertadr[mesh]
            vertices = model.mesh_vert[first:first + model.mesh_vertnum[mesh]]
            depth = -min(vertices @ axis)
        elif kind == mj.mjtGeom.mjGEOM_CAPSULE:
            depth = size[0] + abs(axis[2]) * size[1]
        else:
            depth = np.abs(axis) @ size
        lowest = min(lowest, centre - depth)
    return lowest


def smoothstep(value):
    return value * value * (3 - 2 * value)


def rise_target(sim, angles):
    target = sim.walk[1].astype(float)
    for side, sign in (('left', 1), ('right', -1)):
        for joint, angle in zip(('hip_pitch', 'knee', 'ankle'), angles):
            actuator = sim.model.actuator(f'{side}_{joint}').id
            target[sim.actuators.index(actuator)] = angle * sign
    return target


def set_skate_stance(sim, pose, hip_roll_rad, addresses):
    for side, sign in (('left', -1), ('right', 1)):
        actuator = sim.model.actuator(f'{side}_hip_roll').id
        pose[addresses[sim.actuators.index(actuator)]] = sign * hip_roll_rad


def chair_rise(sim, stages, record, skate_roll=None):
    """Apply mirrored leg targets, then blend to the walking policy's nominal pose."""
    model, data = sim.model, sim.data
    previous = data.qpos[sim.qpos].copy()
    targets = [(slots, rise_target(sim, angles)) for slots, angles in stages]
    targets.append((22, sim.walk[1].astype(float)))
    elapsed = 0
    for slots, target in targets:
        if skate_roll is not None:
            set_skate_stance(sim, target, skate_roll, range(len(target)))
        for slot in range(1, slots + 1):
            blend = smoothstep(slot / slots)
            data.ctrl[sim.actuators] = previous + blend * (target - previous)
            mj.mj_step(model, data, nstep=round(SLOT_S / STEP_S))
            elapsed += 1
            if elapsed % 4 == 0:
                record('chair_rise')
        previous = target
    mj.mj_forward(model, data)
    if data.qpos[sim.root + 2] >= .115 and data.xmat[sim.trunk, 8] >= .96:
        sim.recovery.phase = 'walk'
        sim.resumed_at_s = round(data.time, 3)
    return elapsed


def back_into_chair(sim, approach, chair, stages, *, skates, record, skate_roll=None, trigger=None,
                    slow_skate_gate=None, entry_maneuver=None, navigate=None):
    model, data = sim.model, sim.data
    x, lateral, heading, speed = approach
    yaw = math.radians(heading)
    if skates:
        # Use the roller model's standing pose and let the wheels coast from
        # a known speed while the motor positions stay held.
        mj.mj_resetDataKeyframe(model, data, model.key('home').id)
        if skate_roll is not None:
            set_skate_stance(sim, data.qpos, skate_roll, sim.qpos)
            set_skate_stance(sim, data.ctrl, skate_roll, sim.actuators)
        if navigate is None:
            data.qvel[sim.root_dof:sim.root_dof + 2] = (-speed * math.cos(yaw), -speed * math.sin(yaw))
    data.qpos[sim.root:sim.root + 2] = (x, lateral)
    data.qpos[sim.root + 3:sim.root + 7] = (math.cos(yaw / 2), 0, 0, math.sin(yaw / 2))
    sim.command = (-speed, 0, 0)
    mj.mj_forward(model, data)
    trigger = .175 if trigger is None else trigger
    lower_at = trigger
    gate_checked = False
    if navigate is not None:
        reached = navigate(sim, record, skates, speed, lower_at)
    else:
        record('approaching')
        for slot in range(1, round(3.6 / SLOT_S) + 1):
            if skates:
                mj.mj_step(model, data, nstep=round(SLOT_S / STEP_S))
            else:
                sim.tick()
            if slot % 4 == 0:
                record('approaching')
            if slow_skate_gate is not None and not gate_checked and data.qpos[sim.root] <= trigger:
                cutoff, late_trigger = slow_skate_gate
                if -data.qvel[sim.root_dof] < cutoff:
                    lower_at = late_trigger
                gate_checked = True
            if data.qpos[sim.root] <= lower_at or data.qpos[sim.root + 2] < .08:
                break
        reached = bool(data.qpos[sim.root] <= lower_at)
    lowering_speed = float(-data.qvel[sim.root_dof]) if reached else None
    if reached and stages:
        sim.recovery.reset()
        sim.fall_at_s = sim.getup_at_s = sim.resumed_at_s = None
        # Let the resulting pose settle under gravity before testing seating.
        profile = chair.get('sit_profile')
        lowering = DESIGNS['sit_profiles'][profile]['skates' if skates else 'feet'] if profile else None
        if slow_skate_gate is not None:
            record('sitting')
        if entry_maneuver is not None:
            reached = entry_maneuver.run(sim, record, lowering)
            sim.command = (.12, 0, 0)
            return reached, lower_at, lowering_speed
        for slots, angles in lowering or reversed(stages):
            previous = data.ctrl[sim.actuators].copy()
            target = rise_target(sim, angles)
            for step in range(1, slots + 1):
                blend = smoothstep(step / slots)
                data.ctrl[sim.actuators] = previous + blend * (target - previous)
                mj.mj_step(model, data, nstep=round(SLOT_S / STEP_S))
                if step % 4 == 0:
                    record('sitting')
    sim.command = (.12, 0, 0)
    return reached, lower_at, lowering_speed


def pad_loads(model, data, pairs):
    loads = dict.fromkeys(PAD_SIDES, 0.)
    force = np.zeros(6)
    for index, contact in enumerate(data.contact):
        side = pairs.get(frozenset(contact.geom))
        if side:
            mj.mj_contactForce(model, data, index, force)
            loads[side] += float(force[0])
    return loads


def set_backrest_angle(chair, degrees):
    updated = deepcopy(chair)
    backrest = next(module for module in updated['modules'] if module['name'] == 'Backrest')
    old = math.radians(backrest['pitch_deg'])
    delta = math.radians(degrees) - old
    half_length = backrest['size_m'][0] / 2
    pivot = np.asarray(backrest['center_m']) + half_length * np.array([math.cos(old), 0, -math.sin(old)])
    rotation = np.array([[math.cos(delta), 0, math.sin(delta)], [0, 1, 0],
                         [-math.sin(delta), 0, math.cos(delta)]])
    backrest['center_m'] = (pivot + rotation @ (backrest['center_m'] - pivot)).tolist()
    backrest['pitch_deg'] = updated['backrest_deg'] = degrees
    updated['approach_m'] = (pivot + rotation @ (updated['approach_m'] - pivot)).tolist()
    return updated


def incline_seat_lip(chair, degrees):
    """Keep the rear top edge fixed and raise the front of the seat and pads."""
    if not math.isfinite(degrees) or not 0 < degrees <= 30:
        raise ValueError('Seat lip angle must be greater than zero and at most 30°')
    chair = deepcopy(chair)
    lip = next(module for module in chair['modules'] if module['name'] == 'Seat lip')
    rise = lip['size_m'][0] * math.tan(math.radians(degrees))
    lip['size_m'][2] += rise
    lip['center_m'][2] += rise / 2
    lip['ramp_deg'] = degrees
    for pad in chair['modules']:
        if pad['name'].endswith('seat contact'):
            pad['center_m'][2] += rise / 2
            pad['size_m'][0] /= math.cos(math.radians(degrees))
            pad['pitch_deg'] = -degrees
    return chair


def add_seat_guides(chair, guide_mm):
    """Put cross-slopes beside a flat seat to guide the shroud laterally."""
    entry, run, rise = (mm / 1000 for mm in guide_mm)
    if not all(math.isfinite(m) and m > 0 for m in (entry, run, rise)):
        raise ValueError('Seat guide dimensions must be positive and finite')
    chair = deepcopy(chair)
    lip = next(module for module in chair['modules'] if module['name'] == 'Seat lip')
    height = lip['center_m'][2] + lip['size_m'][2] / 2 + rise
    angle = math.degrees(math.atan2(rise, run))
    for side, sign in (('Left', 1), ('Right', -1)):
        chair['modules'].append({'name': f'{side} seat guide',
                                 'center_m': [lip['center_m'][0], sign * (entry + run / 2), height / 2],
                                 'size_m': [run, lip['size_m'][0], height],
                                 'ramp_deg': angle, 'yaw_deg': sign * 90})
    return chair


def evaluate(design, pose, *, skates=False, approach_start=None, receiver_mass=.008,
             skate_roll=None, rise_roll=None, trigger=None, angle=None, settle_s=PARK_S, pad_inset_m=0,
             roller_release=False, wheel_grip=None, clearance_handoff=False, seat_lip_deg=0,
             slow_skate_gate=None, seat_guides_mm=None, contact_handoff=False, brace_s=0, entry_maneuver=None,
             ground_grip=None, navigate=None):
    chair = DESIGNS.get('chairs', {}).get(design)
    if angle is not None and angle != chair['backrest_deg']:
        chair = set_backrest_angle(chair, angle)
    if entry_maneuver is not None:
        chair = deepcopy(chair)
        chair['modules'].extend(entry_maneuver.fixtures)
    if seat_lip_deg:
        chair = incline_seat_lip(chair, seat_lip_deg)
    if seat_guides_mm is not None:
        if seat_lip_deg or not chair:
            raise ValueError('The seat guides require a flat chair lip')
        chair = add_seat_guides(chair, seat_guides_mm)
    lower_at = trigger if trigger is not None else .175
    if slow_skate_gate is not None and (not skates or not approach_start or not chair or
                                       not (math.isfinite(slow_skate_gate[0]) and 0 < slow_skate_gate[0]
                                            and 0 < slow_skate_gate[1] < lower_at)):
        raise ValueError('The late lowering gate requires a skate approach, speed cutoff and closer trigger')
    if pad_inset_m:
        chair = deepcopy(chair)
        for module in chair['modules']:
            if module['name'].endswith('seat contact'):
                y = module['center_m'][1]
                module['center_m'][1] = y - math.copysign(pad_inset_m / 2, y)
                module['size_m'][1] += pad_inset_m
    surfaces = ({'parent': 'world', **module} for module in chair['modules']) if chair else dock_modules(design)
    shroud_pads = [{'parent': 'trunk_base', **module} for module in (chair or {}).get('shroud_pads', [])]
    modules = [*SHROUD, *surfaces, *shroud_pads]
    modules[1] = {**modules[1], 'mass_kg': receiver_mass - sum(pad['mass_kg'] for pad in shroud_pads)}
    sim = WalkSimulation(.12, 0, configure=lambda spec: build_scene(spec, modules), skates=skates)
    model, data = sim.model, sim.data
    if ground_grip is not None:
        if not math.isfinite(ground_grip) or ground_grip <= 0 or wheel_grip is not None:
            raise ValueError('Specify one positive ground grip coefficient')
        # Equal sliding coefficients on both sides yield the sampled floor/foot contact
        # coefficient with either the foot or wheel collider priority.
        model.geom_friction[[sim.floor, *sim.feet], 0] = ground_grip
    if wheel_grip is not None:
        if not skates or not math.isfinite(wheel_grip) or wheel_grip <= 0:
            raise ValueError('Wheel friction requires skates and a positive, finite coefficient')
        model.geom_friction[list(sim.feet), 0] = wheel_grip
    names = {model.geom(module['name']).id: module['name'] for module in modules}
    bill = model.body('jaw_soft').id
    foot_names = {geom: f'{side.title()} skate' if skates else f'{side.title()} foot'
                  for geom, side in sim.feet.items()}
    wheel_qpos = [int(model.joint(name).qposadr[0]) for name in WHEEL_NAMES] if skates else []
    receiver = model.geom('Receiver').id
    back_support = model.geom('Backrest' if chair else 'Deck').id
    pad_pairs = {
        frozenset(model.geom(f'{side} {suffix} contact').id for suffix in ('seat', 'shroud')): side
        for side in PAD_SIDES
    } if shroud_pads else {}
    trace = []

    def contacts():
        return {names[geom] for contact in data.contact for geom in contact.geom if geom in names}

    def record(phase=None):
        frame = sim.snapshot()
        frame['root'] = [round(value, 6) for value in frame['root']]
        frame['joints_rad'] = {key: round(value, 6) for key, value in frame['joints_rad'].items()}
        frame['footfalls'] = sim.footfalls.copy()
        if skates:
            frame['wheels_rad'] = [round(float(data.qpos[index]), 6) for index in wheel_qpos]
        frame['module_contacts'] = sorted(contacts())
        push_off = set()
        for contact in data.contact:
            a, b = contact.geom
            if model.geom_bodyid[a] != 0:
                a, b = b, a
            if model.geom_bodyid[a] != 0:
                continue
            label = 'Bill' if model.geom_bodyid[b] == bill else foot_names.get(b)
            if label:
                push_off.add(f'{label} on {names.get(a, "floor").lower()}')
        if push_off:
            frame['push_off'] = sorted(push_off)
        if phase:
            frame['recovery']['phase'] = phase
        if trace and trace[-1]['time_s'] == frame['time_s']:
            trace[-1] = frame
        else:
            trace.append(frame)

    stages = chair.get('rise_stages', {}).get('skates' if skates else 'feet') if chair else None
    approach_reached = None
    lowering_speed = None
    if approach_start is not None:
        approach_reached, lower_at, lowering_speed = back_into_chair(
            sim, approach_start, chair, stages, skates=skates, record=record, skate_roll=skate_roll,
            trigger=trigger, slow_skate_gate=slow_skate_gate, entry_maneuver=entry_maneuver, navigate=navigate)

    pitch, y, yaw = pose
    if chair:
        pitch += 90 - chair['backrest_deg']
    pitch_rotation, yaw_rotation, orientation = (np.empty(4) for _ in range(3))
    mj.mju_axisAngle2Quat(pitch_rotation, np.array([0., 1, 0]), -math.radians(pitch))
    mj.mju_axisAngle2Quat(yaw_rotation, np.array([0., 0, 1]), math.radians(yaw))
    mj.mju_mulQuat(orientation, yaw_rotation, pitch_rotation)
    transmitter = np.array(DESIGNS['transmitter_m'] if not chair else chair['transmitter_m'])
    normal = np.array([0., 0, 1]) if not chair else np.array([
        math.sin(math.radians(chair['backrest_deg'])), 0, math.cos(math.radians(chair['backrest_deg']))])
    if chair and approach_start is None:
        # Start on the docking approach, just clear of the backrest.
        nominal = math.radians(90 - chair['backrest_deg'])
        rotation = np.array([math.cos(nominal / 2), 0, -math.sin(nominal / 2), 0])
        receiver_from_root = np.zeros(3)
        mj.mju_rotVecQuat(receiver_from_root, np.array(SHROUD[1]['center_m']), rotation)
        approach = np.array(chair.get('approach_m', chair['transmitter_m']))
        start = approach + .012 * normal - receiver_from_root + [0, y, 0]
        data.qpos[sim.root:sim.root + 7] = [*start, *orientation]
        data.qvel[sim.root_dof:sim.root_dof + 3] = -.08 * normal
    elif approach_start is None:
        data.qpos[sim.root:sim.root + 7] = [0, y, 0, *orientation]
        mj.mj_forward(model, data)
        deck_height = DESIGNS['deck']['size_m'][2]
        data.qpos[sim.root + 2] = max(-minimum_height(model, data), .082 + deck_height) + .012
        data.qvel[sim.root_dof + 4] = -.5
    gain, bias = model.actuator_gainprm.copy(), model.actuator_biasprm.copy()
    if brace_s and approach_reached:
        # Transfer weight to the seat from the achieved bend. Holding the
        # scripted angle targets here can push the Duck off the pads.
        data.ctrl[sim.actuators] = data.qpos[sim.qpos]
        brace_steps = round(brace_s / STEP_S)
        for step in range(1, brace_steps + 1):
            support = 1 - smoothstep(step / brace_steps)
            model.actuator_gainprm[:] = gain * support
            model.actuator_biasprm[:] = bias * support
            mj.mj_step(model, data)
            if step % 8 == 0:
                record('bracing')
    model.actuator_gainprm.fill(0)
    model.actuator_biasprm.fill(0)
    mj.mj_forward(model, data)
    if not trace:
        record('parking')
    settling_steps = round(settle_s / STEP_S) if approach_reached is not False else 0
    samples = []
    for step in range(1, settling_steps + 1):
        mj.mj_step(model, data)
        if step % 8 == 0 and step < settling_steps:
            record('parking')
            if pad_pairs and settling_steps - step <= round(.20 / STEP_S):
                samples.append(pad_loads(model, data, pad_pairs))
    mj.mj_forward(model, data)
    parked_at = data.time
    centre = data.geom_xpos[receiver]
    coil_normal = normal
    if chair and 'transmitter_pitch_deg' in chair:
        angle = math.radians(chair['transmitter_pitch_deg'])
        coil_normal = np.array([math.sin(angle), 0, math.cos(angle)])
    gap = float((centre - transmitter) @ coil_normal) * 1000
    offset = float(np.linalg.norm(centre - transmitter - gap / 1000 * coil_normal)) * 1000
    tilt = math.degrees(math.acos(np.clip(data.geom_xmat[receiver, ::3] @ coil_normal, -1, 1)))
    bumper_contacts = {names.get(b if a == back_support else a)
                       for contact in data.contact for a, b in [contact.geom] if back_support in (a, b)}
    cassette_contact = 'Receiver' in contacts()
    aligned = offset <= 10 and tilt <= 5 and 0 < gap <= 8 and not cassette_contact
    support_names = {'Seat lip', 'Backrest', 'Left seat contact', 'Right seat contact'}
    seated = approach_reached is not False and (approach_start is None
                 or bool(support_names & contacts() and data.qpos[sim.root + 2] > .085))
    aligned = aligned and seated
    contact_loads = {}
    both_pads_loaded = None
    if pad_pairs:
        samples.append(pad_loads(model, data, pad_pairs))
        contact_loads = {side: round(min(sample[side] for sample in samples), 2) for side in PAD_SIDES}
        both_pads_loaded = seated and min(contact_loads.values()) >= .1
    record('parked' if seated else 'approach_missed')
    parked_xy = data.qpos[sim.root:sim.root + 2].copy()
    model.actuator_gainprm[:] = gain
    model.actuator_biasprm[:] = bias
    elapsed = 0
    release = None
    sim.recovery.reset()
    sim.fall_at_s = sim.getup_at_s = sim.resumed_at_s = None
    if roller_release and seated:
        from skate_dock_exit import roll_off_fixed_pad
        release = roll_off_fixed_pad(sim, record, clearance_handoff=clearance_handoff,
                                     contact_handoff=contact_handoff)
    elif chair and seated:
        sim.recovery.phase = 'getup'
        if stages:
            elapsed = chair_rise(sim, stages, record, skate_roll=rise_roll)
        if sim.recovery.phase == 'getup':
            sim.getup_at_s = round(data.time, 3)
    xy = slice(sim.root, sim.root + 2)
    walk_started = None if sim.resumed_at_s is None else data.qpos[xy].copy()
    recovery_slots = round(RECOVERY_S / SLOT_S) if seated and release is None else 0
    for slot in range(elapsed + 1, recovery_slots + 1):
        sim.tick()
        if sim.resumed_at_s is None:
            walk_started = None
        elif walk_started is None:
            walk_started = data.qpos[xy].copy()
        if slot % 4 == 0:
            waking = sim.fall_at_s is None and sim.getup_at_s is None and sim.resumed_at_s is None
            record('waking' if waking else None)
    dx = 0 if walk_started is None else float(np.linalg.norm(data.qpos[xy] - walk_started))
    recovered = sim.resumed_at_s is not None and data.time - sim.resumed_at_s >= 1 and dx >= .10
    exit_shift = None if walk_started is None else (walk_started - parked_xy) * 1000
    handoff = sim.resumed_at_s if recovered else round(data.time, 3)
    side_tilt = max(abs(2 * (frame['root'][3] * frame['root'][4] + frame['root'][5] * frame['root'][6]))
                    for frame in trace if round(parked_at, 3) <= frame['time_s'] <= handoff)
    side_tilt_deg = round(math.degrees(math.asin(min(side_tilt, 1))), 1)
    if release is not None:
        dx = release['after_handoff_m']
        recovered = release['upright_exit']
        side_tilt_deg = release['side_tilt_deg']
        exit_shift = (np.array([release['handoff_x_m'] - parked_xy[0], release['sideways_m']]) * 1000
                      if release['handoff'] else None)
    return dict(
        dock=dict(chair=bool(chair), skates=skates, approach_reached=approach_reached,
                  seated=seated, receiver_mass_g=round(receiver_mass * 1000, 1),
                  contact_force_n=contact_loads if pad_pairs else None, pads_loaded=both_pads_loaded,
                  backrest_deg=chair['backrest_deg'] if chair else None, skate_roll=skate_roll, rise_roll=rise_roll,
                  seat_trigger_m=lower_at, settling_s=settle_s, seat_lip_deg=seat_lip_deg,
                  seat_guides_mm=seat_guides_mm,
                  brace_s=brace_s,
                  lowering_speed_mps=round(lowering_speed, 4) if lowering_speed is not None else None,
                  pad_inset_mm=pad_inset_m * 1000, roller_release=release,
                  approach_speed_mps=None if approach_start is None else approach_start[3],
                  offset_mm=round(offset, 1), tilt_deg=round(tilt, 1), gap_mm=round(gap, 1),
                  aligned=aligned, recovered=recovered, walked_m=round(dx, 3),
                  headward_mm=None if exit_shift is None else round(-float(exit_shift[0])),
                  sideways_mm=None if exit_shift is None else round(abs(float(exit_shift[1]))),
                  side_tilt_deg=side_tilt_deg,
                  bumpers_on_support=sum(side in bumper_contacts for side in ('Left bumper', 'Right bumper')),
                  receiver_contact=cassette_contact),
        passed=(both_pads_loaded if pad_pairs else aligned) and recovered and seated,
        recovered_s=round(sim.resumed_at_s - parked_at, 2) if recovered else None,
        modules=modules, trace=trace,
    )


def write_report(path, report):
    path.write_text(json.dumps(report, separators=(',', ':'), allow_nan=False) + '\n', encoding='utf8')


def write_browser_recordings(report):
    assets = ROOT / 'assets/sim'
    flat, chairs, approaches = {}, {}, {}
    for name, trials in report.items():
        for scenario, trial in trials.items():
            dock = trial['dock']
            group = (approaches if dock['approach_reached'] is not None else chairs if dock['chair'] else flat)
            group.setdefault(name, {})[scenario] = trial
    for filename, data in [('floor-dock-recording.json', flat), ('chair-dock-recording.json', chairs),
                           ('dock-approach-recording.json', approaches)]:
        write_report(assets / filename, data)


def fixed_pad_recordings(*, refinements=False):
    report = {}
    near = ('Centred entry', '8 mm left', '8 mm right', 'Angled left', 'Angled right')
    approaches = ('centred', 'left', 'right', 'yaw left', 'yaw right')
    profiles = [(name, dict(skates=skates, angle=angle, skate_roll=roll, rise_roll=roll, trigger=trigger))
                for name, skates, angle, roll, trigger in FIXED_PAD_PROFILES]
    if refinements:
        profiles = [
            ('Fixed pad chair · Wider pads', dict(angle=45, settle_s=2.6, pad_inset_m=.008)),
            ('Fixed pad chair · Wider pads 40°', dict(angle=40, settle_s=2.6, pad_inset_m=.008)),
            ('Fixed pad chair · Wider pads, skates', dict(skates=True, angle=45, trigger=.165,
                                                         settle_s=2.6, pad_inset_m=.008)),
            ('Fixed pad chair · Skate roll-off', dict(skates=True, angle=40, skate_roll=.08, roller_release=True)),
            ('Fixed pad chair · Wider pads and skate roll-off', dict(skates=True, angle=40, skate_roll=.08,
                                                                    roller_release=True, settle_s=2.6, pad_inset_m=.008)),
        ]
    for name, settings in profiles:
        exits = {case: evaluate('Fixed pad chair', CHAIR_CASES[case], **settings) for case in near}
        docks = {}
        for case in approaches:
            x, y, yaw, _ = APPROACH_CASES[f'Approach · {case}']
            start = (x, y, yaw, .28 if settings.get('skates') else .16)
            docks[f'Pad approach · {case}'] = evaluate('Fixed pad chair', (0, 0, 0), approach_start=start, **settings)
        report[name] = {**exits, **docks}
        loaded = sum(trial['dock']['pads_loaded'] for trial in docks.values())
        upright = sum(trial['dock']['recovered'] and trial['dock']['side_tilt_deg'] <= 25 for trial in exits.values())
        print(f'{name}: {loaded}/{len(docks)} approaches loaded both pads, '
              f'{upright}/{len(exits)} exits passed the 25° side tilt screen')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path, help='Write a Duck Lab replay JSON file')
    parser.add_argument('--browser-recordings', action='store_true', help='Refresh Duck Lab’s built-in replays')
    parser.add_argument('--fixed-pad-recordings', action='store_true', help='Refresh the unpowered fixed-contact replays')
    parser.add_argument('--contact-refinements', action='store_true', help='Record wider pads and the roller release')
    parser.add_argument('--chairs-only', action='store_true', help='Skip flat tray trials')
    parser.add_argument('--design', choices=[*DESIGNS['designs'], *DESIGNS['chairs']],
                        help='Compare both footwear setups for a single chair')
    parser.add_argument('--cassette-mass-g', type=float, nargs='+',
                        help='Screen the original low chair at the given cassette masses')
    args = parser.parse_args()
    if args.contact_refinements:
        output = args.trace or ROOT / 'assets/sim/contact-refinements-recording.json'
        write_report(output, fixed_pad_recordings(refinements=True))
        return
    if args.fixed_pad_recordings:
        write_report(args.trace or ROOT / 'assets/sim/contact-dock-recording.json', fixed_pad_recordings())
        return
    if args.browser_recordings and (args.chairs_only or args.design or args.cassette_mass_g):
        parser.error('--browser-recordings requires the complete dock sweep')
    report = {}
    if args.cassette_mass_g:
        for grams in args.cassette_mass_g:
            if not math.isfinite(grams) or grams <= 0:
                parser.error('Cassette masses must be positive and finite')
            for skates in (False, True):
                label = f'{grams:g} g cassette · {"Skates" if skates else "Feet"}'
                trials = {case: evaluate('Low chair', CHAIR_CASES[case], skates=skates, receiver_mass=grams / 1000)
                          for case in ('Centred entry', '8 mm left', '8 mm right')}
                report[label] = trials
                print(f'{label}: {sum(trial["passed"] for trial in trials.values())}/{len(trials)} '
                      f'seated alignment and exit, {sum(trial["dock"]["recovered"] for trial in trials.values())} exits')
        if args.trace:
            write_report(args.trace, report)
        return

    print(f'{"Design":<27} Alignment  Rise and exit  Both')
    chairs = DESIGNS['chairs']
    flat_docks = [] if args.chairs_only else list(DESIGNS['designs'])
    names = [args.design] if args.design else [*flat_docks, *chairs]
    for name in names:
        cases = CHAIR_CASES if name in chairs else CASES
        for skates in (False, True) if name in chairs or name == 'Rails + foot pad' else (False,):
            label = f'{name} · Skates' if skates else name
            trials = {case: evaluate(name, pose, skates=skates) for case, pose in cases.items()}
            report[label] = trials
            counts = [sum(trial['dock'][key] for trial in trials.values()) for key in ('aligned', 'recovered')]
            print(f'{label:<27} {counts[0]}/{len(cases):<10} {counts[1]}/{len(cases):<13} '
                  f'{sum(trial["passed"] for trial in trials.values())}/{len(cases)}')
            if name in APPROACH_CHAIRS:
                approaches = {case: evaluate(name, (0, 0, 0), skates=skates, approach_start=start)
                              for case, start in APPROACH_CASES.items()}
                report[label].update(approaches)
                reached = sum(trial['dock']['approach_reached'] for trial in approaches.values())
                seated = sum(trial['dock']['seated'] for trial in approaches.values())
                completed = sum(trial['passed'] for trial in approaches.values())
                print(f'  Approach ({len(approaches)}): {reached} reached, {seated} seated, {completed} full cycles')
    if args.trace:
        write_report(args.trace, report)
    if args.browser_recordings:
        write_browser_recordings(report)


if __name__ == '__main__':
    main()
