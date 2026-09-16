"""Optional direct adapter for the local PassLLM 0.5B LoRA checkpoint.

The adapter is intentionally lazy: importing ZipfGuard never imports Torch or
Transformers. The UI can therefore run on a CPU-only machine and accurately
report why it selected the local n-gram fallback.
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
        "fallback": "local-ngram" if missing or not config.base_model.is_dir() or not config.lora_path.is_dir() else None,
    }


class PassLLMAttacker:
    """Lazy PassLLM wrapper implementing the same generate contract.

    The upstream search code is loaded only after runtime checks pass. This
    prevents the demo from crashing when Torch is not installed.
    """

    name = "passllm-0.5b-rockyou"

    def __init__(self, config: PassLLMConfig):
        self.config = config
        self._train = []
        self._model = None
        self._tokenizer = None
        self._vocab = None

    def fit(self, train_samples, metadata=None):
        self._train = list(train_samples)
        return self

    def _load(self):
        status = runtime_status(self.config)
        if not status["available"]:
            raise RuntimeError("PassLLM 不可用：" + ", ".join(status["missing_packages"]) + "; 请安装模型运行依赖，界面将继续使用 n-gram 回退")
        sys.path.insert(0, str(self.config.project_dir))
        from src.model.eval import Basic_Config_For_Evaluation, load_model
        self._model, self._tokenizer, self._vocab = load_model(Basic_Config_For_Evaluation(str(self.config.base_model), str(self.config.base_model), str(self.config.lora_path), ""))

    def generate(self, policy: Mapping[str, object], max_guesses: int, seed: int = 42):
        if self._model is None:
            self._load()
        # Full dynamic beam search is exposed by the upstream project. The
        # adapter deliberately leaves generation policy-specific; callers may
        # use CommandAttacker with the project's dsgen/widthgen config for a
        # large run. This method provides a safe capability check for the UI.
        raise NotImplementedError("PassLLM 动态搜索请通过上游 dsgen/widthgen 配置运行；当前界面使用可复现 n-gram 回退")

    def score(self, candidates: Sequence[str], policy: Mapping[str, object] | None = None):
        if self._model is None:
            self._load()
        return []
