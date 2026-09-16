"""A safe, offline interface for classical and PassLLM/PassGPT attackers.

The command adapter never contacts authentication endpoints.  It exchanges
JSONL with a local process so either PassLLM or PassGPT can be plugged in
without changing the policy-evaluation pipeline.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence


@dataclass
class AttackerConfig:
    name: str = "local-ngram"
    command: Sequence[str] | None = None
    timeout_seconds: int = 120
    extra: Mapping[str, object] = field(default_factory=dict)


class NgramAttacker:
    """Adapter around the existing deterministic synthetic ranker."""

    name = "local-ngram"

    def __init__(self, ranker):
        self.ranker = ranker
        self._train = []

    def fit(self, train_samples: Iterable[object], metadata=None):
        self._train = list(train_samples)
        return self

    def generate(self, policy: Mapping[str, object], max_guesses: int, seed: int = 42):
        candidates = policy.get("candidates", [])
        if not candidates:
            raise ValueError("NgramAttacker 需要 policy['candidates']")
        rows = self.ranker(self._train, candidates, attack="hybrid")
        return rows[: max(0, int(max_guesses))]


class CommandAttacker:
    """Run a local PassLLM/PassGPT JSONL command and parse its guesses."""

    def __init__(self, config: AttackerConfig):
        if not config.command:
            raise ValueError("command adapter 需要本地命令")
        self.config = config
        self.name = config.name
        self._train = []

    def fit(self, train_samples: Iterable[object], metadata=None):
        self._train = list(train_samples)
        return self

    def generate(self, policy: Mapping[str, object], max_guesses: int, seed: int = 42):
        payload = {
            "policy": dict(policy),
            "max_guesses": int(max_guesses),
            "seed": int(seed),
            "train_size": len(self._train),
            "metadata": dict(self.config.extra),
        }
        completed = subprocess.run(
            list(self.config.command),
            input=json.dumps(payload, ensure_ascii=False) + "\n",
            text=True,
            capture_output=True,
            timeout=self.config.timeout_seconds,
            check=True,
        )
        rows = []
        for line in completed.stdout.splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if "guess" not in item:
                raise ValueError("攻击器输出缺少 guess 字段")
            rows.append(item)
        return rows[: max(0, int(max_guesses))]


def build_attacker(config: AttackerConfig, ranker=None):
    """Build a configured adapter; command failures remain visible to caller."""
    if config.command:
        return CommandAttacker(config)
    if ranker is None:
        raise ValueError("无 command 时必须提供本地 ranker")
    return NgramAttacker(ranker)
