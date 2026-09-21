"""Local command bridge into the authoritative fit_select_rank contract."""
from __future__ import annotations
import json
import subprocess
from dataclasses import dataclass, field
from typing import Mapping, Sequence
from core.attackers import BaselineAttacker, CharacterNgramAttacker, RankingResult

@dataclass
class AttackerConfig:
    name: str = "local-command"
    command: Sequence[str] | None = None
    timeout_seconds: int = 120
    max_guesses: int = 20_000
    seed: int = 42
    extra: Mapping[str, object] = field(default_factory=dict)

class NgramAttacker(CharacterNgramAttacker):
    """Compatibility name for the sole Python n-gram implementation."""

class CommandAttacker(BaselineAttacker):
    version = "command-jsonl-v2"
    def __init__(self, config):
        if not config.command or not 1 <= config.max_guesses <= 1_000_000 or not 1 <= config.timeout_seconds <= 3600:
            raise ValueError("command、max_guesses 或 timeout_seconds 无效")
        self.config = config
        self.attacker_id = config.name
        self.label = config.name

    def fit_select_rank(self, train, validation, candidates):
        payload = {"protocol": self.version, "train": list(train),
                   "candidates": list(candidates), "max_guesses": self.config.max_guesses,
                   "seed": self.config.seed, "metadata": dict(self.config.extra)}
        completed = subprocess.run(list(self.config.command),
            input=json.dumps(payload, ensure_ascii=False) + "\n", text=True,
            encoding="utf-8", capture_output=True, timeout=self.config.timeout_seconds,
            check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        allowed = set(candidates)
        guesses = []
        generated = 0
        for line in completed.stdout.splitlines():
            if not line.strip(): continue
            generated += 1
            if generated > self.config.max_guesses:
                raise ValueError("攻击器超过生成上限")
            item = json.loads(line)
            if not isinstance(item.get("guess"), str):
                raise ValueError("攻击器输出缺少字符串 guess 字段")
            if item["guess"] in allowed: guesses.append(item["guess"])
        guesses = tuple(dict.fromkeys(guesses))
        return RankingResult(self.attacker_id, self.label, self.version, guesses,
            parameters={"generated_count": generated, "matched_candidates": len(guesses),
                        "generation_limit": self.config.max_guesses, "evaluation_mode": "closed candidate ranking"},
            selection={"method": "command order", "test_used_for_parameters": False},
            training_size=len(train), validation_size=len(validation))

def build_attacker(config):
    return CommandAttacker(config) if config.command else NgramAttacker()
