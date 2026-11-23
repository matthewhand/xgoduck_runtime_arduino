"""Bounded, passive recorder for the stock hardware walk/get-up policy."""
from datetime import datetime, timezone
from pathlib import Path
import threading
import time
from uuid import uuid4

from walk_lab import RELEASE, load_peaks, read_record, save_report


REPORT = Path(__file__).resolve().parents[1] / '.cache/physical-trial-report.json'
LIMIT_S = 60


def start_blocker(sample):
    if not sample['ready']:
        return 'Waiting for all 15 servos and a fresh IMU reading.'
    if sample['enabled'] or sample['arm_pending'] or sample['mode'] not in ('off', 'shadow'):
        return 'Turn torque off before starting a capture.'
    if not sample['stock']:
        return 'Select the stock walking setup before starting a capture.'
    return None


class PhysicalTrial:
    def __init__(self, snapshot, board_load):
        self.snapshot = snapshot
        self.board_load = board_load
        self.lock = threading.Lock()
        self.run = None
        self.worker = None
        saved = read_record(REPORT)
        self.latest_report = saved if saved.get('source') == 'physical-duck' and saved.get('run_key') else None

    def status(self):
        with self.lock:
            sample = self.snapshot()
            blocked = start_blocker(sample)
            report = self.latest_report or {}
            active = self.run is not None
            return dict(recording=active, ready=sample['ready'], can_start=not active and blocked is None,
                        blocked=blocked, run_key=self.run['run_key'] if active else None,
                        elapsed_s=round(sample['now'] - self.run['began'], 1) if active else None,
                        walking=active and sample['mode'] == 'policy' and sample['enabled'] and sample['ready'],
                        report_run_key=report.get('run_key'), report_state=report.get('state'),
                        report_end_reason=report.get('end_reason'))

    def report(self):
        with self.lock:
            return self.latest_report

    def start(self):
        with self.lock:
            if self.run is not None:
                raise RuntimeError('A physical capture is already recording.')
            first = self.snapshot()
            blocked = start_blocker(first)
            if blocked:
                raise RuntimeError(blocked)
            stop = threading.Event()
            run = dict(run_key=uuid4().hex, began=first['now'], stop=stop)
            self.run = run
            self.worker = threading.Thread(target=self._record, args=(first, run),
                                           name='physical-trial', daemon=True)
            self.worker.start()
        return self.status()

    def stop(self, run_key):
        with self.lock:
            if not self.run or self.run['run_key'] != run_key:
                raise RuntimeError('This physical capture has already ended or changed.')
            self.run['stop'].set()
        return self.status()

    def close(self):
        with self.lock:
            if self.run:
                self.run['stop'].set()
            worker = self.worker
        if worker:
            worker.join(timeout=1)

    def _record(self, first, run):
        began, stop = run['began'], run['stop']
        stamp = datetime.now(timezone.utc).isoformat()
        release = read_record(RELEASE).get('commit')
        loads, recoveries = [], []
        cursor = next_load_at = began
        recovery = None
        first_walk = last_walk = walk_generation = None
        missed = first['loop_missed']
        while True:
            sample = self.snapshot()
            now = sample['now']
            for timestamp, generation, phase in sample['events']:
                if timestamp <= cursor:
                    continue
                cursor = timestamp
                elapsed = round(timestamp - began, 3)
                if phase == 'default_pose':
                    recovery = dict(fall_at_s=elapsed, getup_at_s=None, resumed_at_s=None, fall_to_walk_s=None)
                    recoveries.append(recovery)
                    recovery_generation = generation
                    fall_at = timestamp
                elif recovery is not None and generation == recovery_generation:
                    if phase == 'getup':
                        recovery['getup_at_s'] = elapsed
                    elif recovery['getup_at_s'] is not None:
                        recovery['resumed_at_s'] = elapsed
                        recovery['fall_to_walk_s'] = round(timestamp - fall_at, 3)
                        recovery = None

            if not sample['ready']:
                end = 'feedback_lost'
                break
            if not sample['stock'] or sample['mode'] not in ('off', 'shadow', 'hold', 'policy'):
                end = 'stock_mode_changed'
                break
            walking = sample['mode'] == 'policy' and sample['enabled']
            if first_walk is not None and (not walking or sample['generation'] != walk_generation):
                end = 'policy_ended'
                break
            if walking:
                if first_walk is None:
                    first_walk, walk_generation = now, sample['generation']
                last_walk = now
                if now >= next_load_at:
                    loads.append(dict(elapsed_s=round(now - began, 3),
                                      board_missed_slots=sample['loop_missed'] - missed,
                                      phase=sample['phase'], command=sample['command'], **self.board_load()))
                    next_load_at = now + 1
            if stop.is_set() or now - began >= LIMIT_S:
                end = 'operator' if stop.is_set() else 'time_limit'
                break
            stop.wait(.1)

        state = ('interrupted' if end in ('feedback_lost', 'stock_mode_changed') else
                 'complete' if first_walk is not None or recoveries else 'no_motion')
        report = dict(schema=1, source='physical-duck', run_id=run['run_key'][:8], run_key=run['run_key'],
                      release=release, started_at=stamp, finished_at=datetime.now(timezone.utc).isoformat(),
                      state=state, end_reason=end, time_s=round(now - began, 3),
                      policy_active_s=round(last_walk - first_walk, 3) if first_walk is not None else 0,
                      loaded_policy_sha256=first['policies_sha256'], sim_missed_slots=None,
                      board_missed_slots=sample['loop_missed'] - missed, load_samples=loads,
                      load_peaks=load_peaks(loads), pushes=[], recoveries=recoveries)
        with self.lock:
            self.latest_report = report
            save_report(REPORT, report)
            self.run = None
            self.worker = None
