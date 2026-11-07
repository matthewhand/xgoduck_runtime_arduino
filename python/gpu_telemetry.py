"""Optional host load telemetry; no file I/O on the policy path."""
import json
from pathlib import Path
import threading
import time

CACHE_PATH = Path(__file__).resolve().parent.parent / '.cache/gpu-status.json'
MAX_AGE_S = 5.
CPU_DISABLED = dict(enabled=False, available=False, load_percent=None, busiest_core_percent=None)


def _percentage(value):
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                              or not 0 <= value <= 100):
        raise ValueError('Invalid activity percentage')
    return value


def _read_cpu(payload, age):
    if not isinstance(payload, dict):
        return dict(CPU_DISABLED, enabled=True, reason='Invalid CPU sample')
    try:
        value = _percentage(payload.get('load_percent'))
        busiest = _percentage(payload.get('busiest_core_percent'))
        return dict(payload, enabled=True, available=value is not None, load_percent=value,
                    busiest_core_percent=busiest, age_s=age)
    except ValueError as exc:
        return dict(CPU_DISABLED, enabled=True, reason=str(exc))


def read_sample(path=CACHE_PATH, now=None):
    now = time.time() if now is None else now
    disabled = dict(enabled=False, available=False, load_percent=None)
    has_cpu = False
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return disabled
    except OSError as exc:
        return dict(disabled, enabled=True, reason=str(exc))
    try:
        if len(raw) > 8192:
            raise ValueError('GPU sample is too large')
        sample = json.loads(raw)
        has_cpu = isinstance(sample, dict) and 'cpu' in sample
        stamp = sample['timestamp']
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
            raise ValueError('Invalid GPU sample timestamp')
        if sample.get('schema') != 1 or not now - MAX_AGE_S <= stamp <= now:
            raise ValueError('GPU sample is stale or incompatible')
        age = now - stamp
        try:
            value = _percentage(sample.get('load_percent'))
            result = dict(sample, enabled=True, available=value is not None, age_s=age)
        except ValueError as exc:
            result = dict(disabled, enabled=True, reason=str(exc), age_s=age)
        if has_cpu:
            result['cpu'] = _read_cpu(sample['cpu'], age)
        return result
    except (ValueError, TypeError, KeyError) as exc:
        result = dict(disabled, enabled=True, reason=str(exc))
        if has_cpu:
            result['cpu'] = dict(CPU_DISABLED, enabled=True, reason=str(exc))
        return result


class GpuTelemetry:
    def __init__(self, bridge, path=CACHE_PATH):
        self.bridge, self.path = bridge, path
        self.stop_event = threading.Event()
        self.latest = dict(enabled=False, available=False, load_percent=None)
        self.worker = threading.Thread(target=self.run, name='load-matrix1', daemon=True)

    def run(self):
        active = False
        while not self.stop_event.is_set():
            sample = read_sample(self.path)
            if sample['enabled'] or active:
                percent = round(sample['load_percent']) if sample['available'] else (-1 if sample['enabled'] else -2)
                cpu = sample.get('cpu', CPU_DISABLED)
                try:
                    if cpu['enabled']:
                        self.bridge.notify('duck_load', round(cpu['load_percent']) if cpu['available'] else -1, percent)
                    else:
                        self.bridge.notify('duck_gpu', percent)
                except Exception as exc:
                    sample['matrix_error'] = str(exc)
            active = sample['enabled']
            self.latest = sample
            self.stop_event.wait(1.)

    def start(self):
        self.worker.start()

    def stop(self):
        self.stop_event.set()
        self.worker.join(timeout=2)
