"""Run and cache Duck Lab's Triple M simulation cases."""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
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
from tempfile import NamedTemporaryFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))

import mujoco as mj
import numpy as np
import onnxruntime as ort

from skate_dock_exit import load_roller_policy, roller_target
from walk_sim import JOINT_IDS, MODEL, ROLLER_MODEL, RUN_S, SLOT_S, SUBSTEPS, WHEEL_NAMES, WalkSimulation

TOOLS = ROOT / 'tools'
ASSETS = ROOT / 'assets'
CACHE = ROOT / '.cache/triple-m'
REPLAY_SCHEMA = 1
HARDWARE = runpy.run_path(str(TOOLS / 'check-duck-hardware.py'))
MOTIONS = runpy.run_path(str(TOOLS / 'record-xgo-motions.py'))
FALLS, add_modules = HARDWARE['FALLS'], HARDWARE['add_modules']
PACK = json.loads((ASSETS / 'sim/contact-harness.json').read_text(encoding='utf-8'))['estimate']['with_printed']
MOVE_LABELS = {'walk':'Walk', 'getup':'Get-up', 'skate':'Skate', 'dance':'Head dance', 'polite-bow':'Polite bow',
               'flamingo-cycle':'Flamingo'}
EXPRESSION_ASSETS = {item[0]: item[1:] for item in MOTIONS['COMMUNITY'].values()}
DEFAULT = dict(moves=['walk','getup','skate'], builds=['stock','backpack'], faults=['nominal','shove','jam'],
               pack_g=round(PACK['mass_g']['nominal'], 2), grip=.75, shove_m_s=.35, jam_s=.60)
FAULT_AT_S = 2.


def normalize(options):
    if not isinstance(options, dict) or set(options) - set(DEFAULT):
        raise ValueError('Choose the supported motions, builds and physics settings.')
    settings = {**DEFAULT, **options}
    for name, choices in (('moves', MOVE_LABELS), ('builds', DEFAULT['builds']), ('faults', DEFAULT['faults'])):
        selected = settings[name]
        if not isinstance(selected, list) or not selected or any(not isinstance(v, str) or v not in choices for v in selected):
            raise ValueError(f'Choose one or more supported {name}.')
        settings[name] = [v for v in choices if v in selected]
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
    if not cases:
        raise ValueError('No selected move supports those physics settings.')
    return cases


def label(case):
    fault = case['fault']
    condition = (f"From {fault['fall']}" if 'fall' in fault else
                 ('Shove left' if fault['shove'] > 0 else 'Shove right') if 'shove' in fault else
                 f"{fault['jam']} wheel jam" if 'jam' in fault else 'Baseline')
    return f"{MOVE_LABELS[case['move']]} · {condition} · {case['build'].capitalize()}"


def tilt(sim):
    x, y = sim.data.qpos[sim.root + 4:sim.root + 6]
    return math.degrees(math.acos(max(-1., 1 - 2*(x*x+y*y))))


def setup(case):
    fault, modules = case['fault'], case['modules']

    def configure(spec):
        add_modules(spec, modules)
        if 'jam' in fault:
            spec.add_equality(name='test_wheel_lock', type=mj.mjtEq.mjEQ_JOINT, active=0,
                              name1=f"passive_{fault['jam']}_wheel", objtype=mj.mjtObj.mjOBJ_JOINT,
                              data=[0.]*11, solref=[.010, 1.])

    sim = WalkSimulation(.2, 0, configure=configure, skates=case['move'] == 'skate')
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


def skate(sim, case):
    fault = case['fault']
    mj.mj_resetDataKeyframe(sim.model, sim.data, sim.model.key('home').id)
    mj.mj_forward(sim.model, sim.data)
    wheels = [int(sim.model.joint(w).qposadr[0]) for w in WHEEL_NAMES]
    policy = load_roller_policy()
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


def expression(sim, case):
    skill = case['move']
    stand = MOTIONS['load_skill']('walk')
    if skill == 'dance':
        policy = MOTIONS['load_skill']('walk')
    else:
        policy_path = ROOT / '.cache' / f'microduck-{skill}.onnx'
        policy = MOTIONS['load_skill'](skill, policy_path)
    result = MOTIONS['record'](sim, stand, policy, skill)
    motion = result['motion']
    gesture = max(max(frame['joints_rad'][id] for frame in result['trace']) - min(frame['joints_rad'][id] for frame in result['trace']) for id in (30,31,32,33))
    failure = ('Did not return upright' if not motion['upright'] else
               'Head motion under 10°' if gesture < math.radians(10) else
               'One-foot contact under 0.15 s' if skill == 'flamingo-cycle' and motion['one_foot_s'] < .15 else None)
    return dict(trace=result['trace'], failure=failure, peak_tilt_deg=motion['peak_tilt_deg'],
                gesture_deg=math.degrees(gesture), one_foot_s=motion.get('one_foot_s'))


def dependency_key(case, digests):
    move = case['move']
    skate_case = move == 'skate'
    model = ROLLER_MODEL if skate_case else MODEL
    files = [model, model.parent / ('robot.xml' if skate_case else 'robot_walk.xml')]
    files.extend(sorted((model.parent / 'assets').glob('*')))
    files += [ROOT / 'python' / name for name in ('walk_sim.py','policy.py','rl_core.py')]
    functions = [setup, add_modules]
    if skate_case:
        files += [ROOT / 'python/xgoduck_roller.onnx', TOOLS / 'skate_dock_exit.py']
        functions += [skate, capture, tilt]
        if 'jam' in case['fault']:
            functions.append(engage_lock)
    elif move in ('walk','getup'):
        files += [ROOT / 'python' / f'xgoduck_{policy}.onnx' for policy in ('walk','getup')]
        files.append(ROOT / 'python/recovery.py')
        functions += [walk_or_getup, capture, tilt]
    else:
        files += [ROOT / 'python/xgoduck_walk.onnx', TOOLS / 'record-xgo-motions.py']
        functions.append(expression)
        if move in EXPRESSION_ASSETS:
            path = ROOT / '.cache' / f'microduck-{move}.onnx'
            if not path.is_file() or sha256(path.read_bytes()).hexdigest() != EXPRESSION_ASSETS[move][2]:
                raise ValueError(f'Place the pinned {move} ONNX in .cache before running that expression.')
            files.append(path)
    fingerprints = []
    for path in files:
        if path not in digests:
            digests[path] = sha256(path.read_bytes()).hexdigest()
        fingerprints.append((path.relative_to(ROOT).as_posix(), digests[path]))
    physics = case['fault']
    if 'fall' in physics:
        physics = dict(physics, axis=FALLS[physics['fall']])
    identity = dict(schema=REPLAY_SCHEMA, move=move, physics=physics, grip=case['grip'], modules=case['modules'],
                    engine=[mj.__version__, np.__version__, ort.__version__, platform.system(), platform.machine()],
                    sources=[sha256(getsource(f).encode()).hexdigest() for f in functions],
                    files=fingerprints)
    return sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def run_case(case):
    sim = setup(case)
    move = case['move']
    result = (skate(sim, case) if move == 'skate' else walk_or_getup(sim,case) if move in ('walk','getup') else expression(sim,case))
    result.update(mass_g=round(float(sim.model.body_mass.sum())*1000, 2), passed=result['failure'] is None)
    return result


def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, mode='w', encoding='utf-8', delete=False) as staged:
        name = Path(staged.name)
        try:
            json.dump(payload, staged, separators=(',', ':'), allow_nan=False)
            staged.write('\n')
        except BaseException:
            staged.close()
            name.unlink(missing_ok=True)
            raise
    try:
        name.replace(path)
    finally:
        name.unlink(missing_ok=True)


def load_cache(path, key):
    try:
        entry = json.loads(path.read_text(encoding='utf-8'))
        return entry['result'] if entry.get('key') == key and entry['result']['trace'] else None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def run_batch(options, workers, cache=CACHE, *, progress=lambda update: None):
    settings = normalize(options)
    cases = cases_for(settings)
    digests = {}
    keys = [dependency_key(case, digests) for case in cases]
    entries = {key:load_cache(cache / f'{key}.json', key) for key in set(keys)}
    queued = {key:case for key,case in zip(keys,cases) if entries[key] is None}
    hits = sum(entries[key] is not None for key in keys)
    used_workers = min(workers, len(queued))
    progress(dict(total=len(cases), reused=hits, completed=hits, workers=used_workers))
    if queued:
        with ProcessPoolExecutor(max_workers=used_workers, mp_context=get_context('spawn')) as pool:
            futures = {pool.submit(run_case, case):key for key,case in queued.items()}
            completed = hits
            for future in as_completed(futures):
                key = futures[future]
                entries[key] = result = future.result()
                atomic_json(cache / f'{key}.json', dict(key=key, result=result))
                completed += keys.count(key)
                progress(dict(total=len(cases), reused=hits, completed=completed, workers=used_workers))
    rows = [dict(case=case, label=label(case), key=key, result=entries[key]) for case,key in zip(cases,keys)]
    return dict(schema=REPLAY_SCHEMA, created_at=datetime.now(timezone.utc).isoformat(), settings=settings, cases=rows,
                compute=dict(workers=used_workers, reused=hits, ran=len(queued)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--options', type=Path, help='Run a saved plan from the Triple M panel')
    parser.add_argument('--report', type=Path, default=CACHE / 'latest.json')
    parser.add_argument('--cache', type=Path, default=CACHE)
    parser.add_argument('--jobs', type=int, choices=range(1, 9), default=min(4, os.cpu_count() or 1))
    parser.add_argument('--expressions', action='store_true', help='Include head dance and both Microduck gestures')
    parser.add_argument('--serve', action='store_true', help='Enable the Run batch button on this computer')
    args = parser.parse_args()
    if args.serve:
        from triple_m_server import serve
        serve(run_batch, atomic_json, args.cache, args.jobs, ASSETS)
        return
    options = json.loads(args.options.read_text(encoding='utf-8')) if args.options else {}
    if args.expressions:
        options['moves'] = list(MOVE_LABELS)
    report = run_batch(options, args.jobs, args.cache)
    atomic_json(args.report, report)
    for row in report['cases']:
        print(row['label'], row['result']['failure'] or 'Pass')
    print(report['compute'], flush=True)


if __name__ == '__main__':
    main()
