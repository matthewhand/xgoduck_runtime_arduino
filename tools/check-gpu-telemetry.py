import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'python'))
from gpu_stats import GpuSampler
from cpu_stats import CpuSampler
from board_health import BoardHealthSampler
from gpu_telemetry import GpuTelemetry, read_sample


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.proc = self.root / 'proc'
        self.proc.mkdir()
        self.now = 0.
        self.sampler = GpuSampler(self.proc, self.root / 'sys', lambda: self.now)

    def client(self, pid, client, ns):
        p = self.proc / str(pid) / 'fdinfo'
        p.mkdir(parents=True, exist_ok=True)
        (p / '3').write_text(f'drm-driver: msm\ndrm-client-id: {client}\ndrm-engine-gpu: {ns} ns\n')

    def test_real_time_delta_and_shared_descriptors(self):
        self.client(1, 7, 200_000_000)
        self.client(2, 7, 200_000_000)
        self.assertIsNone(self.sampler.sample()['load_percent'])
        self.now = 1.
        self.client(1, 7, 500_000_000)
        self.client(2, 7, 500_000_000)
        sample = self.sampler.sample()
        self.assertEqual(sample['clients'], 1)
        self.assertEqual(sample['load_percent'], 30.)

    def test_new_client_lifetime_not_counted_as_interval(self):
        self.client(1, 7, 0)
        self.sampler.sample()
        self.now = 1.
        self.client(1, 7, 100_000_000)
        self.client(2, 8, 999_000_000_000)
        self.assertEqual(self.sampler.sample()['load_percent'], 10.)

    def test_reset_and_saturation(self):
        self.client(1, 7, 50)
        self.sampler.sample()
        self.now = 1.
        self.client(1, 7, 0)
        self.assertEqual(self.sampler.sample()['load_percent'], 0.)
        self.now = 2.
        self.client(1, 7, 2_000_000_000)
        self.assertEqual(self.sampler.sample()['load_percent'], 100.)

    def test_unsupported_is_not_zero(self):
        self.assertIsNone(self.sampler.sample()['load_percent'])
        self.now = 1.
        self.assertIsNone(self.sampler.sample()['load_percent'])

    def test_kgsl_ratio(self):
        p = self.root / 'sys/class/kgsl/kgsl-3d0/gpubusy'
        p.parent.mkdir(parents=True)
        p.write_text('250 1000')
        sample = self.sampler.sample()
        self.assertEqual(sample['load_percent'], 25.)
        self.assertEqual(sample['scope'], 'device')

    def test_cache_validation(self):
        path = self.root / 'gpu.json'
        self.assertFalse(read_sample(path, 100.)['enabled'])
        for value in [0, 25.5, 100, None]:
            path.write_text(json.dumps(dict(schema=1, timestamp=99., load_percent=value)))
            result = read_sample(path, 100.)
            self.assertEqual(result['available'], value is not None)
            self.assertEqual(result['load_percent'], value)
        for value in [-1, 101, True, float('nan'), '25']:
            path.write_text(json.dumps(dict(schema=1, timestamp=99., load_percent=value)))
            self.assertFalse(read_sample(path, 100.)['available'])
        for stamp in [90., 101., True, float('nan'), 10**310]:
            path.write_text(json.dumps(dict(schema=1, timestamp=stamp, load_percent=25)))
            self.assertFalse(read_sample(path, 100.)['available'])
        for raw in ['{', '[]', '{}']:
            path.write_text(raw)
            self.assertFalse(read_sample(path, 100.)['available'])

    def test_cpu_aggregate_and_busiest_core(self):
        stat = self.proc / 'stat'
        stat.write_text('cpu 10 0 0 10 0 0 0 0 0 0\ncpu0 5 0 0 5 0 0 0 0 0 0\ncpu1 5 0 0 5 0 0 0 0 0 0\n')
        sampler = CpuSampler(stat)
        self.assertIsNone(sampler.sample()['load_percent'])
        stat.write_text('cpu 70 0 0 140 10 0 0 0 30 0\ncpu0 65 0 0 45 0 0 0 0 30 0\ncpu1 5 0 0 95 10 0 0 0 0 0\n')
        sample = sampler.sample()
        self.assertEqual(sample['load_percent'], 30.)
        self.assertEqual(sample['busiest_core_percent'], 60.)
        self.assertEqual(sample['cores'], 2)
        self.assertIsNone(sampler.sample()['load_percent'])
        stat.write_text('cpu 1 0 0 1\n')
        self.assertIsNone(sampler.sample()['load_percent'])

    def test_cpu_and_gpu_availability_are_independent(self):
        path = self.root / 'load.json'
        packet = dict(schema=1, timestamp=99., load_percent=None,
                      cpu=dict(load_percent=18., busiest_core_percent=55.))
        path.write_text(json.dumps(packet))
        sample = read_sample(path, 100.)
        self.assertFalse(sample['available'])
        self.assertEqual(sample['cpu']['busiest_core_percent'], 55.)
        self.assertFalse(read_sample(path, 105.)['cpu']['available'])
        packet.update(load_percent=22., cpu=dict(load_percent=True))
        path.write_text(json.dumps(packet))
        sample = read_sample(path, 100.)
        self.assertEqual(sample['load_percent'], 22.)
        self.assertFalse(sample['cpu']['available'])

    def test_load_rpc_and_legacy_gpu_rpc(self):
        path = self.root / 'load.json'
        for cpu, expected in [(dict(load_percent=25.), ('duck_load', 25, 41)),
                              (None, ('duck_gpu', 41))]:
            packet = dict(schema=1, timestamp=time.time(), load_percent=41.)
            if cpu is not None:
                packet['cpu'] = cpu
            path.write_text(json.dumps(packet))
            calls = []
            class Bridge:
                def notify(self, *args):
                    calls.append(args)
                    telemetry.stop_event.set()
            telemetry = GpuTelemetry(Bridge(), path)
            telemetry.run()
            self.assertEqual(calls, [expected])

    def test_board_health_and_cache(self):
        mem = self.proc / 'meminfo'
        mem.write_text('MemTotal: 4000 kB\nMemFree: 1000 kB\nMemAvailable: 2800 kB\n')
        thermal = self.root / 'thermal'
        for i, (name, value) in enumerate((('cpuss0-thermal', '38000'), ('cpuss1-thermal', '42300'),
                                           ('gpu-thermal', '60000'), ('cpuss2-thermal', 'invalid'))):
            zone = thermal / f'thermal_zone{i}'
            zone.mkdir(parents=True)
            (zone / 'type').write_text(name)
            (zone / 'temp').write_text(value)
        health = BoardHealthSampler(mem, thermal).sample()
        self.assertEqual(health, {'ram_percent': 30.0, 'temperature_c': 42.3})
        path = self.root / 'health.json'
        packet = dict(schema=1, timestamp=99., load_percent=None, health=health)
        path.write_text(json.dumps(packet))
        self.assertEqual(read_sample(path, 100.)['health'], health)
        self.assertNotIn('health', read_sample(path, 105.))
        health['ram_percent'] = True
        path.write_text(json.dumps(packet))
        self.assertEqual(read_sample(path, 100.)['health'], {'ram_percent': None, 'temperature_c': 42.3})


if __name__ == '__main__':
    unittest.main(verbosity=2)
