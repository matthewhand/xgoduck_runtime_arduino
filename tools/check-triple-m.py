"""Regression checks for Triple M cache integrity and resumable batches."""

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from triple_m_batches import BatchStore, atomic_json, publish_latest, read_json


triple_m = import_module('triple-m')
OPTIONS = dict(moves=['walk'], builds=['stock', 'backpack'], faults=['nominal'])


def sample_result():
    return dict(passed=True, failure=None, trace=[dict(time_s=0., root=[0., 0., .2, 1., 0., 0., 0.],
                                                      joints_rad=dict.fromkeys(triple_m.JOINT_IDS, 0.))])


class BatchChecks(unittest.TestCase):
    def test_unrelated_changes_reuse_case_keys(self):
        plan = triple_m.plan_batch(OPTIONS)
        cases = [row['key'] for row in plan['cases']]
        lighter = triple_m.plan_batch({**OPTIONS, 'pack_g': 5})
        self.assertEqual(cases[0], lighter['cases'][0]['key'])
        self.assertNotEqual(cases[1], lighter['cases'][1]['key'])
        unrelated = triple_m.plan_batch({**OPTIONS, 'jam_s': 1.2})
        self.assertEqual(cases, [row['key'] for row in unrelated['cases']])

    def test_expression_uses_controller_fingerprint(self):
        options = {**OPTIONS, 'moves': ['walk', 'dance']}
        cases = triple_m.plan_batch(options)['cases']
        prior = triple_m.digest_file

        def changed_controller(path, digests):
            return 'modified' if path.name == 'controller.py' else prior(path, digests)

        with patch.object(triple_m, 'digest_file', changed_controller):
            changed = triple_m.plan_batch(options)['cases']
        for before, after in zip(cases, changed):
            self.assertEqual(before['key'] != after['key'], before['case']['move'] == 'dance')

    def test_malformed_case_cache_is_ignored(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'case.json'
            result = sample_result()
            atomic_json(path, dict(key='a', result=result))
            self.assertIsNotNone(triple_m.load_cache(path, 'a'))
            self.assertIsNone(triple_m.load_cache(path, 'b'))
            result['trace'][0]['joints_rad'].pop(triple_m.JOINT_IDS[0])
            atomic_json(path, dict(key='a', result=result))
            self.assertIsNone(triple_m.load_cache(path, 'a'))

    def test_failed_worker_can_resume_without_overwriting_completed_case(self):
        with TemporaryDirectory() as folder, patch.object(triple_m, 'ProcessPoolExecutor',
                side_effect=lambda max_workers, **_: ThreadPoolExecutor(max_workers=max_workers)):
            cache = Path(folder)
            plan = triple_m.plan_batch(OPTIONS)
            batch = BatchStore.create(cache, plan)
            stock, backpack = (row['key'] for row in plan['cases'])
            with patch.object(triple_m, 'run_pinned_case', side_effect=[sample_result(), RuntimeError('Offline')]):
                report = triple_m.run_batch(OPTIONS, 1, cache, batch=batch)
            self.assertEqual(report['state'], 'partial')
            self.assertEqual(batch.case(stock)['state'], 'passed')
            self.assertEqual(batch.case(backpack)['error'], 'Offline')
            self.assertNotIn('trace', batch.report(include_trace=False)['cases'][0]['result'])
            self.assertIn('trace', batch.case(stock)['result'])
            publish_latest(cache / 'latest.json', report)
            self.assertEqual(len(read_json(cache / 'latest.json')['cases']), 1)
            with patch.object(triple_m, 'run_pinned_case', return_value=sample_result()) as worker:
                resumed = triple_m.run_batch(OPTIONS, 2, cache, batch=BatchStore(cache, report['id']))
            self.assertEqual(resumed['state'], 'complete')
            self.assertEqual(resumed['id'], report['id'])
            self.assertEqual(resumed['compute']['reused'], 1)
            worker.assert_called_once_with(plan['cases'][1]['case'], backpack)

    def test_missing_expression_does_not_stop_unrelated_case(self):
        name = 'flamingo-cycle'
        options = {**OPTIONS, 'builds': ['stock'], 'moves': ['walk', name]}
        with TemporaryDirectory() as folder, patch.object(triple_m, 'ProcessPoolExecutor',
                side_effect=lambda max_workers, **_: ThreadPoolExecutor(max_workers=max_workers)), \
                patch.dict(triple_m.EXPRESSION_ASSETS, {name: ('repo', 'commit', 'absent-digest')}), \
                patch.object(triple_m, 'run_pinned_case', return_value=sample_result()) as worker:
            cache = Path(folder)
            report = triple_m.run_batch(options, 2, cache)
            self.assertEqual([row['state'] for row in report['cases']], ['passed', 'error'])
            self.assertEqual(report['compute']['errors'], 1)
            worker.assert_called_once()
            self.assertFalse((cache / 'latest.json').exists())


if __name__ == '__main__':
    unittest.main()
