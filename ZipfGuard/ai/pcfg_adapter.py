"""Bounded, offline adapter for the vendored PCFG Password Cracker.

Only caller-supplied training samples are written to a short-lived file. The
upstream source tree is treated as read-only: executable Python files are
copied to a versioned runtime backend before the upstream programs run. The
generated stream is bounded and intersected with ZipfGuard's public synthetic
candidate universe. No authentication or network interface exists here.
"""
from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Mapping, Sequence

from core.attackers import BaselineAttacker, RankingResult


UPSTREAM_URL = "https://github.com/lakiw/pcfg_cracker"
EXPECTED_COMMIT = "b04bbdadfe8928fd1287fa73ad1aa46a297ff83a"
MAX_GENERATION_LIMIT = 1_000_000
MAX_TIMEOUT_SECONDS = 3_600


class PCFGError(RuntimeError):
    """Base class for adapter failures."""


class PCFGUnavailableError(PCFGError):
    """The pinned local upstream or its runtime dependency is unavailable."""


class PCFGTrainingError(PCFGError):
    """The bounded local training process failed."""


class PCFGGenerationError(PCFGError):
    """The bounded local generation process failed."""


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclasses.dataclass(frozen=True)
class PCFGConfig:
    """Location and hard resource limits for the external PCFG process."""

    source_root: Path
    runtime_root: Path
    generation_limit: int = 20_000
    timeout_seconds: int = 180
    coverage: float = 1.0
    python_executable: str = sys.executable

    @classmethod
    def workspace_default(cls, workspace_root: str | Path | None = None, **kwargs):
        root = Path(workspace_root) if workspace_root is not None else _workspace_root()
        model_root = root / "PCFG攻击模型"
        return cls(
            source_root=model_root / "upstream" / "pcfg_cracker",
            runtime_root=model_root / "runtime",
            **kwargs,
        )

    def normalized(self) -> "PCFGConfig":
        generation_limit = int(self.generation_limit)
        timeout_seconds = int(self.timeout_seconds)
        coverage = float(self.coverage)
        if isinstance(self.generation_limit, bool) or generation_limit <= 0:
            raise ValueError("PCFG generation_limit 必须为正整数")
        if generation_limit > MAX_GENERATION_LIMIT:
            raise ValueError(f"PCFG generation_limit 不得超过 {MAX_GENERATION_LIMIT}")
        if isinstance(self.timeout_seconds, bool) or timeout_seconds <= 0:
            raise ValueError("PCFG timeout_seconds 必须为正整数")
        if timeout_seconds > MAX_TIMEOUT_SECONDS:
            raise ValueError(f"PCFG timeout_seconds 不得超过 {MAX_TIMEOUT_SECONDS}")
        if coverage != 1.0:
            raise ValueError("ZipfGuard 仅允许 coverage=1.0 的纯 PCFG 模式")
        source_root = Path(self.source_root).resolve()
        runtime_root = Path(self.runtime_root).resolve()
        if (
            source_root == runtime_root
            or source_root in runtime_root.parents
            or runtime_root in source_root.parents
        ):
            raise ValueError("PCFG runtime_root 必须与第三方 source_root 完全隔离")
        return dataclasses.replace(
            self,
            source_root=source_root,
            runtime_root=runtime_root,
            generation_limit=generation_limit,
            timeout_seconds=timeout_seconds,
            coverage=coverage,
            python_executable=str(self.python_executable),
        )


def _git_commit(source_root: Path) -> str | None:
    if not (source_root / ".git").exists():
        return None
    try:
        completed = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=10,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def _git_tracked_dirty(source_root: Path) -> bool | None:
    if not (source_root / ".git").exists():
        return None
    try:
        completed = subprocess.run(
            [
                "git", "-C", str(source_root), "status", "--porcelain",
                "--untracked-files=no",
            ],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=10,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return bool(completed.stdout.strip())


def _manifest_commit(source_root: Path) -> str | None:
    manifest = source_root.parents[1] / "UPSTREAM_VERSION.txt"
    try:
        for line in manifest.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == "commit":
                return value.strip() or None
    except OSError:
        return None
    return None


def _dependency_status(python_executable: str) -> tuple[bool, str | None]:
    """Check the dependency in the interpreter that will run upstream."""

    if Path(python_executable).resolve() == Path(sys.executable).resolve():
        return importlib.util.find_spec("chardet") is not None, None
    try:
        completed = subprocess.run(
            [python_executable, "-c", "import chardet"],
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=10,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, type(error).__name__
    return completed.returncode == 0, None


def runtime_status(config: PCFGConfig | None = None) -> dict[str, Any]:
    """Return an auditable availability report without training a model."""

    cfg = (config or PCFGConfig.workspace_default()).normalized()
    trainer = cfg.source_root / "trainer.py"
    guesser = cfg.source_root / "pcfg_guesser.py"
    git_commit = _git_commit(cfg.source_root)
    tracked_dirty = _git_tracked_dirty(cfg.source_root)
    manifest_commit = _manifest_commit(cfg.source_root)
    detected_commit = git_commit or manifest_commit
    dependency_available, dependency_error = _dependency_status(cfg.python_executable)
    missing = [
        name for name, path in (("trainer.py", trainer), ("pcfg_guesser.py", guesser))
        if not path.is_file()
    ]
    version_matches = detected_commit == EXPECTED_COMMIT
    if not version_matches:
        missing.append("pinned upstream commit")
    if tracked_dirty:
        missing.append("modified upstream tracked files")
    if dependency_error is not None:
        missing.append("python executable")
    return {
        "available": not missing,
        "attacker_id": "pcfg",
        "label": "PCFG 结构化攻击",
        "source_root": str(cfg.source_root),
        "runtime_root": str(cfg.runtime_root),
        "upstream_url": UPSTREAM_URL,
        "expected_commit": EXPECTED_COMMIT,
        "detected_commit": detected_commit,
        "git_commit": git_commit,
        "git_tracked_dirty": tracked_dirty,
        "manifest_commit": manifest_commit,
        "commit_matches_expected": version_matches,
        "missing": missing,
        "optional_missing": [] if dependency_available else ["python package: chardet"],
        "chardet_required": False,
        "dependency_error": dependency_error,
        "python_executable": cfg.python_executable,
        "generation_limit": cfg.generation_limit,
        "generation_limit_ceiling": MAX_GENERATION_LIMIT,
        "timeout_seconds": cfg.timeout_seconds,
        "coverage": cfg.coverage,
        "pure_pcfg": True,
        "source_tree_execution": False,
        "network_access": False,
        "fallback": None,
    }


def _unique_candidates(candidates: Sequence[str]) -> list[str]:
    values: list[str] = []
    for raw_value in candidates:
        value = str(raw_value)
        if not value or any(ord(character) < 32 for character in value):
            raise ValueError("PCFG 候选必须是非空单行字符串")
        values.append(value)
    return list(dict.fromkeys(values))


class PCFGAttacker(BaselineAttacker):
    """PCFG Password Cracker exposed through ZipfGuard's ranking contract."""

    attacker_id = "pcfg"
    label = "PCFG 结构化攻击"
    version = "pcfg-cracker-4.8-adapter-2026.2"

    def __init__(self, config: PCFGConfig | None = None):
        self.config = (config or PCFGConfig.workspace_default()).normalized()
        self._generation_cache: dict[tuple[str, str], tuple[tuple[str, ...], int]] = {}

    def status(self) -> dict[str, Any]:
        return runtime_status(self.config)

    def _ensure_available(self) -> Mapping[str, Any]:
        status = self.status()
        if not status["available"]:
            raise PCFGUnavailableError(
                "PCFG 攻击器不可用：" + ", ".join(status["missing"])
                + f"；期望目录 {self.config.source_root}"
            )
        return status

    def _backend_root(self) -> Path:
        return self.config.runtime_root / "backend" / EXPECTED_COMMIT[:12]

    def _prepare_backend(self) -> Path:
        """Create a runtime-only copy so upstream is never executed in place."""

        backend = self._backend_root()
        marker = backend / ".zipfguard_backend.json"
        if (backend / "trainer.py").is_file() and (backend / "pcfg_guesser.py").is_file() and marker.is_file():
            return backend

        staging_parent = self.config.runtime_root / "backend"
        staging_parent.mkdir(parents=True, exist_ok=True)
        if backend.exists():
            shutil.rmtree(backend)
        staging = Path(tempfile.mkdtemp(prefix="pcfg_backend_", dir=staging_parent))
        excluded = {".git", "Rules", "docs", "__pycache__"}
        try:
            for source in self.config.source_root.rglob("*"):
                relative = source.relative_to(self.config.source_root)
                if any(part in excluded for part in relative.parts):
                    continue
                target = staging / relative
                if source.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                elif source.suffix == ".py" or source.name == "requirements.txt":
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
            (staging / "Rules").mkdir(parents=True, exist_ok=True)
            marker_payload = {
                "source_root": str(self.config.source_root),
                "upstream_commit": EXPECTED_COMMIT,
                "purpose": "isolated ZipfGuard runtime backend; no training plaintext",
            }
            (staging / marker.name).write_text(
                json.dumps(marker_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            try:
                staging.replace(backend)
            except FileExistsError:
                shutil.rmtree(staging, ignore_errors=True)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return backend

    def _training_key(self, train: Sequence[str]) -> str:
        digest = hashlib.sha256()
        digest.update(b"pcfg-adapter=2026.2\ncoverage=1.0\n")
        for raw_value in train:
            value = str(raw_value)
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(4, "big"))
            digest.update(encoded)
        return digest.hexdigest()

    @staticmethod
    def _candidate_key(candidates: Sequence[str]) -> str:
        digest = hashlib.sha256()
        for value in candidates:
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(4, "big"))
            digest.update(encoded)
        return digest.hexdigest()

    @staticmethod
    def _ruleset_name(key: str) -> str:
        return "ZipfGuard_" + key[:16]

    @staticmethod
    def _ruleset_path(backend: Path, name: str) -> Path:
        return backend / "Rules" / name

    def _ruleset_ready(self, backend: Path, name: str) -> bool:
        base = self._ruleset_path(backend, name)
        return (base / "config.ini").is_file() and (base / "Grammar" / "grammar.txt").is_file()

    def _run(
        self, backend: Path, command: Sequence[str], *, error_type: type[PCFGError], operation: str,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            process = subprocess.Popen(
                [str(value) for value in command],
                cwd=backend,
                env=environment,
                # Keep this pipe open until process exit. Upstream starts a
                # daemon input thread; DEVNULL makes input() hit EOF and can
                # trigger a Python 3.14 shutdown race on Windows.
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as error:
            raise error_type(f"PCFG {operation}无法启动：{type(error).__name__}") from error

        output: dict[str, str] = {"stdout": "", "stderr": ""}

        def drain(name: str, stream) -> None:
            output[name] = stream.read()

        stdout_thread = threading.Thread(
            target=drain, args=("stdout", process.stdout), daemon=True,
        )
        stderr_thread = threading.Thread(
            target=drain, args=("stderr", process.stderr), daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        try:
            returncode = process.wait(timeout=self.config.timeout_seconds)
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.wait()
            raise error_type(
                f"PCFG {operation}超过 {self.config.timeout_seconds} 秒限制"
            ) from error
        finally:
            if process.stdin is not None:
                process.stdin.close()
            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
        return subprocess.CompletedProcess(
            [str(value) for value in command], returncode,
            output["stdout"], output["stderr"],
        )

    def _train(self, backend: Path, train: Sequence[str], ruleset_name: str, key: str) -> dict[str, Any]:
        metadata_dir = self.config.runtime_root / "metadata"
        metadata_path = metadata_dir / f"{ruleset_name}.json"
        if self._ruleset_ready(backend, ruleset_name) and metadata_path.is_file():
            return {"cache_hit": True, "ruleset": ruleset_name, "training_key": key}

        training_dir = self.config.runtime_root / "training"
        training_dir.mkdir(parents=True, exist_ok=True)
        metadata_dir.mkdir(parents=True, exist_ok=True)
        training_path: Path | None = None
        ruleset_path = self._ruleset_path(backend, ruleset_name)
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", suffix=".txt",
                prefix="pcfg_train_", dir=training_dir, delete=False,
            ) as handle:
                training_path = Path(handle.name)
                for raw_value in train:
                    value = str(raw_value)
                    if not value or any(ord(character) < 32 for character in value):
                        raise ValueError("PCFG 训练样本必须是非空单行字符串")
                    handle.write(value + "\n")

            command = [
                self.config.python_executable, str(backend / "trainer.py"),
                "--rule", ruleset_name, "--training", str(training_path),
                "--encoding", "utf-8", "--coverage", "1.0",
                "--comments", "ZipfGuard synthetic train split only",
            ]
            completed = self._run(
                backend, command, error_type=PCFGTrainingError, operation="训练",
            )
            if completed.returncode != 0 or not self._ruleset_ready(backend, ruleset_name):
                shutil.rmtree(ruleset_path, ignore_errors=True)
                detail = (completed.stderr or completed.stdout)[-2000:].strip()
                raise PCFGTrainingError(
                    f"PCFG 训练失败（exit={completed.returncode}）"
                    + (f"：{detail}" if detail else "")
                )
            metadata = {
                "attacker_id": self.attacker_id,
                "ruleset": ruleset_name,
                "training_key": key,
                "training_size": len(train),
                "input_role": "train",
                "coverage": 1.0,
                "test_data_used": False,
                "validation_data_used": False,
                "deterministic_upstream_order": True,
                "upstream_url": UPSTREAM_URL,
                "upstream_commit": EXPECTED_COMMIT,
                "source_tree_modified": False,
            }
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return {"cache_hit": False, **metadata}
        except PCFGTrainingError:
            shutil.rmtree(ruleset_path, ignore_errors=True)
            metadata_path.unlink(missing_ok=True)
            raise
        finally:
            if training_path is not None:
                training_path.unlink(missing_ok=True)

    def _generate(
        self, backend: Path, ruleset_name: str, allowed_candidates: Sequence[str],
    ) -> tuple[tuple[str, ...], int, bool]:
        candidate_key = self._candidate_key(allowed_candidates)
        cache_key = (ruleset_name, candidate_key)
        if cache_key in self._generation_cache:
            guesses, count = self._generation_cache[cache_key]
            return guesses, count, True

        allowed = set(allowed_candidates)
        session_name = f"zipfguard_{os.getpid()}_{ruleset_name[-8:]}"
        session_file = backend / f"{session_name}.sav"
        command = [
            self.config.python_executable, str(backend / "pcfg_guesser.py"),
            "--rule", ruleset_name, "--session", session_name,
            "--limit", str(self.config.generation_limit),
        ]
        try:
            completed = self._run(
                backend, command, error_type=PCFGGenerationError, operation="候选生成",
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout)[-2000:].strip()
                raise PCFGGenerationError(
                    f"PCFG 候选生成失败（exit={completed.returncode}）"
                    + (f"：{detail}" if detail else "")
                )
            if "Starting to generate password guesses" not in completed.stderr:
                raise PCFGGenerationError("PCFG 候选生成未进入有效运行阶段")
            # Upstream emits one empty banner line on stdout before guesses.
            # Empty passwords are forbidden by this adapter, so it is protocol
            # noise rather than a generated candidate and does not consume the
            # experimental budget.
            stream = [line for line in completed.stdout.splitlines() if line]
            if len(stream) > self.config.generation_limit:
                raise PCFGGenerationError("PCFG 上游输出超过适配器候选硬上限")
            guesses: list[str] = []
            seen: set[str] = set()
            for line in stream:
                if line in allowed and line not in seen:
                    guesses.append(line)
                    seen.add(line)
            result = (tuple(guesses), len(stream))
            self._generation_cache[cache_key] = result
            return result[0], result[1], False
        finally:
            session_file.unlink(missing_ok=True)

    def fit_select_rank(
        self, train: Sequence[str], validation: Sequence[str], candidates: Sequence[str],
    ) -> RankingResult:
        status = self._ensure_available()
        if not train:
            raise ValueError("PCFG 需要非空 train")
        public_candidates = _unique_candidates(candidates)
        if not public_candidates:
            raise ValueError("PCFG 需要非空候选空间")
        key = self._training_key(train)
        ruleset_name = self._ruleset_name(key)
        backend = self._prepare_backend()
        training = self._train(backend, train, ruleset_name, key)
        guesses, generated_count, generation_cache_hit = self._generate(
            backend, ruleset_name, public_candidates,
        )
        return RankingResult(
            self.attacker_id, self.label, self.version, guesses,
            parameters={
                "backend": "lakiw/pcfg_cracker",
                "upstream_url": UPSTREAM_URL,
                "upstream_commit": status["detected_commit"],
                "execution_root": "isolated runtime backend",
                "ruleset": ruleset_name,
                "training_key": key,
                "coverage": 1.0,
                "markov_component_present": False,
                "markov_component_generated": False,
                "generation_limit": self.config.generation_limit,
                "generated_count": generated_count,
                "matched_candidates": len(guesses),
                "training_cache_hit": bool(training["cache_hit"]),
                "generation_cache_hit": generation_cache_hit,
                "deterministic_order": True,
            },
            selection={
                "method": "upstream PCFG probability order; no validation tuning",
                "split": None,
                "validation_used_for_parameters": False,
                "test_used_for_parameters": False,
            },
            training_size=len(train), validation_size=len(validation),
        )
