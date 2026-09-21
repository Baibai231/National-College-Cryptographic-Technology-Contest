import dataclasses
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ai.pcfg_adapter import (
    MAX_GENERATION_LIMIT,
    PCFGAttacker,
    PCFGConfig,
    PCFGTrainingError,
    runtime_status,
)
from core.attackers import FrequencyAttacker
from core.synthetic import candidate_space, generate_synthetic_dataset, passwords_for_split
from experiments.policy_attack import run_policy_attack_experiment
from experiments.policy_search import PolicySearchConfig, enumerate_candidate_policies, run_policy_search
from policy.engine import PasswordPolicy


class PCFGAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="zipfguard_pcfg_tests_")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.config = PCFGConfig.workspace_default(
            generation_limit=2_000,
            timeout_seconds=180,
        )
        cls.config = dataclasses.replace(cls.config, runtime_root=Path(cls.temporary.name) / "runtime")
        cls.status = runtime_status(cls.config)

    def require_upstream(self):
        if not self.status["available"]:
            self.skipTest("外部 PCFG 源码未安装")

    def test_status_records_pinned_upstream_and_pure_pcfg_mode(self):
        self.require_upstream()
        self.assertTrue(self.status["commit_matches_expected"])
        self.assertTrue(self.status["pure_pcfg"])
        self.assertFalse(self.status["source_tree_execution"])
        self.assertFalse(self.status["network_access"])
        self.assertIsNone(self.status["fallback"])

    def test_fit_rank_is_deterministic_bounded_and_candidate_only(self):
        self.require_upstream()
        dataset = generate_synthetic_dataset(size=1_000, seed=23)
        train = passwords_for_split(dataset, "train")
        validation = passwords_for_split(dataset, "validation")
        candidates = candidate_space()
        attacker = PCFGAttacker(self.config)
        first = attacker.fit_select_rank(train, validation, candidates)
        second = attacker.fit_select_rank(train, list(reversed(validation)), candidates)
        self.assertEqual(first.guesses, second.guesses)
        self.assertGreater(len(first.guesses), 100)
        self.assertLessEqual(first.parameters["generated_count"], self.config.generation_limit)
        self.assertTrue(set(first.guesses).issubset(set(candidates)))
        self.assertEqual(len(first.guesses), len(set(first.guesses)))
        self.assertEqual(first.selection["validation_used_for_parameters"], False)
        self.assertEqual(first.selection["test_used_for_parameters"], False)
        self.assertEqual(first.parameters["markov_component_generated"], False)
        self.assertEqual(first.parameters["execution_root"], "isolated runtime backend")
        self.assertTrue(second.parameters["generation_cache_hit"])

        metadata_path = (
            self.config.runtime_root / "metadata" /
            f"{first.parameters['ruleset']}.json"
        )
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["training_size"], 600)
        self.assertEqual(metadata["test_data_used"], False)
        self.assertEqual(metadata["validation_data_used"], False)
        self.assertEqual(metadata["source_tree_modified"], False)

    def test_temporary_plaintext_training_file_is_removed(self):
        self.require_upstream()
        training_dir = self.config.runtime_root / "training"
        leftovers = list(training_dir.glob("pcfg_train_*.txt")) if training_dir.exists() else []
        self.assertEqual(leftovers, [])

    def test_config_rejects_unbounded_or_invalid_values(self):
        with self.assertRaises(ValueError):
            PCFGConfig.workspace_default(generation_limit=0).normalized()
        with self.assertRaises(ValueError):
            PCFGConfig.workspace_default(timeout_seconds=0).normalized()
        with self.assertRaises(ValueError):
            PCFGConfig.workspace_default(coverage=0.9).normalized()
        with self.assertRaises(ValueError):
            PCFGConfig.workspace_default(generation_limit=MAX_GENERATION_LIMIT + 1).normalized()
        with self.assertRaisesRegex(ValueError, "完全隔离"):
            PCFGConfig(
                source_root=Path("third_party"),
                runtime_root=Path("third_party") / "runtime",
            ).normalized()

    def test_status_reports_missing_upstream_without_running_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            status = runtime_status(PCFGConfig(
                source_root=root / "missing",
                runtime_root=root / "runtime",
                generation_limit=10,
            ))
        self.assertFalse(status["available"])
        self.assertIn("trainer.py", status["missing"])
        self.assertIn("pcfg_guesser.py", status["missing"])
        self.assertIn("pinned upstream commit", status["missing"])

    def test_failed_training_removes_plaintext_and_partial_ruleset(self):
        self.require_upstream()
        with tempfile.TemporaryDirectory() as temporary:
            config = PCFGConfig(
                source_root=self.config.source_root,
                runtime_root=Path(temporary) / "runtime",
                generation_limit=10,
            )
            attacker = PCFGAttacker(config)
            with mock.patch.object(
                attacker, "_run", side_effect=PCFGTrainingError("synthetic failure"),
            ):
                with self.assertRaises(PCFGTrainingError):
                    attacker.fit_select_rank(["cedar123"], [], ["cedar123"])
            self.assertEqual(list((config.runtime_root / "training").glob("*.txt")), [])
            rules = config.runtime_root / "backend" / self.status["expected_commit"][:12] / "Rules"
            self.assertEqual(list(rules.glob("ZipfGuard_*")), [])

    def test_upstream_source_tree_remains_unchanged(self):
        self.require_upstream()
        before = subprocess.run(
            ["git", "-C", str(self.config.source_root), "status", "--porcelain"],
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
        dataset = generate_synthetic_dataset(size=300, seed=31)
        PCFGAttacker(dataclasses.replace(self.config, generation_limit=200)).fit_select_rank(
            passwords_for_split(dataset, "train"),
            passwords_for_split(dataset, "validation"),
            candidate_space(),
        )
        after = subprocess.run(
            ["git", "-C", str(self.config.source_root), "status", "--porcelain"],
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
        self.assertEqual(after, before)
        self.assertEqual(list((self.config.source_root / "Rules").glob("ZipfGuard_*")), [])
        self.assertEqual(list(self.config.source_root.glob("zipfguard_*.sav")), [])

    def test_unified_frozen_adaptive_and_policy_search_integration(self):
        self.require_upstream()
        config = dataclasses.replace(self.config, generation_limit=500)
        attacker = PCFGAttacker(config)
        dataset = generate_synthetic_dataset(size=400, seed=37)
        policies = (
            PasswordPolicy(),
            PasswordPolicy(name="pcfg-integration", min_length=10),
        )
        experiment = run_policy_attack_experiment(
            dataset, policies, budgets=(100, 1_000), seed=37,
            attackers=(FrequencyAttacker(), attacker),
        )
        pcfg_row = next(
            row for row in experiment["policies"][1]["attacks"]
            if row["attacker_id"] == "pcfg"
        )
        self.assertEqual(pcfg_row["frozen"]["evaluation"]["total"], 80)
        self.assertEqual(pcfg_row["adaptive"]["evaluation"]["total"], 80)
        self.assertEqual(
            [point["budget"] for point in pcfg_row["adaptive"]["evaluation"]["points"]],
            [100, 1_000],
        )

        candidate_names = {"baseline", "search-l8", "search-l10", "search-l12"}
        candidates = tuple(
            policy for policy in enumerate_candidate_policies()
            if policy.name in candidate_names
        )
        search = run_policy_search(
            dataset, seed=37, budgets=(100, 1_000),
            config=PolicySearchConfig(min_security_gain=0.0),
            candidate_policies=candidates,
            search_attackers=(FrequencyAttacker(), attacker),
            final_attackers=(FrequencyAttacker(), attacker),
        )
        self.assertIn("pcfg", search["protocol"]["selection_attackers"])
        self.assertTrue(any(
            attack["attacker_id"] == "pcfg"
            for row in search["validation_candidates"] for attack in row["attacks"]
        ))


if __name__ == "__main__":
    unittest.main()
