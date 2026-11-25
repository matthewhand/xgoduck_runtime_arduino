"""Plan Triple M cases across PCs, execute a partition, or merge its results."""

import argparse
from hashlib import sha256
from importlib import import_module
import json
import os
from pathlib import Path
from uuid import uuid4

triple_m = import_module('triple-m')
SCHEMA = 1


def read_json(path):
    with path.open(encoding='utf-8-sig') as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError(f'{path}: expected a JSON object.')
    return data


def manifest_id(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return sha256(encoded.encode()).hexdigest()


def make_manifest(options, shard_count):
    plan = triple_m.plan_batch(options)
    keys = [row['key'] for row in plan['cases']]
    if len(set(keys)) != len(keys):
        raise ValueError('The plan contains duplicate simulation cases.')
    if not 1 <= shard_count <= len(keys):
        raise ValueError(f'Choose between 1 and {len(keys)} partitions for this plan.')
    payload = dict(schema=SCHEMA, plan=plan, shards=[keys[i::shard_count] for i in range(shard_count)])
    return dict(payload, id=manifest_id(payload))


def read_manifest(path):
    manifest = read_json(path)
    payload = {key: value for key, value in manifest.items() if key != 'id'}
    if manifest.get('schema') != SCHEMA or manifest.get('id') != manifest_id(payload):
        raise ValueError('The batch manifest checksum or format does not match.')
    plan = manifest['plan']
    shards = manifest['shards']
    keys = [row['key'] for row in plan['cases']]
    if not shards or len(set(keys)) != len(keys) or len(shards) > len(keys):
        raise ValueError('The batch manifest does not describe unique cases and non-empty partitions.')
    if shards != [keys[i::len(shards)] for i in range(len(shards))]:
        raise ValueError('The partition assignments do not match the planned cases.')
    return manifest


def record_id(row):
    return {field: row[field] for field in ('key', 'case', 'label')}


def verify_report(manifest, shard, report):
    plan = manifest['plan']
    if report['runner'] != plan['runner'] or report['settings'] != plan['settings']:
        raise ValueError(f'Partition {shard} uses different simulation inputs or runner versions.')
    expected_keys = manifest['shards'][shard - 1]
    by_key = {row['key']: row for row in plan['cases']}
    if [record_id(row) for row in report['cases']] != [record_id(by_key[key]) for key in expected_keys]:
        raise ValueError(f'Partition {shard} has missing, duplicate, or unexpected cases.')
    for row in report['cases']:
        result = row.get('result')
        state = row.get('state')
        if state == 'error' and result is None and isinstance(row.get('error'), str) and row['error']:
            continue
        if isinstance(result, dict) and result.get('trace') and type(result.get('passed')) is bool:
            outcome = 'skipped' if result.get('skipped') else 'passed' if result['passed'] else 'failed'
            if state == outcome:
                continue
        raise ValueError(f"Partition {shard} has an invalid or incomplete result for {row['label']}.")


def run_shard(manifest, shard, workers, cache):
    if not 1 <= shard <= len(manifest['shards']):
        raise ValueError(f"Choose a partition from 1 to {len(manifest['shards'])}.")
    plan = manifest['plan']
    local_plan = triple_m.plan_batch(plan['settings'])
    if local_plan != plan:
        raise ValueError('This PC has different simulation files, policies, or runner versions from the plan.')
    report = triple_m.run_batch(plan['settings'], workers, cache, keys=manifest['shards'][shard - 1])
    verify_report(manifest, shard, report)
    return dict(schema=SCHEMA, manifest_id=manifest['id'], shard=shard, report=report)


def merge_reports(manifest, parts):
    reports = {}
    for part in parts:
        shard = part.get('shard')
        if (part.get('schema') != SCHEMA or part.get('manifest_id') != manifest['id']
                or type(shard) is not int or not 1 <= shard <= len(manifest['shards'])):
            raise ValueError('A partition belongs to a different batch or has an invalid number.')
        if shard in reports:
            raise ValueError(f'Partition {shard} was provided twice.')
        report = part['report']
        verify_report(manifest, shard, report)
        reports[shard] = report
    missing = sorted(set(range(1, len(manifest['shards']) + 1)) - reports.keys())
    if missing:
        raise ValueError(f"Missing partitions {', '.join(map(str, missing))}.")

    first = reports[1]
    if any(report['schema'] != first['schema'] for report in reports.values()):
        raise ValueError('Partitions use incompatible report formats.')
    outcomes = {row['key']: row for report in reports.values() for row in report['cases']}
    ordered = [outcomes[row['key']] for row in manifest['plan']['cases']]
    compute = {field: sum(report['compute'][field] for report in reports.values())
               for field in ('workers', 'reused', 'ran')}
    compute['shards'] = len(reports)
    compute['errors'] = sum(row.get('result') is None for row in ordered)
    counts = {state: sum(row['state'] == state for row in ordered)
              for state in ('pending', 'error', 'passed', 'failed', 'skipped')}
    state = 'error' if counts['error'] == len(ordered) else 'partial' if counts['error'] else 'complete'
    return dict(first, id=uuid4().hex, manifest_id=manifest['id'], cases=ordered, compute=compute, counts=counts,
                state=state, created_at=max(report['created_at'] for report in reports.values()))


def publish_merged(manifest, report, cache):
    from triple_m_batches import BatchStore

    batch = BatchStore.create(cache, dict(manifest['plan'], manifest_id=manifest['id']))
    for row in report['cases']:
        batch.save(row)
    batch.save_compute(report['compute'])
    return batch.report()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    plan = commands.add_parser('plan', help='Export a manifest to copy to every worker PC')
    plan.add_argument('--options', type=Path, help='Plan exported from Duck Lab')
    plan.add_argument('--shards', type=int, required=True)
    plan.add_argument('--out', type=Path, required=True)
    run = commands.add_parser('run', help='Run one numbered partition on this PC')
    run.add_argument('manifest', type=Path)
    run.add_argument('shard', type=int)
    run.add_argument('--jobs', type=int, choices=range(1, 9), default=min(4, os.cpu_count() or 1))
    run.add_argument('--cache', type=Path, default=triple_m.CACHE)
    run.add_argument('--out', type=Path, required=True)
    merge = commands.add_parser('merge', help='Merge all partitions into a Duck Lab report')
    merge.add_argument('manifest', type=Path)
    merge.add_argument('parts', type=Path, nargs='+')
    merge.add_argument('--out', type=Path, required=True)
    merge.add_argument('--publish', action='store_true', help='Also make the merged report available in the local runner')
    merge.add_argument('--cache', type=Path, default=triple_m.CACHE)
    args = parser.parse_args()
    try:
        if args.command == 'plan':
            payload = make_manifest(read_json(args.options) if args.options else {}, args.shards)
        else:
            manifest = read_manifest(args.manifest)
            if args.command == 'run':
                payload = run_shard(manifest, args.shard, args.jobs, args.cache)
            else:
                payload = merge_reports(manifest, [read_json(part) for part in args.parts])
                if args.publish:
                    payload = publish_merged(manifest, payload, args.cache)
        triple_m.atomic_json(args.out, payload)
    except (OSError, KeyError, ValueError, TypeError, AttributeError) as error:
        parser.error(str(error))
    print(args.out)
    if args.command == 'merge' and args.publish:
        print(f"http://127.0.0.1:19534/triple-m.html?source=local&report={payload['id']}")
    rows = (payload['report'] if args.command == 'run' else payload).get('cases', [])
    errors = sum(row.get('error') is not None and row.get('result') is None for row in rows)
    if errors:
        print(f'{errors} execution error(s) recorded. Rerun the affected partitions to retry.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
