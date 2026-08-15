"""Shared, durable storage helpers for web-created measurement records.

``reports/sites/sites_latest.jsonl`` is the source of truth.  SQLite is a
rebuildable serving index, so web writes must reach the JSONL file first.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


@contextmanager
def coordinated_data_lock(path: Path | str):
    """Take an exact-path advisory lock shared by the web app and sync job."""
    import fcntl

    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _exclusive_lock(path: Path):
    """Serialize writers to one authoritative JSON/JSONL file."""
    with coordinated_data_lock(path.with_suffix(path.suffix + ".lock")):
        yield


def measurement_record(hostname: str, site_url: str, version: str,
                       entry_kind: str, entry: dict,
                       measured_at: str | None = None) -> dict:
    """Normalize a web classifier response into the canonical JSONL schema."""
    now = measured_at or datetime.now(timezone.utc).isoformat()
    states = entry.get("raw_states") or entry.get("states") or entry.get("steps") or []
    url = site_url or entry.get("url") or "https://" + hostname
    return {
        "site": url,
        "hostname": hostname,
        "entry_kind": entry_kind,
        "measured_at": entry.get("measured_at") or now,
        "version": version or "v3",
        "flow_type": entry.get("flow_type") or "unknown",
        "confidence": entry.get("confidence"),
        "stop_reason": entry.get("stop_reason"),
        "primary_method": entry.get("primary_method"),
        "ui_type": entry.get("ui_type") or "unknown",
        "final_url": entry.get("final_url") or url,
        "states": states,
        "methods": entry.get("methods") or [],
        "policy": entry.get("policy") or {},
        "evidence": entry.get("evidence") or [],
        "error": entry.get("error"),
        "start_url": entry.get("start_url") or url,
    }


def upsert_records(path: Path | str, records: Iterable[dict]) -> dict:
    """Atomically upsert records by ``(hostname, entry_kind)``.

    Unmentioned entry kinds are retained, which prevents a login-only web test
    from erasing an existing signup result (and vice versa).
    """
    target = Path(path)
    incoming = list(records)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(target):
        current: dict[tuple[str, str], dict] = {}
        order: list[tuple[str, str]] = []
        if target.is_file():
            with target.open(encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    key = (record.get("hostname"), record.get("entry_kind"))
                    if not all(key):
                        raise ValueError(f"{target}:{number} 缺少 hostname/entry_kind")
                    if key not in current:
                        order.append(key)
                    current[key] = record

        if not incoming:
            return {"added": 0, "updated": 0, "total": len(current)}

        added = updated = 0
        for record in incoming:
            key = (record.get("hostname"), record.get("entry_kind"))
            if not all(key) or key[1] not in ("login", "signup"):
                raise ValueError("记录必须包含 hostname 及 login/signup entry_kind")
            if key in current:
                updated += 1
            else:
                added += 1
                order.append(key)
            current[key] = record

        fd, tmp_name = tempfile.mkstemp(
            prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for key in order:
                    handle.write(json.dumps(current[key], ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except Exception:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise
    return {"added": added, "updated": updated, "total": len(current)}


def upsert_manual_review(path: Path | str, hostname: str, *, login: str = "",
                         signup: str = "", note: str = "",
                         structured: dict | None = None,
                         reviewed_from: str = "web@admin") -> dict:
    """Atomically persist one approved manual review without losing peers."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(target):
        if target.is_file():
            manual = json.loads(target.read_text(encoding="utf-8"))
        else:
            manual = {"sites": {}}
        sites = manual.setdefault("sites", {})
        entry = sites.setdefault(hostname, {})
        if login:
            entry["manual_login"] = login
        if signup:
            entry["manual_signup"] = signup
        if note:
            entry["note"] = note
        entry["verified"] = True
        if structured:
            existing_structured = entry.get("structured")
            if not isinstance(existing_structured, dict):
                existing_structured = {}
            existing_structured.update(structured)
            entry["structured"] = existing_structured
        entry["reviewed_from"] = reviewed_from
        manual["updated_at"] = datetime.now(timezone.utc).isoformat()

        fd, tmp_name = tempfile.mkstemp(
            prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(manual, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except Exception:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise
    return entry


def merge_manual_reviews(path: Path | str, incoming: dict) -> dict:
    """Atomically merge a full manual-review document, incoming sites winning."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(target):
        if target.is_file():
            current = json.loads(target.read_text(encoding="utf-8"))
        else:
            current = {"sites": {}}
        current_sites = current.setdefault("sites", {})
        changed = 0
        for hostname, entry in (incoming.get("sites") or {}).items():
            if current_sites.get(hostname) != entry:
                current_sites[hostname] = entry
                changed += 1
        # updated_at describes the resulting document, not the source snapshot.
        # Replaying an older server delta must never roll a newer Git timestamp
        # backwards.  A no-op replay should not rewrite the file at all.
        if not changed and target.is_file():
            return {"updated": 0, "total": len(current_sites)}
        if changed:
            current["updated_at"] = datetime.now(timezone.utc).isoformat()
        elif incoming.get("updated_at"):
            current["updated_at"] = incoming["updated_at"]

        fd, tmp_name = tempfile.mkstemp(
            prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(current, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except Exception:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise
    return {"updated": changed, "total": len(current_sites)}
