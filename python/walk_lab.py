"""Start at most one bounded Duck Lab rollout and retain its latest sample."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from walk_sim import MODEL, RUN_S

PYTHON = Path(__file__).resolve().parent
DEPS = PYTHON.parent / '.cache/walk-sim-deps'


def walk_command(body):
    if set(body) - {'vx', 'yaw'}:
        raise ValueError('Only forward speed and turn rate are supported')
    values = body.get('vx', 0.2), body.get('yaw', 0.0)
    if any(type(value) not in (int, float) for value in values) or not (
            -0.25 <= values[0] <= 0.3 and -1 <= values[1] <= 1):
        raise ValueError('Set speed within −0.25 to 0.30 m/s and turn rate within ±1 rad/s')
    return values


class WalkLab:
    def __init__(self, board_missed):
        self.board_missed = board_missed
        self.lock = threading.Lock()
        self.process = None
        self.run_id = 0
        self.latest = {'state': 'idle'}

    def available(self):
        return (MODEL.is_file()
                and ((DEPS / 'mujoco/__init__.py').is_file()
                     or importlib.util.find_spec('mujoco') is not None))

    def _snapshot(self):
        result = dict(self.latest, available=self.available(), run_id=self.run_id, duration_s=RUN_S)
        if 'missed_at_start' in result:
            end = result.get('missed_at_end', self.board_missed())
            result['board_missed_delta'] = end - result['missed_at_start']
        return result

    def status(self):
        with self.lock:
            return self._snapshot()

    def start(self, vx, yaw):
        with self.lock:
            if self.process is not None:
                raise RuntimeError('A rollout is already active')
            if not self.available():
                raise RuntimeError('Headless MuJoCo is not installed on this UNO Q')
            env = dict(os.environ, MUJOCO_GL='disable', OPENBLAS_NUM_THREADS='1',
                       OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
                       PYTHONPATH=os.pathsep.join(filter(None, (str(DEPS), os.getenv('PYTHONPATH')))))
            missed_at_start = self.board_missed()
            self.process = subprocess.Popen(
                [sys.executable, '-B', str(PYTHON / 'walk_sim.py'), '--vx', str(vx), '--yaw', str(yaw)],
                env=env, stdout=subprocess.PIPE, text=True,
            )
            self.run_id += 1
            self.latest = dict(state='loading', vx=vx, yaw=yaw, missed_at_start=missed_at_start)
            threading.Thread(target=self._collect, args=(self.process,), name='walk-lab', daemon=True).start()
            return self._snapshot()

    def _collect(self, process):
        with process.stdout:
            for line in process.stdout:
                try:
                    sample = json.loads(line)
                except ValueError:
                    continue
                with self.lock:
                    if self.latest['state'] != 'stopping':
                        self.latest.update(sample)
        code = process.wait()
        with self.lock:
            self.process = None
            self.latest['missed_at_end'] = self.board_missed()
            if self.latest['state'] == 'stopping':
                self.latest['state'] = 'stopped'
            elif self.latest['state'] not in ('complete', 'fallen', 'error'):
                self.latest.update(state='error', detail=f'Walking worker exited ({code}). Check app logs.')

    def stop(self):
        with self.lock:
            if self.process is not None and self.latest['state'] in ('loading', 'running'):
                self.latest['state'] = 'stopping'
                self.process.terminate()
            return self._snapshot()
