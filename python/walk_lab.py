"""Start at most one bounded Duck Lab rollout and retain its latest sample."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from uuid import uuid4

from walk_sim import MODEL, PUSH_SPEEDS, RUN_S
from search_mission import ARENAS, MISSION_S

PYTHON = Path(__file__).resolve().parent
DEPS = PYTHON.parent / '.cache/walk-sim-deps'


def walk_command(body):
    if 'arena' in body:
        if set(body) != {'arena'} or body['arena'] not in ARENAS:
            raise ValueError('Choose a valid search arena')
        return 0.0, 0.0, body['arena']
    if set(body) - {'vx', 'yaw'}:
        raise ValueError('Only forward speed and turn rate are supported for a walking trial')
    values = body.get('vx', 0.2), body.get('yaw', 0.0)
    if any(type(value) not in (int, float) for value in values) or not (
            -0.25 <= values[0] <= 0.3 and -1 <= values[1] <= 1):
        raise ValueError('Set speed within −0.25 to 0.30 m/s and turn rate within ±1 rad/s')
    return (*values, None)


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
        result = dict(self.latest, available=self.available(), run_id=self.run_id,
                      duration_s=MISSION_S if self.latest.get('arena') else RUN_S)
        if 'missed_at_start' in result:
            end = result.get('missed_at_end', self.board_missed())
            result['board_missed_delta'] = end - result['missed_at_start']
        return result

    def status(self):
        with self.lock:
            return self._snapshot()

    def start(self, vx, yaw, arena):
        with self.lock:
            if self.process is not None:
                raise RuntimeError('A rollout is already active')
            if not self.available():
                raise RuntimeError('Headless MuJoCo is not installed on this UNO Q')
            env = dict(os.environ, MUJOCO_GL='disable', OPENBLAS_NUM_THREADS='1',
                       OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
                       PYTHONPATH=os.pathsep.join(filter(None, (str(DEPS), os.getenv('PYTHONPATH')))))
            missed_at_start = self.board_missed()
            command = [sys.executable, '-B', str(PYTHON / 'walk_sim.py'), '--vx', str(vx), '--yaw', str(yaw)]
            if arena:
                command.extend(['--arena', arena])
            else:
                command.append('--interactive')
            self.process = subprocess.Popen(
                command, env=env, stdin=subprocess.PIPE if arena is None else None,
                stdout=subprocess.PIPE, text=True,
            )
            self.run_id += 1
            self.latest = dict(state='loading', vx=vx, yaw=yaw, arena=arena,
                               missed_at_start=missed_at_start, run_key=uuid4().hex)
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
                        push = sample.get('push')
                        if push and push['time_s'] != self.latest.get('push', {}).get('time_s'):
                            self.latest['push_pending'] = False
                        self.latest.update(sample)
        code = process.wait()
        with self.lock:
            if process.stdin is not None:
                process.stdin.close()
            self.process = None
            self.latest.pop('push_pending', None)
            self.latest['missed_at_end'] = self.board_missed()
            if self.latest['state'] == 'stopping':
                self.latest['state'] = 'stopped'
            elif self.latest['state'] not in ('complete', 'found', 'fallen', 'error'):
                self.latest.update(state='error', detail=f'Walking worker exited ({code}). Check app logs.')

    def push(self, run_id, kind):
        if type(run_id) is not int or not isinstance(kind, str) or kind not in PUSH_SPEEDS:
            raise ValueError('Choose Poke, Nudge, or Bash for a valid walking trial.')
        with self.lock:
            if (self.process is None or self.latest['state'] != 'running'
                    or self.latest.get('arena') or self.run_id != run_id):
                raise RuntimeError('Start a walking trial before applying a push.')
            push = self.latest.get('push')
            phase = self.latest.get('recovery', {}).get('phase', 'walk')
            if phase != 'walk' or self.latest.get('push_pending') or (push and push['recovery_s'] is None):
                raise RuntimeError('Wait for the Duck to recover before pushing again.')
            try:
                # One short write fits in the pipe because at most one push is pending.
                os.write(self.process.stdin.fileno(), kind.encode('ascii'))
            except OSError as exc:
                raise RuntimeError('The walking trial has ended.') from exc
            self.latest['push_pending'] = True
            return self._snapshot()

    def stop(self, run_key=None):
        with self.lock:
            if ((run_key is None or self.latest.get('run_key') == run_key) and self.process is not None
                    and self.latest['state'] in ('loading', 'running')):
                self.latest['state'] = 'stopping'
                self.process.terminate()
            return self._snapshot()
