"""Derive an authentication graph from the legacy login/signup state traces.

The graph is a read-time view. It does not change the authoritative JSONL
schema and therefore remains compatible with all existing v4 measurements.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, Mapping, Sequence

from application_security.models import (
    AuthEdge,
    AuthGraph,
    AuthNode,
    Evidence,
    EvidenceLevel,
    ModuleManifest,
    ScanMode,
)
from application_security.paper_registry import (
    LOGIN_POLICIES_USENIX_2023,
    QR_LOGIN_USENIX_2025,
)


AUTH_GRAPH_MANIFEST = ModuleManifest(
    module_id="b.auth_graph",
    name_zh="身份认证入口与路径图谱",
    research_question="网站公开提供哪些认证路径，这些路径如何到达口令、验证码、扫码或联合登录？",
    crypto_elements=(
        "password_authenticator",
        "one_time_password",
        "federated_authentication_token",
        "session_binding",
    ),
    paper_refs=(LOGIN_POLICIES_USENIX_2023, QR_LOGIN_USENIX_2025),
    safe_modes=(ScanMode.PASSIVE, ScanMode.SAFE_INTERACTION),
    limitations=(
        "图谱由公开页面和安全点击的状态序列推导，不证明服务端已正确验证认证凭据。",
        "需要账号、验证码或扫码确认的后续路径只能标记为受阻或未知。",
    ),
)


_METHOD_ZH = {
    "phone": "手机号标识",
    "email": "邮箱标识",
    "identifier": "账号标识",
    "username": "用户名标识",
    "password": "口令认证",
    "sms": "短信验证码",
    "email_code": "邮箱验证码",
    "qr": "二维码登录",
    "sso": "第三方联合登录",
    "wechat": "微信登录",
    "qq": "QQ登录",
    "weibo": "微博登录",
    "google": "Google登录",
    "apple": "Apple登录",
    "github": "GitHub登录",
    "gitee": "Gitee登录",
    "microsoft": "Microsoft登录",
    "baidu": "百度登录",
    "dingtalk": "钉钉登录",
    "douyin": "抖音登录",
    "xiaohongshu": "小红书登录",
    "alipay": "支付宝登录",
    "taobao": "淘宝登录",
    "xiaomi": "小米登录",
    "huawei": "华为登录",
    "solana": "Solana登录",
    "passkey": "通行密钥/WebAuthn",
    "auto_signup": "登录即注册",
}

_BLOCKER_ZH = {
    "sms_code": "短信验证门槛",
    "email_code": "邮箱验证门槛",
    "verification_code": "一次性验证码门槛",
    "scan": "扫码确认门槛",
    "captcha": "人机验证门槛",
    "slide": "滑块验证门槛",
    "app_confirm": "App确认门槛",
    "tos": "协议确认门槛",
}


def _stable_id(prefix: str, payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return "{}:{}".format(prefix, digest)


def _entry_states(entry: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    states = entry.get("states") or entry.get("raw_states") or entry.get("steps") or []
    return tuple(state for state in states if isinstance(state, Mapping))


def _state_methods(state: Mapping[str, Any]) -> Iterable[str]:
    methods = list(state.get("methods") or [])
    fields = set(state.get("fields") or [])
    blockers = set(state.get("blockers") or [])
    if "password" in fields:
        methods.append("password")
    if "code" in fields:
        if "phone" in fields or "sms_code" in blockers:
            methods.append("sms")
        elif "email" in fields or "email_code" in blockers:
            methods.append("email_code")
    if "scan" in blockers:
        methods.append("qr")
    seen = set()
    for method in methods:
        value = str(method).strip().lower()
        if value and value not in seen:
            seen.add(value)
            yield value


def _transition_relation(actions: Sequence[str]) -> tuple[str, str]:
    action_set = set(actions or [])
    for action in ("tab_click", "auth_mode_click", "signup_mode_reveal"):
        if action in action_set:
            return "switch_view", action
    for action in ("next", "submit", "click_link", "entry_click"):
        if action in action_set:
            return "advance", action
    return "observed_transition", next(iter(actions or []), "")


def build_auth_graph(
    target: str,
    entries: Mapping[str, Mapping[str, Any] | None],
) -> AuthGraph:
    """Build one graph from zero, one, or both legacy entry measurements.

    ``entries`` normally contains ``login`` and ``signup``. Keeping them as
    separate branches prevents a registration page from silently becoming a
    login conclusion (and vice versa).
    """

    nodes = [AuthNode(node_id="site:start", kind="site", label_zh=target)]
    edges = []
    evidence = []

    for entry_kind in ("login", "signup"):
        entry = entries.get(entry_kind)
        if not isinstance(entry, Mapping):
            continue
        entry_id = "{}:entry".format(entry_kind)
        entry_label = "登录入口" if entry_kind == "login" else "注册入口"
        nodes.append(AuthNode(
            node_id=entry_id,
            kind="entry",
            label_zh=entry_label,
            entry_kind=entry_kind,
            evidence_level=EvidenceLevel.INFERRED,
            attributes={
                "legacy_flow_type": entry.get("flow_type") or "unknown",
                "stop_reason": entry.get("stop_reason") or "",
            },
        ))
        edges.append(AuthEdge(
            source="site:start",
            target=entry_id,
            relation="explore_entry",
            evidence_level=EvidenceLevel.INFERRED,
        ))

        states = _entry_states(entry)
        previous_id = entry_id
        previous_actions: Sequence[str] = ()
        method_sources: Dict[str, list[str]] = {}
        blocker_sources: Dict[str, list[str]] = {}

        for sequence, state in enumerate(states, 1):
            step = int(state.get("step") or sequence)
            node_id = "{}:state:{}".format(entry_kind, sequence)
            observation = {
                "entry_kind": entry_kind,
                "sequence": sequence,
                "step": step,
                "url": state.get("url") or "",
                "ui_type": state.get("ui_type") or "unknown",
                "fields": list(state.get("fields") or []),
                "actions": list(state.get("actions") or []),
                "blockers": list(state.get("blockers") or []),
                "methods": list(state.get("methods") or []),
                "available_actions": list(state.get("available_actions") or []),
                "tabs": list(state.get("tabs") or []),
            }
            evidence_id = _stable_id("page-state", observation)
            evidence.append(Evidence(
                evidence_id=evidence_id,
                source_type="browser_page_state",
                level=EvidenceLevel.OBSERVED,
                observation=observation,
            ))
            fields = observation["fields"]
            label = "第{}步".format(step)
            if fields:
                label += "：" + "+".join(fields)
            nodes.append(AuthNode(
                node_id=node_id,
                kind="page_state",
                label_zh=label,
                entry_kind=entry_kind,
                step=step,
                url=observation["url"],
                evidence_level=EvidenceLevel.OBSERVED,
                attributes={
                    "ui_type": observation["ui_type"],
                    "fields": fields,
                    "evidence_id": evidence_id,
                },
            ))
            relation, action = _transition_relation(previous_actions)
            edges.append(AuthEdge(
                source=previous_id,
                target=node_id,
                relation=relation if previous_id != entry_id else "observe_state",
                evidence_level=EvidenceLevel.OBSERVED,
                action=action,
            ))
            previous_id = node_id
            previous_actions = observation["actions"]
            for method in _state_methods(state):
                method_sources.setdefault(method, []).append(node_id)
            for blocker in observation["blockers"]:
                blocker_sources.setdefault(str(blocker), []).append(node_id)

        for method, source_ids in sorted(method_sources.items()):
            method_id = "{}:method:{}".format(entry_kind, method)
            nodes.append(AuthNode(
                node_id=method_id,
                kind="authentication_method",
                label_zh=_METHOD_ZH.get(method, method),
                entry_kind=entry_kind,
                evidence_level=EvidenceLevel.OBSERVED,
                attributes={"observed_at": source_ids},
            ))
            for source_id in source_ids:
                edges.append(AuthEdge(
                    source=source_id,
                    target=method_id,
                    relation="offers_method",
                    evidence_level=EvidenceLevel.OBSERVED,
                ))

        for blocker, source_ids in sorted(blocker_sources.items()):
            blocker_id = "{}:gate:{}".format(entry_kind, blocker)
            nodes.append(AuthNode(
                node_id=blocker_id,
                kind="verification_gate",
                label_zh=_BLOCKER_ZH.get(blocker, blocker),
                entry_kind=entry_kind,
                evidence_level=EvidenceLevel.OBSERVED,
                attributes={"observed_at": source_ids},
            ))
            for source_id in source_ids:
                edges.append(AuthEdge(
                    source=source_id,
                    target=blocker_id,
                    relation="blocked_by",
                    evidence_level=EvidenceLevel.OBSERVED,
                ))

    return AuthGraph(
        target=target,
        nodes=tuple(nodes),
        edges=tuple(edges),
        evidence=tuple(evidence),
        paper_ref_ids=tuple(
            ref.reference_id for ref in AUTH_GRAPH_MANIFEST.paper_refs
        ),
        limitations=AUTH_GRAPH_MANIFEST.limitations,
    )
