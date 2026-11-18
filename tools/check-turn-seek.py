"""Turn away from a known chair, seek it in reverse, lower, and attempt departure."""
import argparse
from functools import partial
import math
from pathlib import Path
import runpy

qualify = runpy.run_path(str(Path(__file__).with_name('check-clear-lane.py')))
dock = qualify['dock']
from skate_dock_exit import load_roller_policy, roller_target
from walk_sim import SLOT_S, SUBSTEPS

CASE = 'Turn around and seek backwards'


def clamp(value, limit):
    return max(-limit, min(limit, value))


def navigate(sim, record, skates, speed, trigger, *, rolling, metrics):
    data = sim.data
    policy = load_roller_policy() if skates else None
    phase = 'turn_around'
    record(phase)
    turn_sign = None
    best_error = math.inf
    last_gain = 0
    previous_yaw = None
    travelled_yaw = 0.
    held = 0
    aligned_slots = 0
    start_x, start_y = data.qpos[sim.root:sim.root+2].copy()
    for tick in range(round(24 / SLOT_S)):
        x, y, height, w, qx, qy, qz = data.qpos[sim.root:sim.root + 7]
        yaw = math.atan2(2*(w*qz+qx*qy), 1-2*(qy*qy+qz*qz))
        if turn_sign is None:
            turn_sign = -math.copysign(1., yaw)
            initial_angle = abs(yaw)
        if previous_yaw is not None:
            travelled_yaw += math.remainder(yaw - previous_yaw, 2*math.pi)
        previous_yaw = yaw
        progress = turn_sign*travelled_yaw
        if phase != 'reverse_seek':
            metrics['turned_deg'] = max(metrics['turned_deg'], round(math.degrees(progress), 1))
        metrics['excursion_m'] = max(metrics['excursion_m'], round(math.hypot(x-start_x, y-start_y), 3))
        if height < .085 or 1-2*(qx*qx+qy*qy) < .70 or metrics['excursion_m'] > 1.25:
            metrics['stop'] = 'Lost balance' if metrics['excursion_m'] <= 1.25 else 'Outside test area'
            record(phase)
            return False
        on_heading = abs(yaw) <= math.radians(9) and progress >= initial_angle-math.radians(9)
        if on_heading and phase != 'reverse_seek':
            if not metrics['on_heading']:
                metrics['speed_at_heading'] = round(math.hypot(*data.qvel[sim.root_dof:sim.root_dof+2]), 3)
            metrics['on_heading'] = True
        if skates and phase == 'turn_around' and on_heading:
            phase = 'brake_turn'
            record(phase)
        if phase == 'brake_turn':
            aligned_slots = aligned_slots + 1 if on_heading else 0
            metrics['held_heading'] |= aligned_slots >= round(.4/SLOT_S)
            low_speed = math.hypot(*data.qvel[sim.root_dof:sim.root_dof+2]) <= .12
            held = held+1 if on_heading and low_speed else 0
        if (phase == 'brake_turn' and held >= round(.4/SLOT_S)) or (not skates and phase == 'turn_around' and on_heading):
            phase = 'reverse_seek'
            record(phase)
        if phase == 'reverse_seek' and x <= trigger:
            record(phase)
            return abs(y) < .025 and abs(yaw) < math.radians(12)
        if phase == 'turn_around':
            if initial_angle-progress < best_error - math.radians(4):
                best_error, last_gain = initial_angle-progress, tick
            if tick - last_gain > round(3 / SLOT_S):
                metrics['stop'] = 'Turn stalled'
                record(phase)
                return False
            yaw_rate = turn_sign * 1.4 if abs(yaw) > math.pi/2 else clamp(-2*yaw, 1.4)
            if rolling:
                # The roller policy generates the initial push as well as the arc.
                command = (.24, 0., 0. if tick < 35 else turn_sign*1.4)
            else:
                command = (0., 0., yaw_rate)
        elif phase == 'brake_turn':
            command = (0., 0., clamp(-2*yaw, .8))
            if tick-last_gain > round(4/SLOT_S):
                metrics['stop'] = 'Turn handoff timed out'
                return False
        else:
            # Aim the tail toward the lane and straighten close to the chair.
            aim = clamp(math.atan2(y, max(.09, x-trigger)), .48)
            error = math.atan2(math.sin(aim-yaw), math.cos(aim-yaw))
            command = (-speed, clamp(-1.2*y, .065), clamp(2.5*error, .85))
        if skates:
            data.ctrl[sim.actuators] = roller_target(sim, policy, command)
            sim.mj.mj_step(sim.model, data, nstep=SUBSTEPS)
        else:
            sim.command = command
            sim.tick()
        if tick % 4 == 3:
            record(phase)
    return False


def trial(skates, heading, lateral, speed, start=.38, rolling=False):
    metrics = dict(turned_deg=0., excursion_m=0., on_heading=False, held_heading=False, speed_at_heading=None, stop=None)
    result = dock['evaluate']('Fixed pad chair', (0, 0, 0), skates=skates, angle=40,
                              approach_start=(start, lateral, heading, speed), trigger=.175,
                              pad_inset_m=.008, settle_s=2.6, skate_roll=.08 if skates else None,
                              roller_release=skates, contact_handoff=skates, navigate=partial(navigate, rolling=rolling, metrics=metrics))
    seek = [f for f in result['trace'] if f['recovery']['phase'] == 'reverse_seek']
    outcome = qualify['outcome'](result)
    if not seek:
        outcome = metrics['stop'] or 'Turn incomplete'
    elif not result['dock']['approach_reached']:
        outcome = 'Reverse alignment missed'
    result['passed'] = outcome == 'Clean exit'
    result['dock']['navigation'] = dict(**metrics, outcome=outcome, start_deg=heading, reverse_started=bool(seek),
                                        reverse_m=round(seek[0]['root'][0]-seek[-1]['root'][0], 3) if seek else 0)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recording', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    args = parser.parse_args()
    recordings = {}
    for label, skates, heading, lateral, speed in [
            ('Feet · Clockwise', False, 175, .015, .16),
            ('Feet · Anticlockwise', False, -175, .035, .16),
            ('Skates · Turn and reverse', True, 175, .015, .20)]:
        result = trial(skates, heading, lateral, speed)
        recordings[label] = {CASE: result}
        print(label, result['dock']['navigation'])
    # Compare the same nine facing poses per direction. Keep diagnostic traces
    # for the closest approach to a stable turnaround in each cohort.
    report = {}
    for rolling in (False, True):
        for sign, direction in ((1, 'Clockwise'), (-1, 'Anticlockwise')):
            label = f'{"Rolling arc" if rolling else "Standing pivot"} · {direction}'
            rows = []
            best = None
            for angle in (165, 175, 179):
                for offset in (-.02, 0., .02):
                    r = trial(True, sign*angle, offset, .16, start=.60, rolling=rolling)
                    n = r['dock']['navigation']
                    rows.append({**n, 'offset_m': offset})
                    rank = (r['passed'], n['reverse_started'], n['on_heading'], n['turned_deg'])
                    if best is None or rank > best[0]:
                        best = (rank, r)
            sample = best[1]
            sample['dock']['navigation']['cohort'] = dict(total=len(rows),
                aligned=sum(n['on_heading'] for n in rows), held=sum(n['held_heading'] for n in rows),
                ready=sum(n['reverse_started'] for n in rows))
            recordings[label] = {'Skate turnaround trials': sample}
            report[label] = rows
            print(label, 'on heading', sum(n['on_heading'] for n in rows),
                  'held for reverse', sum(n['reverse_started'] for n in rows), best[1]['dock']['navigation'])
    dock['write_report'](args.results, report)
    dock['write_report'](args.recording, recordings)
