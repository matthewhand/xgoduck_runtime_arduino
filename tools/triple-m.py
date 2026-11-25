"""Run and cache Duck Lab's Triple M simulation cases."""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256
from inspect import getsource
import json
import math
from multiprocessing import get_context
import os
from pathlib import Path
import platform
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))

import mujoco as mj
import numpy as np
import onnxruntime as ort

from skate_dock_exit import load_roller_policy, roller_target
from triple_m_batches import BatchStore, atomic_json, completed_row, error_row, publish_latest, read_json, timestamp
from triple_m_scenarios import run_scenario
from walk_sim import JOINT_IDS, MODEL, ROLLER_MODEL, RUN_S, SLOT_S, SUBSTEPS, WHEEL_NAMES, WalkSimulation

TOOLS = ROOT / 'tools'
ASSETS = ROOT / 'assets'
CACHE = ROOT / '.cache/triple-m'
REPLAY_SCHEMA = 1
RUNNER_VERSION = 2
HARDWARE = runpy.run_path(str(TOOLS / 'check-duck-hardware.py'))
MOTIONS = runpy.run_path(str(TOOLS / 'record-xgo-motions.py'))
FALLS, add_modules = HARDWARE['FALLS'], HARDWARE['add_modules']
PACK = json.loads((ASSETS / 'sim/contact-harness.json').read_text(encoding='utf-8'))['estimate']['with_printed']
MOVE_LABELS = {'walk':'Walk', 'getup':'Get-up', 'skate':'Skate', 'dance':'Head dance', 'polite-bow':'Polite bow',
               'flamingo-cycle':'Flamingo'}
EXPRESSION_ASSETS = {item[0]: item[1:] for item in MOTIONS['COMMUNITY'].values()}
DEFAULT = dict(moves=['walk','getup','skate'], builds=['stock','backpack'], faults=['nominal','shove','jam'],
               pack_g=round(PACK['mass_g']['nominal'], 2), grip=.75, shove_m_s=.35, jam_s=.60, scenarios=[])
FAULT_AT_S = 2.
SCENARIOS = ('wheel-jam-release', 'fall-recovery')


def normalize(options):
    if not isinstance(options, dict) or set(options) - set(DEFAULT):
        raise ValueError('Choose the supported motions, builds and physics settings.')
    settings = {**DEFAULT, **options}
    for name, choices in (('moves', MOVE_LABELS), ('builds', DEFAULT['builds']), ('faults', DEFAULT['faults']),
                          ('scenarios', SCENARIOS)):
        selected = settings[name]
        if not isinstance(selected, list) or (not selected and name in ('builds', 'faults')) or any(
                not isinstance(v, str) or v not in choices for v in selected):
            raise ValueError(f'Choose one or more supported {name}.')
        settings[name] = [v for v in choices if v in selected]
    if not settings['moves'] and not settings['scenarios']:
        raise ValueError('Choose at least one motion or scenario.')
    for name, low, high in (('pack_g', 5, 80), ('grip', .3, 1.5), ('shove_m_s', .1, .8), ('jam_s', .10, 2.)):
        value = settings[name]
        if type(value) not in (int, float) or not low <= value <= high:
            raise ValueError(f'{name} must be between {low:g} and {high:g}.')
        settings[name] = round(float(value), 3)
    return settings


def cases_for(settings):
    cases = []
    for build in settings['builds']:
        modules = []
        if build == 'backpack':
            # Transform the harness/CAD estimate from print coordinates into the trunk frame.
            x, y, z = PACK['centroid_mm']
            modules = [dict(name='charging_backpack', parent='trunk_base', mass_g=settings['pack_g'],
                            center_m=[round(v/1000, 8) for v in (z-57.33226, x-.00628, y-39.25512)],
                            size_m=[.014,.064,.076])]
        for move in settings['moves']:
            conditions = []
            if 'nominal' in settings['faults']:
                conditions.extend([{'fall':side} for side in FALLS] if move == 'getup' else [{}])
            if move in ('walk','skate') and 'shove' in settings['faults']:
                conditions.extend(dict(shove=sign * settings['shove_m_s'], at_s=FAULT_AT_S) for sign in (-1,1))
            if move == 'skate' and 'jam' in settings['faults']:
                conditions.extend(dict(jam=wheel, jam_s=settings['jam_s'], at_s=FAULT_AT_S) for wheel in ('LF','RF'))
            for fault in conditions:
                cases.append(dict(build=build, modules=modules, move=move, grip=settings['grip'], fault=fault))
        preset = dict(build=build, modules=modules, grip=settings['grip'])
        if 'wheel-jam-release' in settings['scenarios']:
            for wheel in ('LF', 'RF'):
                for variant in ('matched-control', 'release', 'simulated-brake'):
                    fault = dict(jam_s=settings['jam_s'], at_s=FAULT_AT_S)
                    fault['jam_wheel' if variant == 'matched-control' else 'jam'] = wheel
                    cases.append(dict(preset, move='skate', fault=fault,
                                      scenario=dict(kind='wheel-jam-release', variant=variant)))
        if 'fall-recovery' in settings['scenarios']:
            for side in ('back', 'right'):
                cases.append(dict(preset, move='walk', fault=dict(tip=side, at_s=FAULT_AT_S),
                                  scenario=dict(kind='fall-recovery', variant=side)))
    if not cases:
        raise ValueError('No selected move supports those physics settings.')
    return cases


def label(case):
    fault = case['fault']
    scenario = case.get('scenario')
    build = case['build'].capitalize()
    if scenario:
        if scenario['kind'] == 'fall-recovery':
            return f"Walk and get up · {fault['tip'].capitalize()} shove · {build}"
        wheel = fault.get('jam', fault.get('jam_wheel'))
        branch = {'matched-control': 'Matched control', 'release': 'Jam and release',
                  'simulated-brake': 'Jam and simulated brake'}[scenario['variant']]
        return f"Skate · {wheel} {branch} · {build}"
    condition = (f"From {fault['fall']}" if 'fall' in fault else
                 ('Shove left' if fault['shove'] > 0 else 'Shove right') if 'shove' in fault else
                 f"{fault['jam']} wheel jam" if 'jam' in fault else 'Baseline')
    return f"{MOVE_LABELS[case['move']]} · {condition} · {build}"


def tilt(sim):
    x, y = sim.data.qpos[sim.root + 4:sim.root + 6]
    return math.degrees(math.acos(max(-1., 1 - 2*(x*x+y*y))))


def setup(case, pins=None):
    fault, modules = case['fault'], case['modules']

    def configure(spec):
        add_modules(spec, modules)
        if 'jam' in fault:
            spec.add_equality(name='test_wheel_lock', type=mj.mjtEq.mjEQ_JOINT, active=0,
                              name1=f"passive_{fault['jam']}_wheel", objtype=mj.mjtObj.mjOBJ_JOINT,
                              data=[0.]*11, solref=[.010, 1.])

    policy_options = {} if pins is None else dict(walk_file=pins['walk'][0], getup_file=pins['getup'][0],
        policy_hashes={skill: pins[skill][1] for skill in ('walk','getup')})
    sim = WalkSimulation(.2, 0, configure=configure, skates=case['move'] == 'skate', **policy_options)
    sim.model.geom_friction[[sim.floor, *sim.feet], 0] = case['grip']
    return sim


def capture(sim, case, *, wheels=None):
    snapshot = sim.snapshot()
    snapshot['root'] = sim.data.qpos[sim.root:sim.root+7].round(6).tolist()
    snapshot['joints_rad'] = dict(zip(JOINT_IDS, sim.data.qpos[sim.qpos].round(6).tolist()))
    snapshot['footfalls'] = snapshot['footfalls'].copy()
    if wheels is not None:
        snapshot['wheels_rad'] = sim.data.qpos[wheels].round(6).tolist()
        snapshot.pop('recovery', None)
    modules = {sim.model.geom(m['name']).id: m['name'] for m in case['modules']}
    snapshot['module_contacts'] = sorted({modules[b if a == sim.floor else a] for a, b in (c.geom for c in sim.data.contact)
                                          if sim.floor in (a, b) and (a in modules or b in modules)})
    return snapshot


def walk_or_getup(sim, case):
    fault = case['fault']
    if 'fall' in fault:
        mj.mju_axisAngle2Quat(sim.data.qpos[sim.root+3:sim.root+7], np.array(FALLS[fault['fall']], dtype=float), math.pi / 2)
    mj.mj_forward(sim.model, sim.data)
    trace = [capture(sim, case)]
    peak, max_side, resumed_xy = tilt(sim), 0., None
    onset = round(fault.get('at_s', -1)/SLOT_S)
    for slot in range(round(RUN_S/SLOT_S)):
        if slot == onset:
            sim.data.qvel[sim.root_dof+1] += fault['shove']
        sim.tick()
        peak = max(peak, tilt(sim))
        max_side = max(max_side, abs(float(sim.data.qpos[sim.root+1])))
        if resumed_xy is None and sim.resumed_at_s is not None:
            resumed_xy = sim.data.qpos[sim.root:sim.root+2].copy()
        if slot % 2 == 1:
            trace.append(capture(sim, case))
    upright = tilt(sim) < 25 and sim.data.qpos[sim.root+2] >= .10 and sim.recovery.phase == 'walk'
    forward = float(sim.data.qpos[sim.root])
    resumed = sim.resumed_at_s
    if case['move'] == 'getup':
        travelled = float(np.linalg.norm(sim.data.qpos[sim.root:sim.root+2] - resumed_xy)) if resumed_xy is not None else 0.
        failure = ('Did not regain upright walking' if not upright or resumed is None else
                   'Recovery took over 8 s' if resumed > 8 else 'Fell again' if sim.recovery.transitions != 3 else
                   'Moved less than 0.75 m after recovery' if travelled < .75 else None)
    else:
        failure = ('Fell during the walk' if sim.recovery.transitions else 'Ended out of balance' if not upright else
                   'Drifted over 15 cm' if max_side > .15 else 'Moved less than 1.5 m' if forward < 1.5 else None)
    return dict(trace=trace, failure=failure, forward_m=forward, max_side_m=max_side, peak_tilt_deg=peak, recovered_s=resumed)


def engage_lock(sim, wheel):
    position = int(sim.model.joint(f'passive_{wheel}_wheel').qposadr[0])
    eq = sim.model.equality('test_wheel_lock').id
    sim.model.eq_data[eq, 0] = sim.data.qpos[position] - sim.model.qpos0[position]
    sim.data.eq_active[eq] = 1
    return eq, position, float(sim.data.qpos[position])


def skate(sim, case, pins=None):
    fault = case['fault']
    mj.mj_resetDataKeyframe(sim.model, sim.data, sim.model.key('home').id)
    mj.mj_forward(sim.model, sim.data)
    wheels = [int(sim.model.joint(w).qposadr[0]) for w in WHEEL_NAMES]
    policy = load_roller_policy(pinned=(pins or {}).get('roller'))
    trace = [capture(sim, case, wheels=wheels)]
    onset = round(fault.get('at_s', -1)/SLOT_S)
    release = onset + round(fault.get('jam_s', 0)/SLOT_S)
    peak, max_side, lock, lock_travel, failure, failed_at = 0., 0., None, 0., None, None
    for slot in range(round(6/SLOT_S)):
        if slot == onset:
            if 'jam' in fault:
                lock = engage_lock(sim, fault['jam'])
            else:
                sim.data.qvel[sim.root_dof+1] += fault['shove']
        if lock and slot == release:
            sim.data.eq_active[lock[0]] = 0
        w, x, y, z = sim.data.qpos[sim.root+3:sim.root+7]
        heading = math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z))
        target = math.atan2(-sim.data.qpos[sim.root+1], .35)
        yaw = max(-.45, min(.45, 1.8*(target-heading)))
        sim.data.ctrl[sim.actuators] = roller_target(sim, policy, [.4,0,yaw])
        mj.mj_step(sim.model, sim.data, nstep=SUBSTEPS)
        if not np.isfinite(sim.data.qpos).all():
            raise ValueError('Roller simulation produced non-finite physics')
        if lock and slot < release:
            lock_travel = max(lock_travel, abs(sim.data.qpos[lock[1]] - lock[2]))
        angle = tilt(sim)
        peak = max(peak, angle)
        max_side = max(max_side, abs(float(sim.data.qpos[sim.root+1])))
        if failure is None:
            floor_hit = any(sim.floor in c.geom and not any(g in sim.feet for g in c.geom) and c.dist < -.00015 for c in sim.data.contact)
            failure = ('Lost balance' if angle > 45 or sim.data.qpos[sim.root+2] < .085 else
                       'Body touched floor' if floor_hit else 'Drifted over 15 cm' if max_side > .15 else None)
            if failure:
                failed_at = float(sim.data.time)
        if slot % 2 == 1:
            trace.append(capture(sim, case, wheels=wheels))
    forward = float(sim.data.qpos[sim.root])
    return dict(trace=trace, failure=failure or ('Moved less than 0.35 m' if forward < .35 else None),
                failed_at_s=failed_at, forward_m=forward, max_side_m=max_side, peak_tilt_deg=peak,
                wheel_slip_deg=math.degrees(lock_travel) if lock else None)


def expression(sim, case, pins=None):
    skill = case['move']
    stand = MOTIONS['load_skill']('walk', pinned=(pins or {}).get('walk'))
    if skill == 'dance':
        policy = MOTIONS['load_skill']('walk', pinned=(pins or {}).get('walk'))
    else:
        policy_path = ROOT / '.cache' / f'microduck-{skill}.onnx'
        policy = MOTIONS['load_skill'](skill, policy_path, pinned=(pins or {}).get(skill))
    result = MOTIONS['record'](sim, stand, policy, skill)
    motion = result['motion']
    gesture = max(max(frame['joints_rad'][id] for frame in result['trace']) - min(frame['joints_rad'][id] for frame in result['trace']) for id in (30,31,32,33))
    failure = ('Did not return upright' if not motion['upright'] else
               'Head motion under 10°' if gesture < math.radians(10) else
               'One-foot contact under 0.15 s' if skill == 'flamingo-cycle' and motion['one_foot_s'] < .15 else None)
    return dict(trace=result['trace'], failure=failure, peak_tilt_deg=motion['peak_tilt_deg'],
                gesture_deg=math.degrees(gesture), one_foot_s=motion.get('one_foot_s'))


def runner_identity():
    return dict(version=RUNNER_VERSION, replay_schema=REPLAY_SCHEMA, python=platform.python_version(),
                implementation=platform.python_implementation(), system=platform.system(), machine=platform.machine(),
                mujoco=mj.__version__, numpy=np.__version__, onnxruntime=ort.__version__,
                provider='CPUExecutionProvider')


def digest_file(path, digests):
    if path not in digests:
        data = path.read_bytes()
        if path.suffix in ('.py', '.xml'):
            data = data.replace(b'\r\n', b'\n')
        digests[path] = sha256(data).hexdigest()
    return digests[path]


def policy_pins(case, digests):
    move = case['move']
    skills = ('walk', 'getup', 'roller') if move == 'skate' else ('walk', 'getup')
    paths = {skill: ROOT / 'python' / f'xgoduck_{skill}.onnx' for skill in skills}
    pins = {skill: (path, digest_file(path, digests)) for skill, path in paths.items()}
    if move in EXPRESSION_ASSETS:
        pins[move] = ROOT / '.cache' / f'microduck-{move}.onnx', EXPRESSION_ASSETS[move][2]
    return pins


def dependency_key(case, digests, *, pins=None, runner=None):
    move = case['move']
    skate_case = move == 'skate'
    model = ROLLER_MODEL if skate_case else MODEL
    files = [model, model.parent / ('robot.xml' if skate_case else 'robot_walk.xml')]
    files.extend(sorted((model.parent / 'assets').glob('*')))
    files += [ROOT / 'python' / name for name in ('walk_sim.py', 'policy.py', 'rl_core.py', 'recovery.py')]
    functions = [setup, add_modules, run_case]
    if skate_case:
        files.append(TOOLS / 'skate_dock_exit.py')
        functions += [skate, capture, tilt]
        if 'jam' in case['fault']:
            functions.append(engage_lock)
    elif move in ('walk','getup'):
        functions += [walk_or_getup, capture, tilt]
    else:
        files += [ROOT / 'python/controller.py', TOOLS / 'record-xgo-motions.py']
        functions.append(expression)
    if case.get('scenario'):
        files.append(TOOLS / 'triple_m_scenarios.py')
        functions.extend((engage_lock, capture, tilt))
    fingerprints = [(path.relative_to(ROOT).as_posix(), digest_file(path, digests)) for path in files]
    policies = pins if pins is not None else policy_pins(case, digests)
    fingerprints.extend((path.relative_to(ROOT).as_posix(), digest) for path, digest in policies.values())
    physics = case['fault']
    if 'fall' in physics:
        physics = dict(physics, axis=FALLS[physics['fall']])
    identity = dict(schema=REPLAY_SCHEMA, move=move, physics=physics, grip=case['grip'], modules=case['modules'],
                    engine=runner or runner_identity(), scenario=case.get('scenario'),
                    sources=[sha256(getsource(f).replace('\r\n', '\n').encode()).hexdigest() for f in functions],
                    files=fingerprints)
    return sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def run_case(case, pins=None):
    sim = setup(case, pins)
    move = case['move']
    if case.get('scenario'):
        result = run_scenario(sim, case, capture=capture, tilt=tilt, engage_lock=engage_lock,
                              load_roller=lambda: load_roller_policy(pinned=(pins or {}).get('roller')))
    elif move == 'skate':
        result = skate(sim, case, pins)
    elif move in ('walk', 'getup'):
        result = walk_or_getup(sim, case)
    else:
        result = expression(sim, case, pins)
    result.update(mass_g=round(float(sim.model.body_mass.sum())*1000, 2),
                  passed=result['failure'] is None and not result.get('skipped', False))
    return result


def run_pinned_case(case, key):
    digests = {}
    pins = policy_pins(case, digests)
    if dependency_key(case, digests, pins=pins) != key:
        raise ValueError('Simulation inputs changed before the worker started. Run a new batch.')
    result = run_case(case, pins)
    if dependency_key(case, {}) != key:
        raise ValueError('Simulation inputs changed during the run. Run a new batch.')
    if not valid_result(result):
        raise ValueError('The worker returned an invalid replay trace.')
    return result


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def finite_vector(value, length):
    return isinstance(value, list) and len(value) == length and all(map(finite_number, value))


EXPECTED_JOINTS = frozenset(map(str, JOINT_IDS))


def valid_result(result):
    if not isinstance(result, dict) or type(result.get('passed')) is not bool or 'failure' not in result:
        return False
    failure = result['failure']
    if failure is not None and not isinstance(failure, str):
        return False
    skipped = result.get('skipped', False)
    if type(skipped) is not bool or result['passed'] != (failure is None and not skipped):
        return False
    trace = result.get('trace')
    if not isinstance(trace, list) or not trace:
        return False
    previous_time = -1
    for frame in trace:
        if not isinstance(frame, dict):
            return False
        current_time, joints = frame.get('time_s'), frame.get('joints_rad')
        if (not finite_number(current_time) or current_time <= previous_time or current_time < 0
                or not finite_vector(frame.get('root'), 7) or not isinstance(joints, dict)
                or set(map(str, joints)) != EXPECTED_JOINTS or len(joints) != len(EXPECTED_JOINTS)
                or not all(map(finite_number, joints.values()))
                or ('wheels_rad' in frame and not finite_vector(frame['wheels_rad'], len(WHEEL_NAMES)))):
            return False
        previous_time = current_time
    return True


def load_cache(path, key):
    try:
        entry = read_json(path)
        if isinstance(entry, dict) and entry.get('key') == key and valid_result(entry.get('result')):
            return entry['result']
    except (OSError, ValueError, OverflowError):
        return None


def plan_batch(options):
    settings = normalize(options)
    digests = {}
    runner = runner_identity()
    rows = [dict(case=case, label=label(case), key=dependency_key(case, digests, runner=runner))
            for case in cases_for(settings)]
    # Keep live plans and manifests identical after serialization, including tuples in case options.
    return json.loads(json.dumps(dict(schema=REPLAY_SCHEMA, runner=runner, settings=settings, cases=rows)))


def run_batch(options, workers, cache=CACHE, *, keys=None, progress=lambda update: None, batch=None):
    plan = plan_batch(options)
    if batch is not None and (keys is not None or not batch.matches(plan)):
        raise ValueError('The stored batch needs different simulation inputs. Run a new batch.')
    if keys is None:
        selected = plan['cases']
    else:
        requested = set(keys)
        if requested - {row['key'] for row in plan['cases']}:
            raise ValueError('One or more case keys are missing from the current plan.')
        selected = [row for row in plan['cases'] if row['key'] in requested]

    entries, queued = {}, {}
    hits = 0

    def finish(row):
        entries[row['key']] = row
        if batch is not None:
            batch.save(row)

    for entry in selected:
        key, move = entry['key'], entry['case']['move']
        saved = batch.case(key) if batch is not None else None
        if saved is not None and saved['result'] is not None:
            entries[key] = saved
            hits += 1
            continue
        cached = load_cache(cache / f'{key}.json', key)
        if cached is not None:
            finish(completed_row(entry, cached))
            hits += 1
            continue
        if move in EXPRESSION_ASSETS:
            path, expected = policy_pins(entry['case'], {})[move]
            if not path.is_file() or digest_file(path, {}) != expected:
                finish(error_row(entry, f'Place the pinned {move} ONNX in .cache, then retry this batch.'))
                continue
        queued[key] = entry

    used_workers = min(workers, len(queued))
    completed = len(selected) - len(queued)

    def report_progress():
        progress(dict(total=len(selected), reused=hits, completed=completed, workers=used_workers))

    report_progress()
    if queued:
        with ProcessPoolExecutor(max_workers=used_workers, mp_context=get_context('spawn')) as pool:
            futures = {pool.submit(run_pinned_case, entry['case'], key): entry for key, entry in queued.items()}
            for future in as_completed(futures):
                entry = futures[future]
                key = entry['key']
                try:
                    result = future.result()
                    atomic_json(cache / f'{key}.json', dict(key=key, result=result))
                    finish(completed_row(entry, result))
                except Exception as exc:
                    finish(error_row(entry, exc))
                completed += 1
                report_progress()
    rows = [entries[row['key']] for row in selected]
    compute = dict(workers=used_workers, reused=hits, ran=len(queued), errors=sum(row['state'] == 'error' for row in rows))
    if batch is not None:
        batch.save_compute(compute)
        return batch.report()
    return {**plan, 'created_at': timestamp(), 'cases': rows, 'compute': compute}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--options', type=Path, help='Run a saved plan from the Triple M panel')
    parser.add_argument('--report', type=Path, help='Also write a standalone report for this batch')
    parser.add_argument('--cache', type=Path, default=CACHE)
    parser.add_argument('--jobs', type=int, choices=range(1, 9), default=min(4, os.cpu_count() or 1))
    parser.add_argument('--expressions', action='store_true', help='Include head dance and both Microduck gestures')
    parser.add_argument('--serve', action='store_true', help='Enable the Run batch button on this computer')
    args = parser.parse_args()
    if args.serve:
        from triple_m_server import serve
        serve(plan_batch, run_batch, args.cache, args.jobs, ASSETS)
        return
    options = read_json(args.options) if args.options else {}
    if args.expressions:
        options['moves'] = list(MOVE_LABELS)
    batch = BatchStore.create(args.cache, plan_batch(options))
    batch.mark_attempt()
    report = run_batch(options, args.jobs, args.cache, batch=batch)
    if args.report is not None:
        atomic_json(args.report, report)
    if any(row['result'] is not None for row in report['cases']):
        publish_latest(args.cache / 'latest.json', report)
    for row in report['cases']:
        result = row['result']
        detail = row.get('error') if result is None else result.get('skip_reason') or result['failure'] or 'Pass'
        print(row['label'], detail)
    print(batch.manifest['id'], report['compute'], flush=True)
    if report['compute']['errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
