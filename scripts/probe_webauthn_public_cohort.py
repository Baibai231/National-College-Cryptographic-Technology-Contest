#!/usr/bin/env python3
"""Measure a fixed, paper-derived Passkey cohort without user interaction."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application_security.oidc_discovery import (  # noqa: E402
    SafeFetchError,
    validate_public_https_url,
)
from application_security.passive_protocol_probe import (  # noqa: E402
    collect_passive_protocol_metadata,
)
from application_security.passkey_well_known import (  # noqa: E402
    probe_passkey_well_known,
)
from application_security.webauthn_observer import (  # noqa: E402
    collect_webauthn_observations,
    install_webauthn_observer,
)


DEFAULT_COHORT = ROOT / "config" / "webauthn_public_cohort.json"


def _redact_public_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if not host:
            return ""
        netloc = "[{}]".format(host) if ":" in host else host
        return urlunsplit((parsed.scheme, netloc, parsed.path or "/", "", ""))
    except Exception:
        return ""


def _validate_https_shape(value: str) -> None:
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.fragment or parsed.port not in (None, 443)):
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise ValueError("invalid public HTTPS URL shape") from exc


def _load_cohort(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        cohort = json.load(handle)
    if cohort.get("schema_version") != "webauthn-public-cohort-1.0":
        raise ValueError("unsupported cohort schema")
    sites = cohort.get("sites")
    if not isinstance(sites, list) or not 1 <= len(sites) <= 30:
        raise ValueError("cohort must contain 1..30 sites")
    seen = set()
    for site in sites:
        if not isinstance(site, dict):
            raise ValueError("site entries must be objects")
        site_id = site.get("site_id")
        if not isinstance(site_id, str) or site_id in seen:
            raise ValueError("site_id must be a unique string")
        seen.add(site_id)
        for field in ("public_entry_url", "well_known_origin"):
            value = site.get(field)
            if not isinstance(value, str):
                raise ValueError("{} missing {}".format(site_id, field))
            _validate_https_shape(value)
    return cohort


def _browser_probe(site: Dict[str, Any], wait_seconds: float) -> Dict[str, Any]:
    # Importing the legacy driver starts Chrome version discovery, so keep it
    # out of analysis/test-only imports.
    from utils.util_test_password import _get_new_driver

    entry = site["public_entry_url"]
    driver = None
    navigation_errors = []
    loaded = False
    final_url = ""
    started = time.monotonic()
    try:
        validate_public_https_url(entry)
    except SafeFetchError as exc:
        return {
            "navigation": {
                "loaded": False,
                "requested_url": _redact_public_url(entry),
                "final_url": "",
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "errors": ["entry_url:" + exc.code],
                "clicks": 0,
                "inputs": 0,
                "probe_initiated_credential_calls": 0,
            },
            "passive_protocol": {
                "module_id": "b.passive_protocol_metadata",
                "schema_version": "passive-protocol-metadata-1.0",
                "scan_mode": "passive", "claims": [], "evidence": [],
                "errors": ["browser_skipped:" + exc.code], "limitations": [],
            },
            "webauthn_observer": {
                "module_id": "b.webauthn_request_observer",
                "schema_version": "webauthn-request-observer-1.1",
                "scan_mode": "passive", "claims": [], "evidence": [],
                "errors": ["browser_skipped:" + exc.code], "limitations": [],
            },
        }
    try:
        driver = _get_new_driver()
        install_errors = install_webauthn_observer(driver)
        try:
            driver.get(entry)
            loaded = True
        except Exception as exc:
            navigation_errors.append("navigation:" + type(exc).__name__)
            try:
                driver.execute_script("window.stop()")
            except Exception:
                pass
        time.sleep(wait_seconds)
        try:
            final_url = _redact_public_url(driver.current_url)
            if final_url:
                validate_public_https_url(final_url)
        except SafeFetchError as exc:
            navigation_errors.append("final_url:" + exc.code)
            final_url = ""
        except Exception as exc:
            navigation_errors.append("final_url:" + type(exc).__name__)
            final_url = ""
        webauthn = collect_webauthn_observations(
            driver, site["site_id"], install_errors).to_dict()
        passive = collect_passive_protocol_metadata(
            driver, site["site_id"]).to_dict()
    except Exception as exc:
        navigation_errors.append("browser:" + type(exc).__name__)
        webauthn = {
            "module_id": "b.webauthn_request_observer",
            "schema_version": "webauthn-request-observer-1.1",
            "scan_mode": "passive",
            "claims": [], "evidence": [],
            "errors": ["browser_unavailable:" + type(exc).__name__],
            "limitations": [],
        }
        passive = {
            "module_id": "b.passive_protocol_metadata",
            "schema_version": "passive-protocol-metadata-1.0",
            "scan_mode": "passive",
            "claims": [], "evidence": [],
            "errors": ["browser_unavailable:" + type(exc).__name__],
            "limitations": [],
        }
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                navigation_errors.append("browser_quit_failed")
    return {
        "navigation": {
            "loaded": loaded,
            "requested_url": _redact_public_url(entry),
            "final_url": final_url,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "errors": navigation_errors,
            "clicks": 0,
            "inputs": 0,
            "probe_initiated_credential_calls": 0,
        },
        "passive_protocol": passive,
        "webauthn_observer": webauthn,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round-id", required=True)
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wait-seconds", type=float, default=4.0)
    args = parser.parse_args()
    if not 0.5 <= args.wait_seconds <= 15:
        parser.error("--wait-seconds must be between 0.5 and 15")
    if args.output.exists():
        parser.error("output already exists; choose a new round file")
    cohort = _load_cohort(args.cohort.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("SITES_HEADLESS", "1")

    with args.output.open("x", encoding="utf-8") as output:
        for index, site in enumerate(cohort["sites"], start=1):
            print("[{}/{}] {}".format(index, len(cohort["sites"]), site["site_id"]), flush=True)
            record = {
                "schema_version": "webauthn-public-observation-1.0",
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "round_id": args.round_id,
                "cohort": {
                    "paper": cohort["paper"],
                    "artifact_repository": cohort["artifact_repository"],
                    "artifact_commit": cohort["artifact_commit"],
                    "artifact_snapshot": cohort["artifact_snapshot"],
                    "selection_rule": cohort["selection_rule"],
                    "positive_directory_membership": True,
                },
                "site_id": site["site_id"],
                "directory_domain": site["directory_domain"],
                "browser_probe": _browser_probe(site, args.wait_seconds),
                "well_known": probe_passkey_well_known(
                    site["well_known_origin"]).to_dict(),
                "interpretation_boundary": (
                    "Directory membership is a positive Passkey claim; absent public-page "
                    "evidence is UNKNOWN, not a negative support verdict."
                ),
            }
            json.dump(record, output, ensure_ascii=False, sort_keys=True)
            output.write("\n")
            output.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
