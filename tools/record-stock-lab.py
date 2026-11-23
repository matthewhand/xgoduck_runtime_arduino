#!/usr/bin/env python3
"""Record the stock walking and four get-up cases for Duck Lab."""

import hashlib
import json
from pathlib import Path
import runpy


REPO = Path(__file__).resolve().parents[1]


def main():
    checks = runpy.run_path(str(REPO / 'tools/check-duck-hardware.py'))
    report = {'stock': {}, 'source': {
        'description': 'Stock MuJoCo trials using the shipped walking and get-up policies',
        'policies_sha256': {name: hashlib.sha256(
            (REPO / 'python' / f'xgoduck_{name}.onnx').read_bytes()).hexdigest()
            for name in ('walk', 'getup')},
    }}
    for label, case in [('Walking', 'walk'), ('Get up from back', 'back'),
                        ('Get up from right side', 'right'), ('Get up from front', 'front'),
                        ('Get up from left side', 'left')]:
        trace = []
        result = checks['run_case'](case, [], {}, trace)
        result['passed'] = checks['passes'](case, result, result)
        # Keep 25 Hz poses plus the final frame.
        kept = trace[::2]
        if kept[-1] is not trace[-1]:
            kept.append(trace[-1])
        result['trace'] = kept
        report['stock'][label] = result
        print(f'{label}: {result["passed"]} (recovery {result["recovered_s"]})', flush=True)
    destination = REPO / 'assets/sim/stock-replay.json'
    destination.write_text(json.dumps(report, separators=(',', ':'), allow_nan=False) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
