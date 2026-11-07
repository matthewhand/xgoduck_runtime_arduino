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
    parser.add_argument('--seconds', type=int, default=60, help='Run for 1–3600 seconds, or 0 continuously (default: 60)')
    parser.add_argument('--quiet', action='store_true', help='Write the current sample without printing every sample')
    args = parser.parse_args()
    if not 0 <= args.seconds <= 3600:
        parser.error('--seconds must be between 0 and 3600')
    if sys.platform != 'linux':
        parser.error('Run this collector on the UNO Q Linux host')
    os.nice(10)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sampler = GpuSampler()
    deadline = time.monotonic() + args.seconds if args.seconds else float('inf')
    # Keep a real MSM client counter readable even when no application renders.
    # An idle render-node descriptor submits no GPU work; unsupported counters
    # still remain unavailable rather than becoming a synthetic zero.
    probe = None
    try:
        probe = os.open('/dev/dri/renderD128', os.O_RDONLY | os.O_CLOEXEC)
    except OSError:
        pass
    try:
        while time.monotonic() < deadline:
            sample = sampler.sample()
            # Atomic replacement keeps the App Lab reader from seeing half a JSON file.
            temporary = args.output.with_name(args.output.name + '.tmp')
            temporary.write_text(json.dumps(sample, allow_nan=False) + '\n')
            temporary.replace(args.output)
            if not args.quiet:
                print(json.dumps(sample), flush=True)
            time.sleep(min(1., max(0., deadline - time.monotonic())))
    except KeyboardInterrupt:
        pass
    finally:
        if probe is not None:
            os.close(probe)
    # Keep the last sample as evidence. Both the app and MCU mark it stale.


if __name__ == '__main__':
    main()
