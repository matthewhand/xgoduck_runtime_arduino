"""Read real Linux GPU counters without adding inference dependencies.

Run the collector on the Linux host, outside App Lab's container. DRM fdinfo
reports activity for visible clients, not guaranteed whole-device utilization.
"""
from pathlib import Path
import re
import time


class GpuSampler:
    def __init__(self, proc=Path('/proc'), sys=Path('/sys'), clock=time.monotonic):
        self.proc, self.sys, self.clock = Path(proc), Path(sys), clock
        self.previous = {}
        self.previous_time = None

    def sample(self):
        now = self.clock()
        result = dict(schema=1, timestamp=time.time(), load_percent=None,
                      source=None, scope=None, clients=0, denied_processes=0)
        # KGSL reports busy and total microseconds since the previous read.
        kgsl = self.sys / 'class/kgsl/kgsl-3d0/gpubusy'
        try:
            busy, total = map(int, kgsl.read_text().split())
            if 0 <= busy <= total and total > 0:
                self.previous, self.previous_time = {}, None
                return dict(result, load_percent=round(100 * busy / total, 1),
                            source='kgsl/gpubusy', scope='device')
        except (OSError, ValueError):
            pass
        clients, denied = {}, 0
        try:
            processes = list(self.proc.iterdir())
        except OSError:
            processes = []
        for process in processes:
            if not process.name.isdigit():
                continue
            try:
                fds = list((process / 'fdinfo').iterdir())
            except PermissionError:
                denied += 1
                continue
            except OSError:
                continue
            for fd in fds:
                try:
                    values = dict(line.split(':', 1) for line in fd.read_text().splitlines() if ':' in line)
                    values = {key: value.strip() for key, value in values.items()}
                    if values.get('drm-driver') != 'msm':
                        continue
                    client = values['drm-client-id']
                    match = re.fullmatch(r'(\d+)\s+ns', values.get('drm-engine-gpu', ''))
                    if not match:
                        continue
                    key = (values.get('drm-pdev', 'platform-msm'), client)
                    # Shared descriptors can appear in several processes.
                    clients[key] = max(clients.get(key, 0), int(match[1]))
                except (OSError, KeyError, ValueError):
                    continue
        elapsed = None if self.previous_time is None else now - self.previous_time
        common = clients.keys() & self.previous.keys()
        if common and elapsed is not None and elapsed > 0:
            delta = sum(max(0, clients[key] - self.previous[key]) for key in common)
            result['load_percent'] = round(min(100., 100 * delta / (elapsed * 1e9)), 1)
        self.previous, self.previous_time = clients, now
        result.update(source='drm-fdinfo/msm' if clients else None,
                      scope='readable DRM clients', clients=len(clients), denied_processes=denied)
        if result['load_percent'] is None:
            result['reason'] = 'Waiting for two samples of the same GPU client' if clients else 'No readable GPU busy counters'
        return result
