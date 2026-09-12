"""Owner-provided target scope for responsible batch measurements.

The scope is deliberately small and auditable: a text file contains one host
per line, or a JSON object contains ``authorized_hosts`` plus optional
``expires_at``.  A SHA-256 fingerprint is attached to output records without
copying the manifest path or its contents into measurement data.
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import FrozenSet, Iterable, Mapping, Optional, Tuple

from scripts.build_target_corpus import normalize_domain


_BROAD_WILDCARD_SUFFIXES = frozenset({
    "co.uk", "org.uk", "ac.uk", "gov.uk", "com.cn", "net.cn",
    "org.cn", "co.jp", "ne.jp", "com.au", "net.au", "co.in", "co.kr",
})


@dataclass(frozen=True)
class AuthorizationScope:
    source_path: str
    digest: str
    allowed_hosts: FrozenSet[str]
    allowed_wildcards: Tuple[str, ...] = ()
    expires_at: Optional[str] = None

    @property
    def scope_id(self) -> str:
        """Short stable identifier suitable for JSONL records and logs."""
        return self.digest[:16]

    def matches(self, host_or_url: str) -> bool:
        host = normalize_domain(host_or_url)
        if not host:
            return False
        if host in self.allowed_hosts:
            return True
        return any(host.endswith("." + suffix)
                   for suffix in self.allowed_wildcards)


def _parse_expiry(value: object) -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("authorization_manifest_invalid_expiry") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed <= datetime.now(timezone.utc):
        raise ValueError("authorization_manifest_expired")
    return parsed.astimezone(timezone.utc).isoformat()


def _entries_from_payload(payload: object) -> Tuple[Iterable[object], Optional[str]]:
    if isinstance(payload, list):
        return payload, None
    if not isinstance(payload, Mapping):
        raise ValueError("authorization_manifest_must_be_json_object_or_list")
    entries = None
    for key in ("authorized_hosts", "authorized_domains", "hosts", "domains"):
        if key in payload:
            entries = payload[key]
            break
    if entries is None and isinstance(payload.get("entries"), list):
        entries = payload["entries"]
    if not isinstance(entries, (list, tuple, set)):
        raise ValueError("authorization_manifest_missing_hosts")
    return entries, _parse_expiry(
        payload.get("expires_at") or payload.get("expires"))


def _entry_value(entry: object) -> str:
    if isinstance(entry, Mapping):
        value = (entry.get("host") or entry.get("domain") or
                 entry.get("url") or "")
    else:
        value = entry
    return str(value or "").strip()


def _normalise_entries(entries: Iterable[object]) -> Tuple[FrozenSet[str], Tuple[str, ...]]:
    exact = set()
    wildcards = set()
    for entry in entries:
        raw = _entry_value(entry)
        if not raw or raw.startswith("#"):
            continue
        wildcard = raw.startswith("*.")
        candidate = raw[2:] if wildcard else raw
        host = normalize_domain(candidate)
        if not host:
            raise ValueError("authorization_manifest_invalid_host:{}".format(raw))
        if wildcard:
            # Avoid accidentally authorizing an entire widely used public
            # suffix such as ``*.com`` or ``*.co.uk``.  A normal owned apex
            # like ``*.owned.example`` remains valid.
            if host in _BROAD_WILDCARD_SUFFIXES:
                raise ValueError("authorization_manifest_wildcard_too_broad:{}".format(raw))
            wildcards.add(host)
        else:
            exact.add(host)
    if not exact and not wildcards:
        raise ValueError("authorization_manifest_empty")
    return frozenset(exact), tuple(sorted(wildcards))


def load_authorization_scope(path: str) -> AuthorizationScope:
    """Load and validate a text/JSON owner authorization manifest."""
    manifest_path = Path(path)
    raw_bytes = manifest_path.read_bytes()
    digest = hashlib.sha256(raw_bytes).hexdigest()
    text = raw_bytes.decode("utf-8-sig")
    expires_at = None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        entries = text.splitlines()
    else:
        entries, expires_at = _entries_from_payload(payload)
    exact, wildcards = _normalise_entries(entries)
    return AuthorizationScope(
        source_path=str(manifest_path), digest=digest,
        allowed_hosts=exact, allowed_wildcards=wildcards,
        expires_at=expires_at)
