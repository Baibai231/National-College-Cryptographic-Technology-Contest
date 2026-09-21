"""Optional direct adapter for the local PassLLM 0.5B LoRA checkpoint.

The adapter is intentionally lazy: importing ZipfGuard never imports Torch or
Transformers. The UI can therefore run on a CPU-only machine and accurately
report environment availability separately from experiment participation.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class PassLLMConfig:
    project_dir: Path
    base_model: Path
    lora_path: Path
    prompt_id: int = 1

    @classmethod
    def workspace_default(cls, workspace: str | Path) -> "PassLLMConfig":
        root = Path(workspace)
        project = root / "PassLLM原版" / "Available artifacts for USENIX Security 2025 #772-v1"
        return cls(project, root / "PolyPass" / "model" / "Qwen0.5B-Instruct", project / "checkpoints" / "rockyou_100w_disQwen0.5B")


def runtime_status(config: PassLLMConfig) -> dict[str, Any]:
    missing = [name for name in ("torch", "transformers", "peft") if importlib.util.find_spec(name) is None]
    return {
        "model": "PassLLM 0.5B + Rockyou LoRA",
        "available": not missing and config.base_model.is_dir() and config.lora_path.is_dir(),
        "base_model": str(config.base_model),
        "lora_path": str(config.lora_path),
        "base_model_present": config.base_model.is_dir(),
        "lora_present": config.lora_path.is_dir(),
        "missing_packages": missing,
        "fallback": None,
        "integrated": False,
        "participated": False,
        "evaluation_status": "环境可检测；尚未接入主评估；当前实验未使用 PassLLM",
    }


class PassLLMAttacker:
    """Capability placeholder, deliberately unavailable to evaluation."""
    attacker_id = "passllm"
    label = "PassLLM（尚未接入）"
    version = "capability-only-v1"

    def __init__(self, config):
        self.config = config

    def fit_select_rank(self, train, validation, candidates):
        raise RuntimeError("PassLLM 尚未接入主评估；当前实验未使用 PassLLM")
