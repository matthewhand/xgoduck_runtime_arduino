"""Sweep approach speed, wheel grip and seated restarts for the 40° skate chair."""
import argparse
from collections import Counter
import itertools
import math
from pathlib import Path
import runpy

TOOLS = Path(__file__).resolve().parent
dock = runpy.run_path(str(TOOLS / 'check-floor-dock.py'))
BASE_SETTINGS = dict(angle=40, skates=True, skate_roll=.08, settle_s=2.6,
                     pad_inset_m=.008, roller_release=True)
SPEEDS = (.18, .22, .25, .28, .30, .32, .36)
APPROACHES = {
    'centred': (0, 0), 'left': (.008, 0), 'right': (-.008, 0),
    'yaw left': (.008, 5), 'yaw right': (-.008, -5),
}
DISTANCE = 'Skate stress · Distance handoff'
CLEARANCE = 'Skate stress · Clearance handoff'


def assess_seated_pose(trial):
    parked = next((frame for frame in trial['trace'] if frame['recovery']['phase'] == 'parked'), None)
    if not parked:
        return None
    w, x, y, z = parked['root'][3:]
    pitch = math.degrees(math.asin(max(-1, min(1, 2 * (w*y - x*z)))))
    roll = math.degrees(math.asin(max(-1, min(1, 2 * (w*x + y*z)))))
    # The two knee actuators use opposite signs for the same physical tuck.
    knees = [-math.degrees(parked['joints_rad'][13]), math.degrees(parked['joints_rad'][23])]
    support = parked.get('push_off', [])
    both_skates = all(f'{side} skate on floor' in support for side in ('Left', 'Right'))
    matches = (trial['dock']['pads_loaded'] and both_skates and -54 <= pitch <= -38 and abs(roll) <= 4
               and all(8 <= knee <= 26 for knee in knees) and abs(knees[0] - knees[1]) <= 5)
    return dict(matches=bool(matches), pitch_deg=round(pitch, 1), roll_deg=round(roll, 1),
                tucked_knees_deg=[round(knee, 1) for knee in knees])


def test(*, pose=(0, 0, 0), approach=None, clearance=True, wheel_grip=1., settle_s=2.6, **overrides):
    settings = {**BASE_SETTINGS, 'settle_s': settle_s}
    trial = dock['evaluate']('Fixed pad chair', pose, approach_start=approach, clearance_handoff=clearance,
                             wheel_grip=wheel_grip, **(settings | overrides))
    result = trial['dock']
    release = result['roller_release'] or {}
    result['pose_screen'] = assess_seated_pose(trial)
    result['wheel_grip'] = wheel_grip
    result['stress_test'] = True
    trial['passed'] = bool(result['pads_loaded'] and release.get('wheels_only_exit'))
    return trial


def summarize(results, group):
    total = len(results)
    reached = sum(bool(result['approach_reached']) for result in results)
    loaded = sum(result['pads_loaded'] for result in results)
    clean = sum(result['full_cycle'] for result in results)
    entry = f'{reached}/{total} reached, ' if any(result['approach_reached'] is not None for result in results) else ''
    print(f'{group}: {entry}{loaded}/{total} both pads, {clean}/{total} clean cycles', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recording', type=Path, help='Export selected trials for Duck Lab')
    parser.add_argument('--results', type=Path, help='Export the complete measurements without replay frames')
    args = parser.parse_args()
    examples = {DISTANCE: {}, CLEARANCE: {}}
    results = {}

    def keep(name, trial, group, *, record=False, variant=CLEARANCE):
        result = {**trial['dock'], 'full_cycle': trial['passed']}
        results.setdefault(group, {})[name] = result
        if record:
            examples[variant][name] = trial

    for speed in SPEEDS:
        for clearance, variant in [(False, DISTANCE), (True, CLEARANCE)]:
            group = f'{speed:.2f} m/s · {"clearance" if clearance else "distance"}'
            for entry, (side, yaw) in APPROACHES.items():
                name = f'Skate approach · {speed:.2f} m/s · {entry}'
                trial = test(approach=(.32, side, yaw, speed), clearance=clearance)
                keep(name, trial, group, record=entry == 'centred' or (speed == .32 and entry == 'left'), variant=variant)
            summarize(list(results[group].values()), group)

    for grip in (.45, .70):
        for speed in (.28, .32):
            group = f'Wheel friction {grip:.2f} · {speed:.2f} m/s'
            for entry, (side, yaw) in APPROACHES.items():
                trial = test(approach=(.32, side, yaw, speed), wheel_grip=grip)
                keep(f'Wheel friction {grip:.2f} · {speed:.2f} m/s · {entry}', trial, group, record=entry == 'centred')
            summarize(list(results[group].values()), group)

    for entry, settle_s in itertools.product(('Centred entry', '8 mm left', '8 mm right', 'Angled left', 'Angled right'),
                                             (2.6, 10.)):
        trial = test(pose=dock['CHAIR_CASES'][entry], settle_s=settle_s)
        keep(f'Seated restart · {settle_s:g} s · {entry.lower()}', trial, 'Preset seating',
             record=entry in ('Centred entry', 'Angled left'))
    for entry, (side, yaw) in APPROACHES.items():
        trial = test(approach=(.32, side, yaw, .28), settle_s=10.)
        keep(f'Approach · 10 s seated · {entry}', trial, 'Approach then 10 s seated', record=entry == 'centred')
    summarize(list(results['Preset seating'].values()), 'Preset seating')
    summarize(list(results['Approach then 10 s seated'].values()), 'Approach then 10 s seated')

    pose_screen = Counter()
    for group, cases in results.items():
        if group.endswith('distance'):
            continue  # Count each physical arrival once in the pose screen.
        for result in cases.values():
            if result['pose_screen'] and result['pads_loaded']:
                pose_screen[result['pose_screen']['matches'], result['full_cycle']] += 1
    print('Pose screen on loaded trials:', dict(sorted(pose_screen.items())), flush=True)
    if args.recording:
        dock['write_report'](args.recording, examples)
    if args.results:
        dock['write_report'](args.results, results)


if __name__ == '__main__':
    main()
