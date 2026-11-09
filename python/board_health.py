"""Sample RAM and CPU subsystem temperature on the UNO Q Linux host."""
from pathlib import Path


class BoardHealthSampler:
    def __init__(self, meminfo=Path('/proc/meminfo'), thermal=Path('/sys/class/thermal')):
        self.meminfo = meminfo
        self.cpu_sensors = []
        for zone in thermal.glob('thermal_zone*'):
            try:
                name = (zone / 'type').read_text().strip()
            except OSError:
                continue
            if name.startswith('cpuss') and name.endswith('-thermal'):
                self.cpu_sensors.append(zone / 'temp')

    def sample(self):
        ram = None
        try:
            fields = dict(line.split(':', 1) for line in self.meminfo.read_text().splitlines() if ':' in line)
            total = int(fields['MemTotal'].split()[0])
            available = int(fields['MemAvailable'].split()[0])
            if total > 0 and 0 <= available <= total:
                ram = 100.0 * (total - available) / total
        except (OSError, KeyError, IndexError, ValueError):
            pass
        readings = []
        for sensor in self.cpu_sensors:
            try:
                raw = int(sensor.read_text())
                if 0 <= raw <= 125_000:
                    readings.append(raw / 1000)
            except (OSError, ValueError):
                continue
        return {'ram_percent': ram, 'temperature_c': max(readings) if readings else None}
