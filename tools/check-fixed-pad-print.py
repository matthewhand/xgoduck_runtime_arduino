"""Screen the added solid of the printable chair against the recorded poses."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import runpy

from manifold3d import Manifold
import mujoco as mj
import numpy as np

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parent
dock = runpy.run_path(str(DIRECTORY / 'check-floor-dock.py'))
chair_body = runpy.run_path(str(DIRECTORY / 'export-fixed-pad-chair.py'))['chair_body']


def fixture_solid(module):
    size = np.array(module['size_m']) * 1000
    if 'ramp_deg' in module:
        length, width, height = size / 2
        rise = 2 * length * math.tan(math.radians(module['ramp_deg']))
        direction = math.copysign(1, rise)
        points = [(x, y, z)
                  for x, top in [(-length * direction, height - abs(rise)), (length * direction, height)]
                  for y in (-width, width) for z in (-height, top)]
        solid = Manifold.hull_points(points)
    else:
        solid = Manifold.cube(size, True)
    return solid.rotate([module.get(f'{axis}_deg', 0) for axis in ('roll', 'pitch', 'yaw')]).translate(
        np.array(module['center_m']) * 1000)


def robot_solids(model):
    for index in range(model.ngeom):
        kind = model.geom_type[index]
        if not model.geom_bodyid[index] or not model.geom_contype[index]:
            continue
        size = model.geom_size[index] * 1000
        if kind == mj.mjtGeom.mjGEOM_MESH:
            mesh = model.geom_dataid[index]
            first = model.mesh_vertadr[mesh]
            last = first + model.mesh_vertnum[mesh]
            solid = Manifold.hull_points(model.mesh_vert[first:last] * 1000)
        elif kind == mj.mjtGeom.mjGEOM_CAPSULE:
            radius, length = size[:2]
            solid = Manifold.cylinder(2 * length, radius, circular_segments=24, center=True)
            sphere = Manifold.sphere(radius, 24)
            solid += sphere.translate((0, 0, length)) + sphere.translate((0, 0, -length))
        elif kind == mj.mjtGeom.mjGEOM_BOX:
            solid = Manifold.cube(2 * size, True)
        else:
            raise ValueError(f'Unsupported robot collider {model.geom(index).name}: {kind}')
        name = model.geom(index).name or model.body(model.geom_bodyid[index]).name
        yield index, name, solid


def bounds_overlap(left, right):
    return all(left[i] < right[i + 3] and right[i] < left[i + 3] for i in range(3))


def inspect(trials):
    first = next(iter(trials.values()))
    skates = first['dock']['skates']
    sim = dock['WalkSimulation'](.12, 0, skates=skates,
                                configure=lambda spec: dock['build_scene'](spec, first['modules']))
    model = sim.model
    data = mj.MjData(model)
    wheels = [int(model.joint(name).qposadr[0]) for name in dock['WHEEL_NAMES']] if skates else []
    robot = list(robot_solids(model))
    added = chair_body(first['dock']['backrest_deg'], first['dock'].get('pad_inset_mm', 0))
    for module in first['modules']:
        if module['parent'] == 'world':
            added -= fixture_solid(module)
    bounds = added.bounding_box()
    overlaps = {}
    for name, trial in trials.items():
        phases = defaultdict(lambda: (0., '', 0., []))
        for frame in trial['trace']:
            data.qpos[:7] = frame['root']
            data.qpos[sim.qpos] = list(frame['joints_rad'].values())
            if skates:
                data.qpos[wheels] = frame['wheels_rad']
            mj.mj_kinematics(model, data)
            phase = frame['recovery']['phase']
            for index, link, solid in robot:
                transform = np.column_stack((data.geom_xmat[index].reshape(3, 3), data.geom_xpos[index] * 1000))
                placed = solid.transform(transform)
                if bounds_overlap(placed.bounding_box(), bounds):
                    intersection = added ^ placed
                    volume = intersection.volume()
                    if volume > max(.05, phases[phase][0]):
                        phases[phase] = (volume, link, frame['time_s'], intersection.bounding_box())
        overlaps[name] = {
            phase: [round(volume, 2), link, time, [round(value, 2) for value in box]]
            for phase, (volume, link, time, box) in phases.items() if volume
        }
    return overlaps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=ROOT / 'assets/sim/contact-dock-recording.json')
    parser.add_argument('--design', action='append', help='Select one or more designs from the recording')
    parser.add_argument('--output', type=Path, help='Save the per-phase intersections as JSON')
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding='utf8'))
    results = {}
    for name in args.design or list(report):
        trials = report[name]
        results[name] = inspect(trials)
        intersecting = sum(bool(phases) for phases in results[name].values())
        print(f'{name}: added print geometry intersects {intersecting}/{len(trials)} sampled trajectories', flush=True)
        for case, phases in results[name].items():
            if phases:
                phase, (volume, link, time, _) = max(phases.items(), key=lambda item: item[1][0])
                print(f'  {case}: {volume:g} mm³ with {link} at {time:g} s ({phase})', flush=True)
    if args.output:
        args.output.write_text(json.dumps(results, indent=2) + '\n', encoding='utf8')


if __name__ == '__main__':
    main()
