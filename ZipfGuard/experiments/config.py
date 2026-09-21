"""Serializable experiment contract shared by CLI and both dashboards."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"
_ACTIVE = ContextVar("experiment_config", default=None)


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_config(path=None, *, preset="quick"):
    source = Path(path) if path else CONFIG_DIR / f"{preset}.json"
    return validate_config(json.loads(source.read_text(encoding="utf-8")))


def validate_config(value):
    cfg = copy.deepcopy(value)
    required = {"schema_version", "seed", "q", "budgets", "bootstrap_repetitions", "synthetic", "attackers", "pcfg", "response", "search", "comparison_policies", "search_actions", "max_action_count", "ngram"}
    if set(cfg) != required:
        raise ValueError(f"配置字段不匹配：缺少 {required - set(cfg)}；未知 {set(cfg) - required}")
    if cfg["schema_version"] != "zipfguard-experiment-v1":
        raise ValueError("不支持的配置版本")
    def integer(v, lo, hi, name):
        if type(v) is not int or not lo <= v <= hi:
            raise ValueError(f"{name} 必须是 [{lo}, {hi}] 内整数")
    integer(cfg["seed"], 0, 2**32 - 1, "seed")
    integer(cfg["bootstrap_repetitions"], 20, 1000, "bootstrap")
    integer(cfg["synthetic"]["size"], 100, 1_000_000, "size")
    if not 0 < cfg["q"] < 1 or not 0 < cfg["synthetic"]["exponent"] <= 5:
        raise ValueError("q 或 Zipf 指数超出范围")
    if not cfg["budgets"]:
        raise ValueError("至少选择一个攻击预算")
    for v in cfg["budgets"]:
        integer(v, 1, 1_000_000, "budget")
    cfg["budgets"] = sorted(set(cfg["budgets"]))
    allowed = {"frequency", "synthetic-dictionary", "character-ngram", "pcfg"}
    if not cfg["attackers"] or not set(cfg["attackers"]) <= allowed:
        raise ValueError("请选择已接入的攻击器")
    if not any(mode == "required" for mode in cfg["attackers"].values()):
        raise ValueError("至少需要一个必选攻击器")
    if any(mode not in ("required", "optional") for mode in cfg["attackers"].values()):
        raise ValueError("攻击器模式只能为 required 或 optional")
    integer(cfg["pcfg"]["generation_limit"], 1, 1_000_000, "PCFG limit")
    integer(cfg["pcfg"]["timeout_seconds"], 1, 3600, "PCFG timeout")
    integer(cfg["response"]["max_attempts"], 3, 100, "max_attempts")
    stages = cfg["response"]["order"]
    if len(stages) != 3 or set(stages) != {"append-symbol", "append-symbol-digit", "random-phrase"}:
        raise ValueError("response.order 必须包含三个不同响应阶段")
    for field in ("root_words", "phrase_words", "suffixes"):
        words = cfg["synthetic"][field]
        if not words or any(not isinstance(w, str) or any(ord(c) < 32 for c in w) or (not w and field != "suffixes") for w in words):
            raise ValueError(f"无效候选词表：{field}")
    integer(cfg["synthetic"].get("size"), 100, 1_000_000, "size")
    if len(cfg["synthetic"]["phrase_words"]) > 50 or len(cfg["synthetic"]["root_words"]) * len(cfg["synthetic"]["suffixes"]) > 100_000:
        raise ValueError("网页候选词表过大：短语词最多 50 个，词根与后缀乘积最多 100000")
    for field in ("orders", "search_orders"):
        if not cfg["ngram"][field]: raise ValueError("n-gram 阶数不能为空")
        for order in cfg["ngram"][field]: integer(order, 1, 5, "n-gram order")
    for field in ("smoothing_values", "search_smoothing_values"):
        if not cfg["ngram"][field] or any(not math.isfinite(v) or v <= 0 for v in cfg["ngram"][field]):
            raise ValueError("n-gram 平滑参数必须有限且为正")
    from experiments.policy_search import PolicySearchConfig
    search = PolicySearchConfig(**cfg["search"])
    for key, value in cfg["search"].items():
        if key != "version" and (not math.isfinite(value) or value < 0):
            raise ValueError(f"无效策略成本参数：{key}")
    if abs(search.response_cost_weight + search.rule_cost_weight - 1) > 1e-8:
        raise ValueError("响应与规则成本权重之和必须为 1")
    if abs(search.modification_weight + search.attempt_weight + search.length_weight - 1) > 1e-8:
        raise ValueError("响应内部成本权重之和必须为 1")
    integer(search.risk_budget, 1, 1_000_000, "risk_budget")
    for name in ("min_completion_rate", "max_modification_rate", "max_total_cost", "min_security_gain", "response_cost_weight", "rule_cost_weight"):
        if not 0 <= getattr(search, name) <= 1:
            raise ValueError(f"{name} 须位于 [0,1]")
    integer(cfg["max_action_count"], 1, 3, "max_action_count")
    for action in cfg["search_actions"]:
        if len(action) != 3 or action[1] not in ("min_length", "required_classes", "deny_feature"):
            raise ValueError("无效搜索动作")
        if action[1] == "min_length": integer(action[2], 0, 100, "搜索长度")
        if action[1] == "required_classes": integer(action[2], 0, 4, "字符类别数")
    if not 1 <= len(cfg["search_actions"]) <= 12:
        raise ValueError("搜索动作数量须为 1 到 12")
    from policy.engine import PasswordPolicy
    policies = [PasswordPolicy(**p) for p in cfg["comparison_policies"]]
    if not policies or policies[0].to_dict() != PasswordPolicy().to_dict() or len({p.name for p in policies}) != len(policies):
        raise ValueError("待比较策略必须从无约束 baseline 开始，且名称不重复")
    for policy in policies:
        integer(policy.min_length, 0, 100, "策略长度")
        integer(policy.required_classes, 0, 4, "策略字符类别数")
    canonical_json(cfg)
    return cfg


def active_section(name):
    cfg = _ACTIVE.get()
    return cfg[name] if cfg else None


@contextmanager
def experiment_context(config):
    token = _ACTIVE.set(config)
    try:
        yield
    finally:
        _ACTIVE.reset(token)
