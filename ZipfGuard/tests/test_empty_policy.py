"""Empty accepted cohorts are undefined, never a perfect defense."""
import copy
import json
import unittest

from core.data import synthetic_counts
from core.metrics import cracked_at_k, risk_delta
from experiments.pipeline import _recommendations, render_markdown, run_pipeline
from policy.engine import PasswordPolicy, evaluate_policy


class EmptyPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_pipeline(synthetic_counts(size=1000, categories=40), bootstrap_repetitions=20)
        cls.empty = next(row for row in cls.result['policies'] if row['policy']['name'] == 'diversified-phrase')
        cls.baseline = next(row for row in cls.result['policies'] if row['policy']['name'] == 'baseline')

    def test_empty_policy_is_not_evaluable(self):
        row = self.empty
        self.assertEqual(row['evaluation_status'], 'not_evaluable')
        self.assertEqual(row['sample_counts'], {'total': 2000, 'accepted': 0, 'rejected': 2000, 'evaluated': 0})
        self.assertEqual(row['accept_rate'], 0)
        self.assertEqual(row['user_cost'], 1)
        self.assertIsNone(row['security_gain'])
        self.assertIn('没有可评估样本', row['evaluation_reason'])
        for point in row['attack']:
            self.assertIsNone(point['rate'])
            self.assertEqual(point['cracked'], 0)
            self.assertEqual(point['evaluated_count'], 0)
        for point in row['risk_delta']:
            self.assertIsNone(point['after'])
            self.assertIsNone(point['delta'])

    def test_extreme_custom_policy_is_also_not_evaluable(self):
        row = evaluate_policy(PasswordPolicy('reject-all', min_length=10000), seed=7)
        self.assertEqual(row['candidate_count'], 0)
        self.assertIsNone(row['security_gain'])
        self.assertEqual(_recommendations([row]), [])

    def test_baseline_and_partial_acceptance_stay_numeric(self):
        self.assertEqual(self.baseline['sample_counts']['evaluated'], 2000)
        self.assertEqual(self.baseline['security_gain'], 0)
        self.assertAlmostEqual(self.baseline['attack'][0]['rate'], 0.8005)
        partial = next(row for row in self.result['policies'] if row['policy']['name'] == 'length-8')
        self.assertEqual(partial['evaluation_status'], 'evaluated')
        self.assertEqual(partial['sample_counts']['accepted'], 1101)
        self.assertEqual(partial['sample_counts']['rejected'], 899)
        self.assertAlmostEqual(partial['accept_rate'], 0.5505)
        self.assertAlmostEqual(partial['attack'][0]['rate'], 992 / 1101)
        self.assertIsNotNone(partial['security_gain'])

    def test_empty_policy_cannot_win_any_recommendation(self):
        for item in self.result['recommendations']:
            self.assertNotEqual(item['policy']['name'], 'diversified-phrase')
        self.assertFalse(any(item['tier'] == '高防护' for item in self.result['recommendations']))
        self.assertEqual(_recommendations([self.empty]), [])
        self.assertEqual(_recommendations([]), [])

    def test_stale_gain_cannot_override_empty_evidence(self):
        stale = copy.deepcopy(self.empty)
        stale['security_gain'] = 1.0
        self.assertEqual(_recommendations([stale]), [])
        stale['evaluation_status'] = 'evaluated'
        self.assertEqual(_recommendations([stale]), [])

    def test_positive_evaluable_candidate_can_be_recommended(self):
        improved = copy.deepcopy(self.baseline)
        improved['policy']['name'] = 'positive-test-fixture'
        improved['security_gain'] = 0.1
        high = [item for item in _recommendations([self.empty, improved]) if item['tier'] == '高防护']
        self.assertEqual(len(high), 1)
        self.assertEqual(high[0]['policy']['name'], 'positive-test-fixture')

    def test_empty_metric_is_distinct_from_zero_hits(self):
        self.assertIsNone(cracked_at_k(['a'], [], [1])[0]['rate'])
        nonempty = cracked_at_k(['a'], ['b'], [1])[0]
        self.assertEqual(nonempty['rate'], 0)
        self.assertEqual(nonempty['evaluated_count'], 1)

    def test_missing_or_unknown_budget_is_not_zero_risk(self):
        before = [{'budget': 1, 'rate': 0.5}]
        for after in ([], [{'budget': 1, 'rate': None}]):
            self.assertIsNone(risk_delta(before, after)[0]['delta'])
        self.assertEqual(risk_delta(before, [{'budget': 1, 'rate': 0}])[0]['delta'], 0.5)
        self.assertIsNone(risk_delta([{'budget': 1, 'rate': None}], before)[0]['delta'])

    def test_reports_preserve_unknown_and_explain_counts(self):
        encoded = json.dumps(self.result, ensure_ascii=False, allow_nan=False)
        decoded = json.loads(encoded)
        row = next(row for row in decoded['policies'] if row['policy']['name'] == 'diversified-phrase')
        self.assertIsNone(row['security_gain'])
        markdown = render_markdown(decoded)
        self.assertIn('| diversified-phrase | 无法评估 | 无法评估 |', markdown)
        self.assertIn('2000/0/2000/0', markdown)
        self.assertNotIn('| diversified-phrase | 1.0000', markdown)


if __name__ == '__main__':
    unittest.main()
