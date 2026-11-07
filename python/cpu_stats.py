"""One-interval host CPU busy percentages from Linux /proc/stat."""
from pathlib import Path


class CpuSampler:
    def __init__(self, stat=Path('/proc/stat')):
        self.stat = Path(stat)
        self.previous = {}

    def sample(self):
        current = {}
        try:
            for line in self.stat.read_text().splitlines():
                fields = line.split()
                if not fields or (fields[0] != 'cpu' and not (
                        fields[0].startswith('cpu') and fields[0][3:].isdigit())):
                    continue
                # Guest time is already included in user/nice. Exclude those
                # duplicate columns; older kernels may omit optional columns.
                ticks = tuple(map(int, fields[1:9]))
                if len(ticks) >= 4 and min(ticks) >= 0:
                    current[fields[0]] = ticks + (0,) * (8 - len(ticks))
        except (OSError, ValueError):
            current = {}

        busy = {}
        for name in current.keys() & self.previous.keys():
            delta = [new - old for new, old in zip(current[name], self.previous[name])]
            total = sum(delta)
            if total > 0 and min(delta) >= 0:
                busy[name] = round(100 * (total - delta[3] - delta[4]) / total, 1)
        self.previous = current
        cores = [value for name, value in busy.items() if name != 'cpu']
        result = dict(load_percent=busy.get('cpu'), busiest_core_percent=max(cores, default=None),
                      cores=sum(name != 'cpu' for name in current), source='proc/stat', scope='host')
        if result['load_percent'] is None:
            result['reason'] = 'Waiting for CPU counter deltas' if current else 'No readable CPU counters'
        return result
