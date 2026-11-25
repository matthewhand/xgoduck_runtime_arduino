"""Continuous qualification scenarios using the installed Duck policies."""

import math
from collections import deque

from skate_dock_exit import roller_target
from walk_sim import RUN_S, SLOT_S, SUBSTEPS, WHEEL_NAMES

LANE_M = .15
CRUISE_COMMAND = .4
BRAKE_COMMAND = -.12
GATE_DEADLINE_S = .8
SHOVE_N = 12.
SHOVE_S = .12
SHOVE_HEIGHT_M = .075
WHEEL_GEOMS = {'LF': 'left_front_tire_collision', 'RF': 'right_front_tire_collision'}


def mark(events, event_id, label, at_s):
    events.append(dict(id=event_id, label=label, time_s=round(at_s, 3)))


def heading(sim):
    w, x, y, z = sim.data.qpos[sim.root + 3:sim.root + 7]
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y*y + z*z))


def wheel_normal_load(sim, wheel_geom):
    model, data, mj = sim.model, sim.data, sim.mj
    force = sim.np.zeros(6)
    total = 0.
    for index, contact in enumerate(data.contact):
        a, b = contact.geom
        if (a == sim.floor and b == wheel_geom) or (b == sim.floor and a == wheel_geom):
            mj.mj_contactForce(model, data, index, force)
            total += float(force[0])
    return total


def wheel_jam_release(sim, case, capture, tilt, engage_lock, load_roller):
    mj, np, model, data = sim.mj, sim.np, sim.model, sim.data
    fault, variant = case['fault'], case['scenario']['variant']
    wheel = fault['jam'] if 'jam' in fault else fault['jam_wheel']
    matched = variant == 'matched-control'
    candidate = variant == 'simulated-brake'
    wheels = [int(model.joint(name).qposadr[0]) for name in WHEEL_NAMES]
    target_wheel = model.geom(WHEEL_GEOMS[wheel]).id
    mj.mj_resetDataKeyframe(model, data, model.key('home').id)
    mj.mj_forward(model, data)
    policy = load_roller()
    lane_slots = round(1 / SLOT_S)
    stop_slots = round(.5 / SLOT_S)
    jam_slots = round(fault['jam_s'] / SLOT_S)
    first_slot = round(fault['at_s'] / SLOT_S)
    last_slot = first_slot + round(GATE_DEADLINE_S / SLOT_S)
    run_slots = max(round(6 / SLOT_S), last_slot + jam_slots + lane_slots)
    metrics = dict(gate_at_s=None, forward_speed_at_gate_m_s=None, target_wheel_load_n=None,
                   jam_at_s=None, release_at_s=None, evaluate_at_s=None, lane_breached_at_s=None,
                   lane_stable_at_s=None, lane_returned_at_s=None,
                   stopped_at_s=None, stop_distance_m=None, axle_motion_deg=None)
    phase = 'Build forward speed'
    trace = [dict(capture(sim, case, wheels=wheels), scenario_phase=phase)]
    events = []
    gate_slot = lock = None
    forward = max_side = peak = lock_travel = travelled_after_release = 0.
    moving_slots = still_slots = 0
    lane_history = deque(maxlen=lane_slots)
    steady_lane = False
    failure = failed_at = None
    fell = False
    start_xy = data.qpos[sim.root:sim.root + 2].copy()
    xy = start_xy
    # The position feedback and exact trigger used by the brake candidate come from MuJoCo.
    for slot in range(run_slots):
        if gate_slot is None:
            forward_speed = float(data.qvel[sim.root_dof])
            moving_slots = moving_slots + 1 if forward_speed >= .25 and tilt(sim) <= 15 else 0
            if slot >= first_slot and moving_slots >= round(.10 / SLOT_S) and forward >= .35:
                mj.mj_forward(model, data)
                load = wheel_normal_load(sim, target_wheel)
                if load >= 1.:
                    gate_slot = slot
                    at_s = round(data.time, 3)
                    metrics.update(gate_at_s=at_s, forward_speed_at_gate_m_s=forward_speed, target_wheel_load_n=load)
                    mark(events, 'wheel-loaded', 'Rolling with target wheel loaded', at_s)
                    if matched:
                        phase = 'Matched control window'
                    else:
                        lock = engage_lock(sim, wheel)
                        metrics['jam_at_s'] = at_s
                        phase = 'Wheel locked'
                        mark(events, 'wheel-jammed', 'Wheel jammed', at_s)
            if gate_slot is None and slot >= last_slot:
                mark(events, 'gate-missed', 'Rolling and load gate missed', data.time)
                break

        if gate_slot is not None and slot == gate_slot + jam_slots:
            at_s = round(data.time, 3)
            metrics['evaluate_at_s'] = at_s
            phase = 'Checking for a stop' if candidate else 'Checking lane travel'
            if lock is not None:
                data.eq_active[lock[0]] = 0
                metrics['release_at_s'] = at_s
                mark(events, 'wheel-released', 'Wheel released', at_s)
            else:
                mark(events, 'matched-release', 'Matched release time', at_s)

        evaluating = metrics['evaluate_at_s'] is not None
        vx = (0. if evaluating else BRAKE_COMMAND) if candidate and lock is not None else CRUISE_COMMAND
        target_heading = math.atan2(-(xy[1] - start_xy[1]), .35)
        yaw = max(-.45, min(.45, 1.8 * math.remainder(target_heading - heading(sim), math.tau)))
        data.ctrl[sim.actuators] = roller_target(sim, policy, [vx, 0, yaw])
        floor_hit = False
        wheel_contact = False
        lane_geometry_safe = True
        peak_speed = distance = 0.
        substep_xy = xy
        for _ in range(SUBSTEPS):
            mj.mj_step(model, data)
            floor_hit_now = False
            for contact in data.contact:
                a, b = contact.geom
                other = b if a == sim.floor else a if b == sim.floor else None
                if other in sim.feet and contact.dist <= 0.:
                    wheel_contact = True
                elif other is not None and other not in sim.feet and contact.dist < -.00015:
                    floor_hit_now = True
            floor_hit |= floor_hit_now
            qpos = data.qpos[sim.root:sim.root + 3]
            angle = tilt(sim)
            side = abs(float(qpos[1] - start_xy[1]))
            if evaluating:
                distance += float(np.linalg.norm(qpos[:2] - substep_xy))
                substep_xy = qpos[:2].copy()
                peak_speed = max(peak_speed, float(np.linalg.norm(data.qvel[sim.root_dof:sim.root_dof + 2])))
                lane_geometry_safe &= side <= LANE_M and angle <= 15 and abs(heading(sim)) <= math.radians(20)
            peak, max_side = max(peak, angle), max(max_side, side)
            if side > LANE_M and metrics['lane_breached_at_s'] is None:
                metrics['lane_breached_at_s'] = round(data.time, 3)
                mark(events, 'lane-breached', 'Left the 15 cm lane', data.time)
            fell = angle > 45 or qpos[2] < .085
            if failure is None:
                failure = ('Fell during skate trial' if fell else 'Body touched floor' if floor_hit_now
                           else 'Drifted over 15 cm' if side > LANE_M else None)
                if failure is not None:
                    failed_at = round(data.time, 3)
                    mark(events, 'first-failure', failure, failed_at)
            if fell:
                phase = 'Fallen'
                mark(events, 'skate-fall', 'Fallen · roller get-up unqualified', data.time)
                break
        if not np.isfinite(data.qpos).all():
            raise ValueError('Roller simulation produced non-finite physics')

        next_xy = data.qpos[sim.root:sim.root + 2].copy()
        if lock is not None and not evaluating:
            lock_travel = max(lock_travel, abs(float(data.qpos[lock[1]]) - lock[2]))
        if evaluating and not fell:
            travelled_after_release += distance
            upright = not floor_hit and angle <= 15 and qpos[2] >= .10
            if upright and lane_geometry_safe:
                lane_history.append((float(next_xy[0] - xy[0]), wheel_contact))
            else:
                lane_history.clear()
            # A swizzle stride may briefly unload every tire while remaining in balance.
            steady_lane = (len(lane_history) == lane_slots and
                           sum(step[0] for step in lane_history) >= .10 and
                           sum(step[1] for step in lane_history) >= .70 * lane_slots)
            narrow_stop = upright and wheel_contact and peak_speed < .03
            still_slots = still_slots + 1 if narrow_stop else 0
            if steady_lane and metrics['lane_stable_at_s'] is None:
                metrics['lane_stable_at_s'] = round(data.time, 3)
                mark(events, 'lane-stable', 'Sustained lane travel', data.time)
            if steady_lane and metrics['lane_breached_at_s'] is not None and metrics['lane_returned_at_s'] is None:
                metrics['lane_returned_at_s'] = round(data.time, 3)
                mark(events, 'lane-returned', 'Sustained lane travel after breach', data.time)
            if steady_lane and not candidate:
                phase = 'Sustained lane travel'
            elif not candidate:
                phase = 'Checking lane travel'
            if still_slots == stop_slots and metrics['stopped_at_s'] is None:
                metrics.update(stopped_at_s=round(data.time, 3), stop_distance_m=travelled_after_release)
                mark(events, 'stop-measured', 'Measured stop', data.time)
            if candidate:
                phase = 'Measured stop' if still_slots >= stop_slots else 'Checking for a stop'

        xy = next_xy
        forward = float(xy[0] - start_xy[0])
        if slot % 2 == 1 or fell:
            trace.append(dict(capture(sim, case, wheels=wheels), scenario_phase=phase))
        if fell:
            break

    skipped = gate_slot is None and failure is None
    skip_reason = 'Could not establish forward motion with a loaded target wheel' if skipped else None
    if fell:
        outcome = 'Fallen · roller get-up unqualified'
    elif skipped:
        outcome = 'Gate not exercised'
    elif still_slots >= stop_slots:
        outcome = 'Measured stop after a breach' if failure else 'Measured stop'
    elif candidate and metrics['stopped_at_s'] is not None:
        outcome = 'Stopped briefly, then moved again'
    elif candidate:
        outcome = 'No sustained stop'
    elif steady_lane:
        outcome = 'Sustained lane travel after a breach' if failure else 'Sustained lane travel'
    elif metrics['lane_returned_at_s'] is not None:
        outcome = 'Returned to lane briefly'
    else:
        outcome = 'No sustained lane travel'
    if not skipped and failure is None and (still_slots < stop_slots if candidate else not steady_lane):
        failure = 'Did not sustain a measured stop' if candidate else 'Did not sustain lane travel'
        failed_at = round(data.time, 3)
        mark(events, 'first-failure', failure, failed_at)
    if lock is not None:
        metrics['axle_motion_deg'] = math.degrees(lock_travel)
    return dict(trace=trace, events=events, outcome=outcome, skipped=skipped, skip_reason=skip_reason,
                failure=failure, failed_at_s=failed_at, forward_m=forward, peak_tilt_deg=peak,
                max_side_m=max_side, scenario_metrics=metrics)


def walking_fall_recovery(sim, case, capture, tilt):
    np, data = sim.np, sim.data
    fault = case['fault']
    first_slot = round(fault['at_s'] / SLOT_S)
    last_slot = first_slot + round(GATE_DEADLINE_S / SLOT_S)
    shove_slots = round(SHOVE_S / SLOT_S)
    start_xy = data.qpos[sim.root:sim.root + 2].copy()
    phase = 'Walk before shove'
    trace = [dict(capture(sim, case), scenario_phase=phase)]
    events = []
    shove_slot = fall_at = getup_at = resumed_at = failed_at = None
    applied_wrench = data.xfrc_applied[sim.trunk].copy()
    resume_xy = resume_heading = None
    previous_landing = None
    previous_contacts = set()
    alternating = 0
    resumed_feet = dict(left=0, right=0)
    peak = max_side = 0.
    failure = None
    fell_again = False

    def observe_contacts(simulation, contacts):
        nonlocal previous_contacts, previous_landing, alternating
        landed = contacts - previous_contacts
        previous_contacts = contacts
        if simulation.recovery.phase != 'walk' or simulation.resumed_at_s is None:
            return
        for foot in landed:
            resumed_feet[foot] += 1
        if len(landed) == 1:
            foot = next(iter(landed))
            alternating += int(previous_landing is not None and previous_landing != foot)
            previous_landing = foot
        elif len(landed) > 1:
            previous_landing = None

    try:
        for slot in range(round(RUN_S / SLOT_S)):
            xy = data.qpos[sim.root:sim.root + 2].copy()
            if shove_slot is None and slot >= first_slot:
                walking = (sim.recovery.phase == 'walk' and tilt(sim) < 15 and
                           float(np.linalg.norm(xy - start_xy)) >= .15 and min(sim.footfalls.values()) >= 2)
                if walking:
                    shove_slot = slot
                    theta = heading(sim)
                    forward_x, forward_y = math.cos(theta), math.sin(theta)
                    fx, fy = (-forward_x, -forward_y) if fault['tip'] == 'back' else (forward_y, -forward_x)
                    fx, fy = SHOVE_N * fx, SHOVE_N * fy
                    data.xfrc_applied[sim.trunk] = applied_wrench + (
                        fx, fy, 0., -SHOVE_HEIGHT_M * fy, SHOVE_HEIGHT_M * fx, 0.)
                    phase = 'Shoved while walking'
                    mark(events, 'shove', f"{fault['tip'].capitalize()} shove", data.time)
                elif slot >= last_slot:
                    mark(events, 'gate-missed', 'Walking gate missed', data.time)
                    break
            if shove_slot is not None and slot == shove_slot + shove_slots:
                data.xfrc_applied[sim.trunk] = applied_wrench
                mark(events, 'shove-ended', 'Shove ended', data.time)

            previous_phase = sim.recovery.phase
            previous_heading = heading(sim)
            sim.tick(observe_contacts=observe_contacts)
            current = sim.recovery.phase
            if current != previous_phase:
                if current == 'default_pose':
                    if fall_at is not None:
                        fell_again = True
                        phase = 'Fell again'
                        mark(events, 'second-fall', 'Fell again after walking resumed', sim.fall_at_s)
                        if failure is None:
                            failure = 'Fell again after walking resumed'
                            failed_at = sim.fall_at_s
                            mark(events, 'first-failure', failure, failed_at)
                    else:
                        fall_at = sim.fall_at_s
                        phase = 'Fall detected'
                        mark(events, 'fall-detected', 'Fall detected', fall_at)
                elif current == 'getup':
                    getup_at = sim.getup_at_s
                    phase = 'Get-up policy'
                    mark(events, 'getup', 'Get-up policy took over', getup_at)
                else:
                    resumed_at, resume_xy, resume_heading = sim.resumed_at_s, xy, previous_heading
                    phase = 'Walking resumed'
                    mark(events, 'walk-resumed', 'Walking policy resumed', resumed_at)
            if failure is None and fall_at is not None and resumed_at is None and data.time > fall_at + 8 + 1e-8:
                failure = 'Recovery exceeded 8 seconds from fall detection'
                failed_at = round(data.time, 3)
                mark(events, 'first-failure', failure, failed_at)
            peak = max(peak, tilt(sim))
            max_side = max(max_side, abs(float(data.qpos[sim.root + 1] - start_xy[1])))
            if slot % 2 == 1 or fell_again:
                trace.append(dict(capture(sim, case), scenario_phase=phase))
            if fell_again:
                break
    finally:
        data.xfrc_applied[sim.trunk] = applied_wrench

    skipped = shove_slot is None or fall_at is None
    if shove_slot is None:
        skip_reason = 'Could not establish walking before the shove'
    elif fall_at is None:
        skip_reason = 'Stayed upright after the shove; get-up policy was not exercised'
    else:
        skip_reason = None
    xy = data.qpos[sim.root:sim.root + 2]
    resumed_forward = recovery_s = None
    if resumed_at is not None:
        direction = (math.cos(resume_heading), math.sin(resume_heading))
        resumed_forward = float((xy - resume_xy) @ direction)
        recovery_s = round(resumed_at - fall_at, 3)
    if not skipped and failure is None:
        upright = sim.recovery.phase == 'walk' and tilt(sim) < 25 and data.qpos[sim.root + 2] >= .10
        if resumed_at is None or not upright:
            failure = 'Did not regain upright walking'
        elif recovery_s > 8.:
            failure = 'Recovery took over 8 seconds from fall detection'
        elif resumed_forward < .75:
            failure = 'Moved less than 0.75 m forward after recovery'
        elif min(resumed_feet.values()) < 5 or alternating < 5:
            failure = 'Did not resume alternating footfalls'
        if failure is not None:
            failed_at = float(data.time)
            mark(events, 'first-failure', failure, failed_at)
    outcome = ('Gate not exercised' if skipped else 'Did not regain upright walking'
               if resumed_at is None else failure or 'Got up and walked forward')
    shove_at = next((event['time_s'] for event in events if event['id'] == 'shove'), None)
    metrics = dict(shove_at_s=shove_at, shove_n=SHOVE_N, shove_s=SHOVE_S, shove_height_m=SHOVE_HEIGHT_M,
                   fall_at_s=fall_at, getup_at_s=getup_at, walk_resumed_at_s=resumed_at, recovery_s=recovery_s,
                   resumed_forward_m=resumed_forward, resumed_footfalls=resumed_feet,
                   alternating_footfalls=alternating, transitions=sim.recovery.transitions)
    return dict(trace=trace, events=events, outcome=outcome, skipped=skipped, skip_reason=skip_reason,
                failure=failure, failed_at_s=failed_at, forward_m=float(xy[0] - start_xy[0]),
                max_side_m=max_side, peak_tilt_deg=peak, recovered_s=recovery_s, scenario_metrics=metrics)


def run_scenario(sim, case, *, capture, tilt, engage_lock, load_roller):
    if case['scenario']['kind'] == 'wheel-jam-release':
        return wheel_jam_release(sim, case, capture, tilt, engage_lock, load_roller)
    return walking_fall_recovery(sim, case, capture, tilt)
