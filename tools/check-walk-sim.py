#!/usr/bin/env python3
"""Check that the shipped ONNX policy walks in the native MuJoCo scene."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))

from walk_sim import JOINT_IDS, RECOVERY_HOLD_S, RUN_S, SLOT_S, WalkSimulation


def check_trial(pushes):
    sim = WalkSimulation(0.2, 0)
    start = sim.snapshot()
    applied = []
    for slot in range(round(RUN_S / SLOT_S)):
        if slot in pushes:
            sim.apply_push(pushes[slot])
            applied.append(sim.push)
        assert not sim.tick(), f'Duck fell at slot {slot}'
        assert sim.data.qpos[sim.root + 2] > 0.10, f'Trunk dropped at slot {slot}'
    end = sim.snapshot()
    assert end['time_s'] == RUN_S, end
    assert set(end['joints_rad']) == set(JOINT_IDS), end
    forward = end['root'][0] - start['root'][0]
    assert forward > 1.5, f'Expected forward motion over {RUN_S} seconds, got {forward:.3f} m'
    assert min(end['footfalls'].values()) >= 10, end
    for push in applied:
        assert push['recovery_s'] is not None and RECOVERY_HOLD_S <= push['recovery_s'] < 2, push
        print(f"{push['kind']} at {push['time_s']:.2f} s: recovered in {push['recovery_s']:.2f} s, peak tilt {push['peak_tilt_deg']:.1f}°")
    print(f"Walk: {forward:.2f} m forward in {RUN_S} s, {end['footfalls']} foot contacts, upright")


def main():
    check_trial({})
    check_trial({207: 'bash', 400: 'nudge', 600: 'poke'})


if __name__ == '__main__':
    main()
