#!/usr/bin/env python3
"""Compare the stock Duck with rigid accessory envelopes before printing."""

import argparse
from itertools import product
import json
import math
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'python'))

from walk_sim import RUN_S, SLOT_S, WalkSimulation

FALLS = {
    'back': (0, -1, 0), 'front': (0, 1, 0),
    'left': (-1, 0, 0), 'right': (1, 0, 0),
}
BASH_SLOTS = {'bash': 207, 'bash-early': 195, 'bash-late': 220}
CASES = ('walk', 'turn-left', 'turn-right', *BASH_SLOTS, *FALLS)


def validate_modules(modules):
    names = set()
    for module in modules:
        name = module['name']
        if not name or name in names:
            raise ValueError('Module names must be nonempty and unique within each variant')
        names.add(name)
        center = module['center_m']
        if len(center) != 3 or not all(math.isfinite(v) for v in center):
            raise ValueError(f'{name}: center_m must have three finite coordinates')
        if not math.isfinite(module['mass_g']) or module['mass_g'] <= 0:
            raise ValueError(f'{name}: mass_g must be positive and finite')
        if ('size_m' in module) == ('capsule_m' in module):
            raise ValueError(f'{name}: choose either size_m or capsule_m')
        if 'capsule_m' in module:
            radius, length = module['capsule_m']
            if not 0 < 2 * radius < length < math.inf:
                raise ValueError(f'{name}: capsule length must exceed its diameter')
        else:
            size = module['size_m']
            if len(size) != 3 or not all(0 < v < math.inf for v in size):
                raise ValueError(f'{name}: size_m must have three positive dimensions')
        if type(module.get('floor_contact', True)) is not bool:
            raise ValueError(f'{name}: floor_contact must be a boolean')


def add_modules(spec, modules):
    import mujoco as mj

    for module in modules:
        # A fixed child gets its own inertia. The parent keeps its
        # explicit stock inertia. Collision mask 4 sees the floor, not the Duck.
        body = spec.body(module['parent']).add_body(name=module['name'], pos=module['center_m'])
        if 'capsule_m' in module:
            radius, length = module['capsule_m']
            kind, size = mj.mjtGeom.mjGEOM_CAPSULE, [radius, length / 2 - radius, 0]
        else:
            kind = mj.mjtGeom.mjGEOM_BOX
            size = [length / 2 for length in module['size_m']]
        body.add_geom(name=module['name'], type=kind, size=size,
                      mass=module['mass_g'] / 1000,
                      contype=4 if module.get('floor_contact', True) else 0,
                      conaffinity=0)
    spec.geom('floor').conaffinity |= 4


def run_case(case, modules, policies, trace=None):
    yaw = {'turn-left': 0.6, 'turn-right': -0.6}.get(case, 0)
    sim = WalkSimulation(0 if yaw else 0.2, yaw,
                         configure=(lambda spec: add_modules(spec, modules)) if modules else None,
                         **policies)
    d, r = sim.data, sim.root
    if case in FALLS:
        sim.mj.mju_axisAngle2Quat(d.qpos[r + 3:r + 7], sim.np.array(FALLS[case], dtype=float),
                                math.pi / 2)
    start_xy = d.qpos[r:r + 2].copy()
    heading_change = previous_heading = 0.0
    highest_tilt = 0.0
    resumed = None
    tilt = 0.0
    module_geoms = {sim.model.geom(m['name']).id: m['name'] for m in modules} if trace is not None else {}
    for slot in range(round(RUN_S / SLOT_S)):
        if slot == BASH_SLOTS.get(case):
            sim.apply_push('bash')
        sim.tick()
        if trace is not None:
            attached_contacts = set()
            for contact in d.contact:
                a, b = contact.geom
                other = b if a == sim.floor else a if b == sim.floor else None
                if other in module_geoms:
                    attached_contacts.add(module_geoms[other])
            trace.append(dict(sim.snapshot(), footfalls=sim.footfalls.copy(),
                              module_contacts=sorted(attached_contacts)))
        w, x, y, z = d.qpos[r + 3:r + 7]
        up = 1 - 2 * (x * x + y * y)
        tilt = math.degrees(math.acos(max(-1, min(1, up))))
        highest_tilt = max(highest_tilt, tilt)
        heading = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
        if slot:
            heading_change += math.remainder(heading - previous_heading, math.tau)
        previous_heading = heading
        if sim.resumed_at_s is not None and resumed is None:
            resumed = (d.qpos[r:r + 2].copy(), (math.cos(heading), math.sin(heading)), sim.footfalls.copy())
    xy = d.qpos[r:r + 2]
    upright = sim.recovery.phase == 'walk' and d.qpos[r + 2] >= 0.10 and tilt < 25
    went_down = sim.recovery.transitions > 0
    recovered_s = forward_after = None
    recovery_steps = 0
    if resumed is not None and sim.resumed_at_s is not None:
        # A second fall fails the gate even if it also gets up.
        recovered_s = sim.resumed_at_s - (sim.push['time_s'] if sim.push else 0)
        forward_after = float((xy - resumed[0]) @ resumed[1])
        recovery_steps = min(sim.footfalls[foot] - count for foot, count in resumed[2].items())
    return dict(
        mass_g=round(float(sim.model.body_mass.sum()) * 1000, 2),
        upright=bool(upright), transitions=sim.recovery.transitions, fell=went_down,
        forward_m=float(xy[0] - start_xy[0]), yaw_deg=math.degrees(heading_change),
        peak_tilt_deg=highest_tilt, both_feet=min(sim.footfalls.values()),
        recovered_s=recovered_s, resumed_forward_m=forward_after,
        resumed_both_feet=recovery_steps,
    )


def passes(case, trial, stock):
    if not trial['upright']:
        return False
    if case == 'walk':
        return (not trial['fell'] and trial['both_feet'] >= 10
                and trial['forward_m'] >= max(1.5, 0.75 * stock['forward_m']))
    if case.startswith('turn-'):
        sign = 1 if case == 'turn-left' else -1
        return (not trial['fell'] and trial['both_feet'] >= 5
                and sign * trial['yaw_deg'] >= max(90, 0.75 * sign * stock['yaw_deg']))
    if case in BASH_SLOTS and not trial['fell']:
        return trial['both_feet'] >= 10 and trial['forward_m'] >= 1.5
    return (trial['transitions'] == 3 and trial['recovered_s'] is not None
            and trial['recovered_s'] <= 8 and trial['resumed_forward_m'] >= 0.75
            and trial['resumed_both_feet'] >= 5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('variants', type=Path, help='JSON mapping variant names to module lists')
    parser.add_argument('--walk-policy', type=Path)
    parser.add_argument('--getup-policy', type=Path)
    parser.add_argument('--variant', help='Check one variant alongside stock')
    parser.add_argument('--sweep-module', help='Vary mass and vertical position of one named module')
    parser.add_argument('--mass-g', type=float, nargs='+', help='Mass values for the sweep')
    parser.add_argument('--z-offset-mm', type=float, nargs='+', help='Vertical offsets for the sweep')
    parser.add_argument('--trace-case', choices=CASES, help='Include actual poses and contacts for one case')
    args = parser.parse_args()
    policies = {}
    for key, path in (('walk_file', args.walk_policy), ('getup_file', args.getup_policy)):
        if path is not None:
            if not path.is_file():
                parser.error(f'Policy file does not exist: {path}')
            policies[key] = path.resolve()
    try:
        variants = json.loads(args.variants.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        parser.error(f'Cannot read variant file: {exc}')
    if not isinstance(variants, dict) or any(not isinstance(items, list) for items in variants.values()):
        parser.error('The variant file must map names to module lists')
    if 'stock' in variants:
        parser.error('The stock baseline is generated automatically')
    if args.variant is not None:
        if args.variant not in variants:
            parser.error(f'Unknown variant: {args.variant}')
        variants = {args.variant: variants[args.variant]}
    for name, modules in variants.items():
        try:
            validate_modules(modules)
        except (KeyError, TypeError, ValueError) as exc:
            parser.error(f'Invalid variant {name}: {exc}')
    if args.sweep_module is not None:
        if args.variant is None or args.mass_g is None or args.z_offset_mm is None:
            parser.error('A sweep needs --variant, --mass-g and --z-offset-mm')
        if not all(math.isfinite(v) for v in args.mass_g + args.z_offset_mm):
            parser.error('Sweep values must be finite')
        if min(args.mass_g) <= 0:
            parser.error('Sweep mass values must be positive')
        if len(args.mass_g) * len(args.z_offset_mm) > 25:
            parser.error('A sweep can contain up to 25 combinations')
        modules = variants[args.variant]
        matches = [module for module in modules if module.get('name') == args.sweep_module]
        if len(matches) != 1:
            parser.error('The sweep module must appear exactly once in the variant')
        source = matches[0]
        variants = {}
        for mass, z_offset in product(args.mass_g, args.z_offset_mm):
            x, y, z = source['center_m']
            item = dict(source, mass_g=mass, center_m=[x, y, z + z_offset / 1000])
            name = f'{args.variant} {mass:g} g z{z_offset:+g} mm'
            variants[name] = [item if module is source else module for module in modules]
    elif args.mass_g is not None or args.z_offset_mm is not None:
        parser.error('Specify --sweep-module to use sweep values')
    results = {}
    for variant, modules in {'stock': [], **variants}.items():
        trials = results[variant] = {}
        for case in CASES:
            trace = [] if case == args.trace_case else None
            trial = trials[case] = run_case(case, modules, {} if variant == 'stock' else policies, trace)
            if trace is not None:
                trial['trace'] = trace
                trial['modules'] = modules
    stock = results['stock']
    for trials in results.values():
        for case, trial in trials.items():
            trial['passed'] = passes(case, trial, stock[case])
    print(json.dumps(results, indent=2, allow_nan=False))
    return 0 if all(t['passed'] for trials in results.values() for t in trials.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
