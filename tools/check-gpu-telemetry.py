import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'python'))
from gpu_stats import GpuSampler
from gpu_telemetry import read_sample


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
        for stamp in [90., 101., True, float('nan')]:
            path.write_text(json.dumps(dict(schema=1, timestamp=stamp, load_percent=25)))
            self.assertFalse(read_sample(path, 100.)['available'])
        for raw in ['{', '[]', '{}']:
            path.write_text(raw)
            self.assertFalse(read_sample(path, 100.)['available'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
