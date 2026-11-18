"""Compare skate release checks and the effects of a shallow chair recess."""
import argparse
from pathlib import Path
import runpy

lowering = runpy.run_path(str(Path(__file__).with_name('check-skate-lowering.py')))
check = lowering['check']
BEFORE = 'Before · Clearance estimate'
AFTER = 'After · Upright and free of contact'


def run(speed, lateral, heading, *, angle=0, guides=None, contact=True):
    trial = check['test'](approach=(.32, lateral, heading, speed), seat_lip_deg=angle,
                          slow_skate_gate=lowering['SLOW_GATE'], seat_guides_mm=guides,
                          contact_handoff=contact)
    trial['dock']['lowering_test'] = True
    return trial


def brace_study():
    """Repeat the same sit-back with successively longer torque fades."""
    results = {}
    entries = {**lowering['ENTRIES'], '20 mm left': (.02, 0), '20 mm right': (-.02, 0),
               'yaw against left offset': (.006, -3), 'yaw against right offset': (-.006, 3)}
    for fade in (0, .10, .20, .35):
        for skates, speed in ((False, .16), (True, .22), (True, .28)):
            group = f'{"Skates" if skates else "Feet"} · {speed:.2f} m/s · {fade:.2f} s fade'
            results[group] = trials = {}
            for entry, (lateral, heading) in entries.items():
                settings = dict(approach_start=(.32, lateral, heading, speed), angle=40,
                                pad_inset_m=.008, settle_s=2.6, skates=skates, brace_s=fade)
                if skates:
                    settings.update(roller_release=True, contact_handoff=True, skate_roll=.08,
                                    slow_skate_gate=lowering['SLOW_GATE'])
                trial = check['dock']['evaluate']('Fixed pad chair', (0, 0, 0), **settings)
                result = trial['dock']
                full_cycle = trial['passed'] and (not skates or result['roller_release']['wheels_only_exit'])
                trials[entry] = {**result, 'full_cycle': full_cycle}
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recording', type=Path)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--brace-study', action='store_true')
    args = parser.parse_args()
    if args.brace_study:
        results = brace_study()
        for group, trials in results.items():
            check['summarize'](list(trials.values()), group)
        check['dock']['write_report'](args.results, results)
        return
    recordings, results = {}, {}

    def record(variant, group, entry, trial, save):
        measures = {**trial['dock'], 'full_cycle': trial['passed']}
        results.setdefault(group, {})[entry] = measures
        if save:
            recordings.setdefault(variant, {})[entry] = trial

    for contact, variant in ((False, BEFORE), (True, AFTER)):
        for angle in lowering['LIP_ANGLES']:
            for speed in (.22, .25, .28, .30, .32):
                group = f'{variant} · {angle}° · {speed:.2f} m/s'
                for name, (lateral, heading) in lowering['ENTRIES'].items():
                    entry = f'Skate release · {angle}° lip · {speed:.2f} m/s · {name}'
                    record(variant, group, entry, run(speed, lateral, heading, angle=angle, contact=contact),
                           name == 'centred' and speed in (.28, .32))

    for variant, guides in (('Flat seat', None), ('Raised sides · 5 mm', (42, 10, 5)),
                            ('Wide raised sides · 2 mm', (46, 15, 2))):
        for speed in (.22, .28):
            group = f'{variant} · {speed:.2f} m/s'
            for label, lateral, heading in [('centred', 0, 0), ('20 mm left', .020, 0), ('20 mm right', -.020, 0),
                                           ('28 mm left', .028, 0), ('28 mm right', -.028, 0),
                                           ('6 mm left, yaw right', .006, -3), ('6 mm right, yaw left', -.006, 3)]:
                entry = f'Recess trial · {speed:.2f} m/s · {label}'
                record(variant, group, entry, run(speed, lateral, heading, guides=guides),
                       speed == .28 and label in ('centred', '20 mm left', '28 mm left'))

    for group, trials in results.items():
        check['summarize'](list(trials.values()), group)
    if args.recording:
        check['dock']['write_report'](args.recording, recordings)
    check['dock']['write_report'](args.results, results)


if __name__ == '__main__':
    main()
