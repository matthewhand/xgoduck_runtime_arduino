#!/usr/bin/env python3
"""Collect host GPU activity into the app's shared .cache directory."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'python'))
from gpu_stats import GpuSampler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent.parent / '.cache/gpu-status.json')
    parser.add_argument('--seconds', type=int, default=60, help='Run for 1–3600 seconds (default: 60)')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error('--seconds must be between 1 and 3600')
    if sys.platform != 'linux':
        parser.error('Run this collector on the UNO Q Linux host')
    os.nice(10)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sampler = GpuSampler()
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            sample = sampler.sample()
            # Atomic replacement keeps the App Lab reader from seeing half a JSON file.
            temporary = args.output.with_name(args.output.name + '.tmp')
            temporary.write_text(json.dumps(sample, allow_nan=False) + '\n')
            temporary.replace(args.output)
            print(json.dumps(sample), flush=True)
            time.sleep(min(1., max(0., deadline - time.monotonic())))
    except KeyboardInterrupt:
        pass
    # Keep the last sample as evidence. Both the app and MCU mark it stale.


if __name__ == '__main__':
    main()
