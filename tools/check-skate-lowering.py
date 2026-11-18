"""Compare a speed-based sit and raised chair lips using the shipped roller policy."""
import argparse
from pathlib import Path
import runpy

check = runpy.run_path(str(Path(__file__).with_name('check-dock-robustness.py')))
BEFORE = 'Before · Timed lowering'
AFTER = 'After · Controlled lowering'
SLOW_GATE = (.06, .153)
LIP_ANGLES = (0, 20, 25, 30)
SPEEDS = (.18, .22, .25, .28, .30, .32)
ENTRIES = check['APPROACHES']
HELD_OUT_ENTRIES = {'yaw only left': (0, 4), 'yaw only right': (0, -4),
                    'offset against yaw left': (.006, -3), 'offset against yaw right': (-.006, 3)}


def trial_for(speed, lateral, yaw, *, angle=0, controlled=True, wheel_grip=1., park_s=2.6):
    trial = check['test'](approach=(.32, lateral, yaw, speed), seat_lip_deg=angle,
                          slow_skate_gate=SLOW_GATE if controlled else None,
                          wheel_grip=wheel_grip, settle_s=park_s)
    trial['dock']['lowering_test'] = True
    return trial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recording', type=Path, help='Export selected before, after and raised lip replays')
    parser.add_argument('--results', type=Path, help='Export measurements for all runs')
    args = parser.parse_args()
    results = {}
    recordings = {}

    def report(group, runs, *, variant=None):
        measurements = {}
        for name, trial, record in runs:
            measurements[name] = {**trial['dock'], 'full_cycle': trial['passed']}
            if record and variant:
                recordings.setdefault(variant, {})[name] = trial
        results[group] = measurements
        check['summarize'](list(measurements.values()), group)

    for angle, controlled in [(0, False), *((angle, True) for angle in LIP_ANGLES)]:
        variant = BEFORE if not controlled else AFTER if not angle else f'Controlled · {angle}° lip'
        for speed in SPEEDS:
            runs = ((f'Slow skate approach · {speed:.2f} m/s · {entry}',
                     trial_for(speed, y, yaw, angle=angle, controlled=controlled),
                     entry == 'centred' or (angle == 0 and speed in (.22, .25) and entry == 'yaw left'))
                    for entry, (y, yaw) in ENTRIES.items())
            report(f'{variant} · {speed:.2f} m/s', runs, variant=variant)

    for controlled in (False, True):
        variant = AFTER if controlled else BEFORE
        for speed in (.20, .23, .26, .27):
            runs = ((f'Crosswind entry · {speed:.2f} m/s · {entry}',
                     trial_for(speed, y, yaw, controlled=controlled), False)
                    for entry, (y, yaw) in HELD_OUT_ENTRIES.items())
            report(f'{variant} · New entries · {speed:.2f} m/s', runs)
        for grip, wait_s in ((.7, 2.6), (1., 10.)):
            runs = ((f'Slow skate approach · {speed:.2f} m/s · {entry}',
                     trial_for(speed, y, yaw, controlled=controlled, wheel_grip=grip, park_s=wait_s), False)
                    for speed in (.22, .25) for entry, (y, yaw) in ENTRIES.items())
            report(f'{variant} · Grip {grip:.2f} · Park {wait_s:g} s', runs)

    for angle in LIP_ANGLES:
        runs = ((entry, check['dock']['evaluate']('Fixed pad chair', (0, 0, 0), angle=40,
                        seat_lip_deg=angle, pad_inset_m=.008, settle_s=2.6,
                        approach_start=(.32, y, yaw, .16)), False)
                for entry, (y, yaw) in ENTRIES.items())
        report(f'Feet · {angle}° lip', runs)

    if args.recording:
        check['dock']['write_report'](args.recording, recordings)
    if args.results:
        check['dock']['write_report'](args.results, results)


if __name__ == '__main__':
    main()
