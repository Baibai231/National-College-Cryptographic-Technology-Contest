import dataclasses
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai.attacker_adapter import AttackerConfig, CommandAttacker
from ai.pcfg_adapter import PCFGAttacker
from core.attackers import FrequencyAttacker
from core.data import load_count_json, synthetic_counts
from core.rockyou import aggregate_rockyou
from core.synthetic import candidate_space, generate_synthetic_dataset
from experiments.config import experiment_context, fingerprint, load_config, validate_config
from experiments.pipeline import run_pipeline, write_json
from policy.engine import PasswordPolicy
from policy.response import response_candidate_space, simulate_policy_response
from web.presentation import report_html
from web.server import execute_request


def small_config():
    cfg = load_config()
    cfg['synthetic']['size'] = 100
    cfg['bootstrap_repetitions'] = 20
    cfg['attackers'] = {'frequency':'required'}
    cfg['comparison_policies'] = [PasswordPolicy().to_dict(), PasswordPolicy('length-8', min_length=8).to_dict()]
    cfg['search_actions'] = [['length-8','min_length',8]]
    cfg['max_action_count'] = 1
    cfg['search']['min_security_gain'] = 0
    return cfg


class DeliveryTests(unittest.TestCase):
    def test_optional_timeout_excluded_everywhere_required_failure_visible(self):
        cfg = small_config()
        cfg['attackers']['pcfg'] = 'optional'
        with patch.object(PCFGAttacker, 'fit_select_rank', side_effect=TimeoutError('test timeout')):
            result = run_pipeline(config=cfg)
        self.assertFalse(result['metadata']['comparison_complete'])
        self.assertFalse(result['metadata']['pcfg']['enabled'])
        self.assertIn('test timeout', result['metadata']['attacker_failures'][0]['reason'])
        self.assertEqual(result['metadata']['participating_attackers'], ['frequency'])
        self.assertEqual(result['policy_search']['protocol']['selection_attackers'], ['frequency'])
        self.assertTrue(all(a['attacker_id'] == 'frequency' for r in result['policies'] for a in r['attacks']))
        cfg['attackers']['pcfg'] = 'required'
        with patch.object(PCFGAttacker, 'fit_select_rank', side_effect=PermissionError('test permissions')):
            with self.assertRaisesRegex(RuntimeError, '必选攻击器 pcfg'):
                run_pipeline(config=cfg)

    def test_late_optional_failure_restarts_validation_without_model(self):
        cfg = small_config()
        cfg['attackers']['pcfg'] = 'optional'
        calls = []
        def fail_late(self, train, validation, candidates):
            calls.append(1)
            if len(calls) == 4: raise OSError('late validation failure')
            return dataclasses.replace(FrequencyAttacker().fit_select_rank(train, validation, candidates), attacker_id='pcfg')
        with patch.object(PCFGAttacker, 'fit_select_rank', fail_late):
            result = run_pipeline(config=cfg)
        self.assertEqual(len(calls),4)
        self.assertEqual(result['metadata']['participating_attackers'],['frequency'])
        self.assertEqual(result['policy_search']['protocol']['selection_attackers'], ['frequency'])

    def test_upload_file_object_invalid_json_and_aggregate_visibility(self):
        payload = synthetic_counts(size=100, categories=10)
        uploaded = io.BytesIO(json.dumps(payload).encode())
        self.assertEqual(load_count_json(uploaded),payload)
        for raw in (b'broken',b'[]',b'{}'):
            with self.assertRaises(ValueError): load_count_json(io.BytesIO(raw))
        result = execute_request({'config':small_config(),'source':'upload','payload':payload})
        page = report_html(result)
        self.assertIn('均未运行',page)
        self.assertNotIn('M2 · 统一攻击基线',page)
        self.assertNotIn('M4 · 策略风险',page)

    def test_config_roundtrip_hash_and_artifact_checksum(self):
        cfg = small_config()
        with tempfile.TemporaryDirectory() as temp:
            config_path = Path(temp)/'config.json'
            config_path.write_text(json.dumps(cfg),encoding='utf-8')
            self.assertEqual(load_config(config_path),cfg)
            result = run_pipeline(config=cfg)
            self.assertEqual(result['reproducibility']['config_sha256'],fingerprint(cfg))
            for key in ('dataset_sha256','attacker_versions','git_commit','python','dependencies','source_sha256'):
                self.assertIn(key,result['reproducibility'])
            output = write_json(result,Path(temp)/'result.json')
            checksum = output.with_suffix('.json.sha256').read_text().split()[0]
            self.assertEqual(checksum,hashlib.sha256(output.read_bytes()).hexdigest())
            cfg['q'] = 0.25
            self.assertNotEqual(fingerprint(cfg),result['reproducibility']['config_sha256'])
        cfg['budgets'] = [0]
        with self.assertRaises(ValueError): validate_config(cfg)

    def test_custom_grammar_and_phrase_first_are_scoped_and_reachable(self):
        original = candidate_space()
        cfg = small_config()
        cfg['synthetic']['root_words'] = ['rose','ocean']
        cfg['synthetic']['suffixes'] = ['','3']
        cfg['synthetic']['phrase_words'] = ['coral','amber']
        cfg['response']['order'] = ['random-phrase','append-symbol','append-symbol-digit']
        with experiment_context(validate_config(cfg)):
            self.assertEqual(len(candidate_space()),8)
            dataset = generate_synthetic_dataset(size=100)
            policy = PasswordPolicy('length-8',min_length=8)
            response = simulate_policy_response(dataset,policy)
            self.assertEqual(response['summary']['overall']['response_kinds'],{'random-phrase':100})
            self.assertTrue({r['password'] for r in response['records']} <= set(response_candidate_space(policy)))
        self.assertEqual(candidate_space(),original)

    def test_no_feasible_recommendations_and_plot_sections(self):
        cfg = small_config()
        cfg['search']['min_security_gain'] = 1.0
        result = run_pipeline(config=cfg)
        self.assertEqual(result['recommendations'],[])
        page = report_html(result)
        for text in ('M2 · 统一攻击基线','95% CI','原始生成数','生成上限','残差','对数刻度','Pareto','无策略达到最低收益'):
            self.assertIn(text,page)
        result['dataset']['dataset_id'] = '<script>alert(1)</script>'
        self.assertNotIn('<script>',report_html(result))

    def test_rockyou_source_metadata_and_truncation(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'counts.txt'
            path.write_text('a\n'*20+'b\n'*10+'c\n'*10,encoding='utf-8')
            payload = aggregate_rockyou(path,top_k=2,source_semantics='frequency')
        m = payload['metadata']
        self.assertEqual(m['source_lines_read'],40)
        self.assertEqual(m['retained_categories'],2)
        self.assertAlmostEqual(m['truncated_mass'],0.25)
        self.assertFalse(m['input_deduplicated'])

    def test_command_bridge_receives_train_without_test_and_returns_common_result(self):
        command = [sys.executable,'-c',"import sys,json; p=json.loads(sys.stdin.readline()); assert p['train']==['rose']; assert 'test' not in p; print(json.dumps({'guess':'rose'}))"]
        attacker = CommandAttacker(AttackerConfig(command=command,max_guesses=2))
        result = attacker.fit_select_rank(['rose'],['ocean'],['rose','ocean'])
        self.assertEqual(result.guesses,('rose',))
        self.assertEqual(result.parameters['generated_count'],1)

    def test_streamlit_upload_and_bad_upload_paths(self):
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError:
            self.skipTest('Streamlit optional dependency absent')
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'web/app.py'),default_timeout=60).run()
        self.assertFalse(app.exception)
        app.selectbox[1].select('upload').run()
        app.number_input[0].set_value(17)
        good = io.BytesIO(json.dumps(synthetic_counts(size=100,categories=10)).encode())
        with patch('streamlit.file_uploader',return_value=good):
            app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['result']['metadata']['seed'],17)
        self.assertIsNone(app.session_state['result']['policy_search'])
        with patch('streamlit.file_uploader',return_value=io.BytesIO(b'bad')):
            app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.error)


if __name__ == '__main__': unittest.main()
