"""Content identities and environment evidence; no plaintext data in manifests."""
import hashlib
import importlib.metadata
import platform
import subprocess
import sys
from pathlib import Path

from experiments.config import fingerprint

ROOT = Path(__file__).resolve().parents[1]


def git_output(*args):
    try:
        return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def manifest(config, dataset, attackers):
    sources = {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
               for directory in ("core", "ai", "policy", "experiments", "web")
               for p in sorted((ROOT / directory).glob("*.py"))}
    sources["run_demo.py"] = hashlib.sha256((ROOT / "run_demo.py").read_bytes()).hexdigest()
    return {
        "config": config, "config_sha256": fingerprint(config),
        "dataset_version": "synthetic-grammar-v1" if "records" in dataset else "aggregate-counts-v1",
        "dataset_sha256": fingerprint(dataset),
        "candidate_space_version": "public-grammar-v1", "candidate_space_sha256": fingerprint(config["synthetic"]),
        "attacker_versions": {a.attacker_id: a.version for a in attackers},
        "git_commit": git_output("rev-parse", "HEAD"), "git_dirty": bool(git_output("status", "--porcelain")),
        "source_sha256": fingerprint(sources), "source_files": sources,
        "python": sys.version, "python_executable": sys.executable, "platform": platform.platform(),
        "dependencies": dict(sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions() if d.metadata["Name"])),
    }
