"""Small snapshots exchanged with the UNO Q host pond worker."""
import json
from pathlib import Path
import time

CACHE = Path(__file__).resolve().parent.parent / '.cache'
INPUT = CACHE / 'pond-input.json'
OUTPUT = CACHE / 'pond-output.json'


def write_sample(path, sample):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(dict(sample, timestamp=time.time()), separators=(',', ':')),
                         encoding='utf-8')
    temporary.replace(path)


def read_sample(path):
    try:
        sample = json.loads(path.read_text(encoding='utf-8'))
        return sample if 0 <= time.time() - sample['timestamp'] <= 1.5 else None
    except (OSError, ValueError, TypeError, KeyError):
        return None
