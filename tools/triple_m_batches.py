"""Durable Triple M manifests and independently addressable case results."""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from uuid import uuid4


BATCH_ID = re.compile(r'[0-9a-f]{32}')
CASE_KEY = re.compile(r'[0-9a-f]{64}')


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with NamedTemporaryFile(dir=path.parent, mode='w', encoding='utf-8', delete=False) as staged:
            name = Path(staged.name)
            json.dump(payload, staged, separators=(',', ':'), allow_nan=False)
            staged.write('\n')
        name.replace(path)
    finally:
        if name is not None:
            name.unlink(missing_ok=True)


def completed_row(case, result):
    state = 'skipped' if result.get('skipped') else 'passed' if result['passed'] else 'failed'
    return {**case, 'state': state, 'result': result}


def error_row(case, message):
    return {**case, 'state': 'error', 'result': None, 'error': str(message) or 'Simulation worker failed.'}


class BatchStore:
    def __init__(self, cache, batch_id):
        if BATCH_ID.fullmatch(batch_id) is None:
            raise FileNotFoundError(batch_id)
        self.path = cache / 'batches' / batch_id
        self.manifest = read_json(self.path / 'manifest.json')
        self.cases = {row['key']: row for row in self.manifest['cases']}

    @classmethod
    def create(cls, cache, plan):
        batch_id = uuid4().hex
        path = cache / 'batches' / batch_id / 'manifest.json'
        atomic_json(path, {**plan, 'id': batch_id, 'created_at': timestamp()})
        return cls(cache, batch_id)

    def matches(self, plan):
        return all(self.manifest.get(field) == value for field, value in plan.items())

    def mark_attempt(self):
        atomic_json(self.path.parent.parent / 'last-attempt.json', {'id': self.manifest['id']})

    def case(self, key, *, include_trace=True):
        if CASE_KEY.fullmatch(key) is None or key not in self.cases:
            raise KeyError(key)
        try:
            row = read_json(self.path / 'cases' / f'{key}.json')
        except FileNotFoundError:
            return {**self.cases[key], 'state': 'pending', 'result': None}
        result = row['result']
        if result is not None:
            if not include_trace:
                result.pop('trace', None)
            elif 'trace' not in result:
                result['trace'] = read_json(self.path / 'traces' / f'{key}.json')
        return row

    def save(self, row):
        key = row['key']
        if self.case(key, include_trace=False)['state'] not in ('pending', 'error'):
            return
        if row['result'] is not None:
            result = row['result'].copy()
            # A playable result becomes visible only after its trace is in place.
            atomic_json(self.path / 'traces' / f'{key}.json', result.pop('trace'))
            row = {**row, 'result': result}
        atomic_json(self.path / 'cases' / f'{key}.json', row)

    def save_compute(self, compute):
        atomic_json(self.path / 'compute.json', compute)

    def report(self, *, include_trace=True, running=False):
        rows = [self.case(entry['key'], include_trace=include_trace) for entry in self.manifest['cases']]
        counts = {kind: sum(row['state'] == kind for row in rows)
                  for kind in ('pending', 'error', 'passed', 'failed', 'skipped')}
        if running:
            state = 'running'
        elif counts['pending']:
            state = 'pending'
        elif counts['error']:
            state = 'error' if counts['error'] == len(rows) else 'partial'
        else:
            state = 'complete'
        try:
            compute = read_json(self.path / 'compute.json')
        except FileNotFoundError:
            compute = dict(workers=0, reused=0, ran=0)
        compute['errors'] = counts['error']
        return {**self.manifest, 'state': state, 'counts': counts, 'cases': rows, 'compute': compute}


def publish_latest(path, report):
    # The original report consumer expects a playable trace in every row.
    atomic_json(path, {**report, 'cases': [row for row in report['cases'] if row['result'] is not None]})
