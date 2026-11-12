#!/usr/bin/env python3
"""Check that the shipped ONNX policy walks in the native MuJoCo scene."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))

from walk_sim import JOINT_IDS, RECOVERY_HOLD_S, RUN_S, SLOT_S, WalkSimulation
from search_mission import MISSION_S


def check_trial(pushes):
    sim = WalkSimulation(0.2, 0)
    start = sim.snapshot()
    applied = []
    for slot in range(round(RUN_S / SLOT_S)):
        if slot in pushes:
            sim.apply_push(pushes[slot])
            applied.append(sim.push)
        sim.tick()
        assert sim.recovery.phase == 'walk', f'Duck fell at slot {slot}'
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
    check_trial({200: 'nudge', 400: 'poke'})
    check_bash_getup()
    check_delivery()


def check_bash_getup():
    sim = WalkSimulation(0.2, 0)
    resume_xy = resume_feet = None
    getup_slots = 0
    for slot in range(round(RUN_S / SLOT_S)):
        if slot == 207:
            sim.apply_push('bash')
        sim.tick()
        if sim.recovery.phase == 'getup':
            assert sim.inference_ms is not None
            getup_slots += 1
        if sim.resumed_at_s is not None and resume_xy is None:
            resume_xy = sim.data.qpos[sim.root:sim.root + 2].copy()
            resume_feet = sim.footfalls.copy()
    result = sim.snapshot()
    assert sim.push['fell'] and sim.push['peak_tilt_deg'] > 90, result
    assert getup_slots >= 50 and 2 < sim.push['recovery_s'] < 6, result
    assert sim.push['time_s'] < sim.fall_at_s < sim.getup_at_s < sim.resumed_at_s < RUN_S, result
    assert sim.recovery.phase == 'walk' and result['root'][2] > 0.10, result
    assert min(sim.footfalls[foot] - count for foot, count in resume_feet.items()) >= 10, result
    travelled = float(sim.np.linalg.norm(sim.data.qpos[sim.root:sim.root + 2] - resume_xy))
    assert travelled > 1.0, result
    print(f"Bash: {sim.push['peak_tilt_deg']:.1f}° fall, {getup_slots} get-up inferences, "
          f"walking resumed after {sim.push['recovery_s']:.2f} s and moved {travelled:.2f} m")


def check_delivery():
    sim = WalkSimulation(0, 0, 'delivery')
    passed_divider = False
    for _ in range(round(MISSION_S / SLOT_S)):
        assert not sim.tick(), 'Duck fell before finishing delivery'
        x, y = sim.data.qpos[sim.root:sim.root + 2]
        passed_divider |= .72 <= x <= .78 and y > .26
        if sim.mission.found:
            break
    result = sim.snapshot()
    assert result['mission']['delivery']['delivered'] == 2 and passed_divider, result
    print(f"Delivery: reached both stations by the north passage in {result['time_s']:.2f} s")


if __name__ == '__main__':
    main()
