"""Run matched docking approaches with a fixed transverse bar in the entry lane."""
import argparse
import math
from pathlib import Path
import runpy

import numpy as np

dock = runpy.run_path(str(Path(__file__).with_name('check-floor-dock.py')))
mj = dock['mj']
FEET = 'Feet · Lean into trip bar'
SKATES = 'Skates · Step over trip bar'
WIDTH = .008
LANES = {'centred': (0, 0), '8 mm left': (.008, 0), '8 mm right': (-.008, 0),
         'left with 5° yaw': (.008, 5), 'right with -5° yaw': (-.008, -5)}


def pitch(sim):
    w, x, y, z = sim.data.qpos[sim.root + 3:sim.root + 7]
    return math.degrees(math.asin(np.clip(2 * (w*y - x*z), -1, 1)))


class BarEntry:
    def __init__(self, skates, x, height, *, bar=True, active=True, span=.22):
        self.skates, self.x, self.height, self.active = skates, x, height, active
        self.fixtures = [{'name': 'Trip bar', 'center_m': [x, 0, height / 2],
                          'size_m': [WIDTH, span, height]}] if bar else []
        self.metrics = dict(bar_mm=height*1000 if bar else 0, bar_x_m=x, span_mm=round(span*1000) if bar else 0, attempted=False, step_commanded=skates and active, catch_s=None,
                            leaned_on_bar=False, pitch_on_bar_deg=None, peak_braced_force_n=0.,
                            pitch_before_seat_deg=None, skates_across=[], clean_step=False, bar_hit_during_step=False, lift_mm={})

    def run(self, sim, record, lowering):
        m, d = sim.model, sim.data
        metrics = self.metrics
        metrics['attempted'] = True
        bar = m.geom('Trip bar').id if self.fixtures else -1
        seat = {m.geom(name).id for name in ('Seat lip', 'Backrest', 'Left seat contact', 'Right seat contact')}
        touched_seat = False
        hit_bar = False
        swing = {}
        vertices = {}
        for geom in sim.feet:
            mesh = m.geom_dataid[geom]
            begin = m.mesh_vertadr[mesh]
            vertices[geom] = m.mesh_vert[begin:begin + m.mesh_vertnum[mesh]]
        force = np.zeros(6)

        def bounds(geom):
            return vertices[geom] @ d.geom_xmat[geom].reshape(3, 3).T + d.geom_xpos[geom]

        def wheels_on_side(side):
            return [bounds(geom) for geom, which in sim.feet.items() if which == side]

        # A skate counts only if both tyres start entirely before the obstacle,
        # lift above it together and finish completely on the chair side.
        initial = {side: all(v[:, 0].min() > self.x + WIDTH/2 for v in wheels_on_side(side))
                   for side in ('left', 'right')} if self.skates else {}

        def observe(phase):
            nonlocal touched_seat, hit_bar
            angle = pitch(sim)
            touched_seat |= any(c.dist < 0 and any(g in seat for g in c.geom) for c in d.contact)
            for idx, contact in enumerate(d.contact):
                if contact.dist >= 0:
                    continue
                a, b = contact.geom
                if bar not in (a, b):
                    continue
                other = b if a == bar else a
                hit_bar = True
                if other in sim.feet and not self.skates and not touched_seat:
                    mj.mj_contactForce(m, d, idx, force)
                    # Require load against the approach face, excluding standing on top.
                    if abs(contact.frame[0]) >= .5 and contact.pos[0] >= self.x and force[0] >= .1:
                        metrics['peak_braced_force_n'] = max(metrics['peak_braced_force_n'], round(float(force[0]), 2))
                        if angle <= -5:
                            prev = metrics['pitch_on_bar_deg']
                            metrics['pitch_on_bar_deg'] = round(angle if prev is None else min(prev, angle), 1)
                            if not metrics['leaned_on_bar']:
                                metrics['catch_s'] = round(d.time, 3)
                                record(phase)
                            metrics['leaned_on_bar'] = True
            if not touched_seat:
                prev = metrics['pitch_before_seat_deg']
                metrics['pitch_before_seat_deg'] = round(angle if prev is None else min(prev, angle), 1)
            if phase.startswith('step_'):
                for side in ('left', 'right'):
                    tyres = wheels_on_side(side)
                    lift = min(float(v[:, 2].min()) for v in tyres)
                    metrics['lift_mm'][side] = max(metrics['lift_mm'].get(side, 0.), round(1000*lift, 1))
                    if lift > self.height:
                        swing[side] = True
                    if (initial[side] and swing.get(side) and side not in metrics['skates_across']
                            and all(v[:, 0].max() < self.x - WIDTH/2 for v in tyres)):
                        metrics['skates_across'].append(side)

        def move(target, slots, phase):
            previous = d.ctrl[sim.actuators].copy()
            record(phase)
            for tick in range(1, slots + 1):
                blend = dock['smoothstep'](tick / slots)
                d.ctrl[sim.actuators] = previous + blend*(target - previous)
                for _ in range(round(dock['SLOT_S'] / dock['STEP_S'])):
                    mj.mj_step(m, d)
                    observe(phase)
                if tick % 2 == 0 or tick == slots:
                    record(phase)

        if self.skates and self.active:
            home = d.ctrl[sim.actuators].copy()
            for side, sign, indices in [('left', 1, slice(2, 5)), ('right', -1, slice(11, 14))]:
                target = home.copy()
                target[indices] = sign * np.array([.70, .30, -.40])
                move(target, 6, 'step_' + side)
                target[indices] = sign * np.array([.42, -.25, -.67])
                move(target, 5, 'step_' + side)
            move(home, 5, 'step_settle')
            metrics['bar_hit_during_step'] = hit_bar
            metrics['clean_step'] = (len(metrics['skates_across']) == 2 and not hit_bar
                                     and d.xmat[sim.trunk, 8] >= .94 and
                                     all(all(v[:, 0].max() < self.x - WIDTH/2 for v in wheels_on_side(side))
                                         for side in ('left', 'right')))
            # Do not teleport to the chair or initiate a sit from a fallen pose.
            if d.qpos[sim.root] > .185 or d.qpos[sim.root + 2] < .105 or d.xmat[sim.trunk, 8] < .80:
                return False
        for slots, angles in lowering:
            move(dock['rise_target'](sim, angles), slots, 'sitting' if self.skates else 'lean_back')
        return True


def trial(skates, x, height, y, yaw, speed, *, bar=True, active=True, trigger=None, span=.22):
    maneuver = BarEntry(skates, x, height, bar=bar, active=active, span=span)
    if trigger is None:
        trigger = x + .070 if skates and active else .175
    result = dock['evaluate']('Fixed pad chair', (0, 0, 0), skates=skates, angle=40,
                              settle_s=2.6, pad_inset_m=.008, approach_start=(.32, y, yaw, speed),
                              trigger=trigger, entry_maneuver=maneuver, skate_roll=.08 if skates else None,
                              roller_release=skates, contact_handoff=skates)
    data = result['dock']
    data['bar_entry'] = entry = maneuver.metrics
    tail = result['trace'][-1]['root']
    # A forward departure must finish beyond the obstruction with the body upright.
    exit_ok = bool(result['passed'] and tail[0] > x + .10 and 1-2*(tail[4]**2+tail[5]**2) >= .95
                   and data['side_tilt_deg'] <= 25
                   and (not skates or data['roller_release']['wheels_only_exit']))
    entry['dock_and_exit'] = exit_ok
    entry['maneuver_passed'] = bool(entry['clean_step'] if skates else entry['leaned_on_bar'])
    result['passed'] = bool(exit_ok and (entry['maneuver_passed'] if bar and active else True))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--recording', type=Path, required=True)
    args = parser.parse_args()
    results, recordings = {}, {FEET: {}, SKATES: {}}
    for height in (.006, .012):
        for name, (y, yaw) in LANES.items():
            case = f'Trip bar · {height*1000:.0f} mm · {name}'
            for skates, label, speed in ((False, FEET, .16), (True, SKATES, .28)):
                controls = ['active', 'no bar', 'short bar']
                if skates:
                    controls.extend(['coast', 'clear lane'])
                for control in controls:
                    run = trial(skates, .140, height, y, yaw, speed, bar=control not in ('no bar', 'clear lane'),
                                active=control not in ('coast', 'clear lane') and not (skates and control == 'short bar'),
                                span=.060 if control == 'short bar' else .220)
                    results.setdefault(case, {})[label + ' / ' + control] = run['dock']
                    if control == 'active':
                        recordings[label][case] = run
                    elif name == 'centred' and ((skates and control == 'clear lane') or (not skates and control == 'no bar')):
                        key = 'Skates · Clear lane' if skates else 'Feet · Clear lane'
                        recordings.setdefault(key, {})[case] = run
                    elif control == 'short bar' and name == 'centred':
                        key = 'Skates · Coast beside short bar' if skates else 'Feet · Lean into short bar'
                        recordings.setdefault(key, {})[case] = run
    dock['write_report'](args.results, results)
    dock['write_report'](args.recording, recordings)


if __name__ == '__main__':
    main()
