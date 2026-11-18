"""Qualify the fixed lowering-point clear-lane controller on paired, held-out approaches."""
import argparse
from collections import Counter
import math
from pathlib import Path
import random
import runpy

dock = runpy.run_path(str(Path(__file__).with_name('check-floor-dock.py')))
SEED = 20261118
COUNT = 100
TARGET = 95
CASE = 'Clear lane · 100 approaches per footwear'


def approaches():
    rng = random.Random(SEED)
    # Independently stratify each dimension. Both footwear modes use the same row.
    columns = []
    for _ in range(5):
        column = [(i + rng.random()) / COUNT for i in range(COUNT)]
        rng.shuffle(column)
        columns.append(column)
    for index, (offset, yaw, speed, grip, mass) in enumerate(zip(*columns), 1):
        yield dict(id=index, lateral_mm=round(-15 + 30*offset, 3), yaw_deg=round(-7 + 14*yaw, 3),
                   foot_speed=round(.12 + .08*speed, 5), skate_speed=round(.22 + .12*speed, 5),
                   ground_grip=round(.70 + .45*grip, 5), receiver_g=round(6 + 8*mass, 3))


def outcome(result):
    d = result['dock']
    if not d['approach_reached']:
        return 'Missed lowering point'
    if not d['seated']:
        return 'Missed seat'
    if not d['pads_loaded']:
        return 'One pad unloaded' if max(d['contact_force_n'].values()) >= .1 else 'Both pads unloaded'
    release = d['roller_release']
    if release and not release['handoff']:
        return 'Skating policy did not start'
    if d['side_tilt_deg'] > 25:
        return 'Exceeded 25° side tilt'
    if not d['recovered']:
        return 'Incomplete upright departure'
    if release and not release['wheels_only_exit']:
        return 'Floor brace or chair recontact'
    # Include the walking phase after the rise: a subsequent fall and recovery
    # does not count as a clean exit. The trace is sampled at 80 ms or better.
    walking = False
    for frame in result['trace']:
        phase = frame['recovery']['phase']
        if phase == 'walk':
            walking = True
        if walking:
            w, x, y, z = frame['root'][3:]
            if phase != 'walk' or 1-2*(x*x+y*y) < .85 or abs(2*(w*x+y*z)) > math.sin(math.radians(25)):
                return 'Lost balance after handoff'
    tail = result['trace'][-1]['root']
    if tail[0] <= .24 or 1-2*(tail[4]**2 + tail[5]**2) < .95:
        return 'Missed upright forward clearance'
    return 'Clean exit'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--recording', type=Path, required=True)
    args = parser.parse_args()
    rows, examples = {}, {}
    for footwear in ('Feet', 'Skates'):
        skates = footwear == 'Skates'
        rows[footwear] = entries = []
        first = {}
        for params in approaches():
            speed = params['skate_speed' if skates else 'foot_speed']
            result = dock['evaluate']('Fixed pad chair', (0, 0, 0), skates=skates, angle=40,
                                      settle_s=2.6, pad_inset_m=.008, trigger=.175, skate_roll=.08 if skates else None,
                                      roller_release=skates, contact_handoff=skates, ground_grip=params['ground_grip'],
                                      receiver_mass=params['receiver_g']/1000,
                                      approach_start=(.32, params['lateral_mm']/1000, params['yaw_deg'], speed))
            reason = outcome(result)
            result['passed'] = reason == 'Clean exit'
            result['dock']['qualification'] = {**params, 'speed_mps': speed, 'outcome': reason}
            entries.append(result['dock'])
            first.setdefault(reason, result)
        counts = Counter(row['qualification']['outcome'] for row in entries)
        print(footwear, dict(counts), flush=True)
        for passed in (True, False):
            reasons = [reason for reason in counts if (reason == 'Clean exit') == passed]
            if reasons:
                result = first[max(reasons, key=counts.get)]
                result['dock']['qualification']['cohort_clean'] = counts['Clean exit']
                examples[f'{footwear} · {"Success" if passed else "Failure"}'] = {CASE: result}
    dock['write_report'](args.results, dict(seed=SEED, trials_per_footwear=COUNT, target=TARGET, cohorts=rows))
    dock['write_report'](args.recording, examples)


if __name__ == '__main__':
    main()
