"""Optional host-to-container GPU telemetry; no file I/O on the policy path."""
import json
import math
from pathlib import Path
import threading
import time

CACHE_PATH = Path(__file__).resolve().parent.parent / '.cache/gpu-status.json'
MAX_AGE_S = 5.


def read_sample(path=CACHE_PATH, now=None):
    now = time.time() if now is None else now
    disabled = dict(enabled=False, available=False, load_percent=None)
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
        stamp = sample['timestamp']
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp):
            raise ValueError('Invalid GPU sample timestamp')
        if sample.get('schema') != 1 or not 0 <= now - stamp <= MAX_AGE_S:
            raise ValueError('GPU sample is stale or incompatible')
        value = sample.get('load_percent')
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not math.isfinite(value) or not 0 <= value <= 100):
            raise ValueError('Invalid GPU percentage')
        return dict(sample, enabled=True, available=value is not None, age_s=now - stamp)
    except (ValueError, TypeError, KeyError) as exc:
        return dict(disabled, enabled=True, reason=str(exc))


class GpuTelemetry:
    def __init__(self, bridge, path=CACHE_PATH):
        self.bridge, self.path = bridge, path
        self.stop_event = threading.Event()
        self.latest = dict(enabled=False, available=False, load_percent=None)
        self.worker = threading.Thread(target=self.run, name='gpu-matrix1', daemon=True)

    def run(self):
        active = False
        while not self.stop_event.is_set():
            sample = read_sample(self.path)
            if sample['enabled'] or active:
                percent = round(sample['load_percent']) if sample['available'] else (-1 if sample['enabled'] else -2)
                try:
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
