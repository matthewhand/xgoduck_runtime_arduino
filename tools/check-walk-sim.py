#!/usr/bin/env python3
"""Check that the shipped ONNX policy walks in the native MuJoCo scene."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))

from walk_sim import JOINT_IDS, WalkSimulation


def main():
    sim = WalkSimulation(0.2, 0)
    start = sim.snapshot()
    for slot in range(300):
        assert not sim.tick(), f'Duck fell at slot {slot}'
    end = sim.snapshot()
    assert end['time_s'] == 6.0, end
    assert set(end['joints_rad']) == set(JOINT_IDS), end
    forward = end['root'][0] - start['root'][0]
    assert forward > 0.4, f'Expected forward motion over six seconds, got {forward:.3f} m'
    assert min(end['footfalls'].values()) >= 3, end
    assert end['root'][2] > 0.10, end
    print(f"Walk: {forward:.2f} m forward in 6 s, {end['footfalls']} foot contacts, upright")


if __name__ == '__main__':
    main()
