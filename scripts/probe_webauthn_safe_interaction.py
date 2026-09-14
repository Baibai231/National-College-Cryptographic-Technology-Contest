#!/usr/bin/env python3
"""Run one guarded Passkey-control interaction against an explicit allowlist."""

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
from application_security.webauthn_observer import (  # noqa: E402
    collect_webauthn_observations,
    install_webauthn_observer,
)
from application_security.webauthn_safe_interaction import (  # noqa: E402
    add_empty_virtual_authenticator,
    analyze_safe_interaction,
    click_exact_passkey_control,
    install_registration_blocker,
    remove_virtual_authenticator,
    virtual_credential_count,
)


DEFAULT_TARGETS = ROOT / "config" / "webauthn_safe_interaction_targets.json"


def _redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if not parsed.hostname:
            return ""
        return urlunsplit((parsed.scheme, parsed.hostname, parsed.path or "/", "", ""))
    except Exception:
        return ""


def _load_targets(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    if config.get("schema_version") != "webauthn-safe-interaction-targets-1.0":
        raise ValueError("unsupported target schema")
    sites = config.get("sites")
    if not isinstance(sites, list) or not 1 <= len(sites) <= 10:
        raise ValueError("allowlist must contain 1..10 sites")
    seen = set()
    for site in sites:
        if not isinstance(site, dict):
            raise ValueError("site must be an object")
        site_id = site.get("site_id")
        if not isinstance(site_id, str) or site_id in seen:
            raise ValueError("site_id must be unique")
        seen.add(site_id)
        if site.get("maximum_clicks") != 1:
            raise ValueError("maximum_clicks must equal 1")
        if site.get("allowed_ceremony") != "authentication":
            raise ValueError("only authentication is allowed")
        labels = site.get("expected_labels")
        if not isinstance(labels, list) or not 1 <= len(labels) <= 5:
            raise ValueError("expected_labels must contain 1..5 strings")
        if any(not isinstance(label, str) or not label.strip() for label in labels):
            raise ValueError("invalid expected label")
        entry = site.get("public_entry_url")
        parsed = urlsplit(entry if isinstance(entry, str) else "")
        if (parsed.scheme != "https" or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.fragment or parsed.port not in (None, 443)):
            raise ValueError("invalid public entry URL")
        allowed_host = site.get("allowed_host")
        if not isinstance(allowed_host, str) or not allowed_host:
            raise ValueError("missing allowed_host")
        if not (parsed.hostname == allowed_host
                or parsed.hostname.endswith("." + allowed_host)):
            raise ValueError("entry URL is outside allowed_host")
    return config


def _claim_value(result: Dict[str, Any], metric_id: str) -> Dict[str, Any]:
    for claim in result.get("claims") or []:
        if claim.get("metric_id") == metric_id:
            value = claim.get("value")
            return value if isinstance(value, dict) else {}
    return {}


def _ceremony_count(result: Dict[str, Any], ceremony: str) -> int:
    configuration = _claim_value(
        result, "auth.webauthn.request_configuration")
    invocations = configuration.get("invocations") or []
    return sum(
        isinstance(item, dict) and item.get("ceremony") == ceremony
        for item in invocations
    )


def _navigate_bounded(driver, entry: str, timeout_seconds: float = 25.0) -> tuple:
    """Navigate without waiting for every long-lived subresource to finish."""
    errors = []
    try:
        response = driver.execute_cdp_cmd("Page.navigate", {"url": entry})
        if isinstance(response, dict) and response.get("errorText"):
            errors.append("navigation:cdp_error")
    except Exception as exc:
        return False, ("navigation:" + type(exc).__name__,)
    deadline = time.monotonic() + timeout_seconds
    document_ready = False
    while time.monotonic() < deadline:
        try:
            current = driver.current_url
            parsed = urlsplit(current)
            if parsed.scheme == "https" and parsed.hostname:
                state = driver.execute_script("return document.readyState")
                if state in {"interactive", "complete"}:
                    document_ready = True
                    break
        except Exception:
            pass
        time.sleep(0.25)
    if not document_ready:
        errors.append("navigation:document_not_ready")
    return document_ready, tuple(errors)


def _run_site(site: Dict[str, Any], wait_seconds: float) -> Dict[str, Any]:
    from utils.util_test_password import _get_new_driver

    entry = site["public_entry_url"]
    started = time.monotonic()
    driver = None
    authenticator_id = None
    credentials_before = None
    credentials_after = None
    errors = []
    loaded = False
    final_url = ""
    control: Dict[str, Any] = {
        "host_guard_passed": False,
        "exact_match_count": 0,
        "clicked": False,
        "click_count": 0,
        "control_kind": "",
        "label_value_retained": False,
        "error": "guard_not_ready",
    }
    empty_webauthn = {
        "module_id": "b.webauthn_request_observer",
        "schema_version": "webauthn-request-observer-1.1",
        "scan_mode": "passive",
        "claims": [], "evidence": [], "errors": [], "limitations": [],
    }
    webauthn = empty_webauthn
    pre_click_authentication_count = 0
    try:
        try:
            validate_public_https_url(entry)
        except SafeFetchError as exc:
            errors.append("entry_url:" + exc.code)
            raise RuntimeError("entry URL safety check failed")
        driver = _get_new_driver()
        blocker_errors = install_registration_blocker(driver)
        observer_errors = install_webauthn_observer(driver)
        authenticator_id, credentials_before, virtual_errors = (
            add_empty_virtual_authenticator(driver))
        errors.extend(blocker_errors)
        errors.extend(observer_errors)
        errors.extend(virtual_errors)
        guard_ready = bool(
            authenticator_id and credentials_before == 0 and not errors)
        if not guard_ready:
            errors.append("pre_click_guard_not_ready")
        loaded, navigation_errors = _navigate_bounded(driver, entry)
        errors.extend(navigation_errors)
        try:
            final_url = _redact_url(driver.current_url)
            if final_url:
                validate_public_https_url(final_url)
        except SafeFetchError as exc:
            errors.append("final_url:" + exc.code)
            final_url = ""
        except Exception as exc:
            errors.append("final_url:" + type(exc).__name__)
            final_url = ""
        # Modern authentication pages may keep network work open past the
        # WebDriver page-load timeout.  A completed load event is not a safety
        # boundary: the exact visible-control matcher plus final HTTPS host
        # guard are.  Therefore a timed-out but correctly hosted, rendered
        # control may still be measured.
        if guard_ready and final_url:
            control_deadline = time.monotonic() + 15.0
            while time.monotonic() < control_deadline:
                pre_click = collect_webauthn_observations(
                    driver, site["site_id"], observer_errors).to_dict()
                pre_click_authentication_count = _ceremony_count(
                    pre_click, "authentication")
                if (_claim_value(pre_click, "auth.webauthn.api_invocation")
                        .get("invocation_count")):
                    webauthn = pre_click
                    control = {
                        "host_guard_passed": True,
                        "label_match_count": 0,
                        "visible_label_match_count": 0,
                        "exact_match_count": 0,
                        "clicked": False,
                        "click_count": 0,
                        "control_kind": "",
                        "label_value_retained": False,
                        "error": "page_initiated_before_click",
                    }
                    break
                control = click_exact_passkey_control(
                    driver,
                    allowed_host=site["allowed_host"],
                    expected_labels=site["expected_labels"],
                )
                if control.get("clicked"):
                    break
                time.sleep(0.25)
            if control.get("clicked"):
                deadline = time.monotonic() + wait_seconds
                while time.monotonic() < deadline:
                    webauthn = collect_webauthn_observations(
                        driver, site["site_id"], observer_errors).to_dict()
                    invocation = _claim_value(
                        webauthn, "auth.webauthn.api_invocation")
                    if invocation.get("invocation_count"):
                        break
                    time.sleep(0.25)
        webauthn = collect_webauthn_observations(
            driver, site["site_id"], observer_errors).to_dict()
        credentials_after = virtual_credential_count(driver, authenticator_id)
    except Exception as exc:
        if not any(item.startswith("entry_url:") for item in errors):
            errors.append("runtime:" + type(exc).__name__)
    finally:
        if driver is not None:
            errors.extend(remove_virtual_authenticator(driver, authenticator_id))
            try:
                driver.quit()
            except Exception:
                errors.append("browser_quit_failed")
    interaction = analyze_safe_interaction(
        site["site_id"],
        control=control,
        webauthn_result=webauthn,
        credentials_before=credentials_before,
        credentials_after=credentials_after,
        pre_click_authentication_count=pre_click_authentication_count,
        setup_errors=errors,
        input_count=0,
    ).to_dict()
    return {
        "navigation": {
            "requested_url": _redact_url(entry),
            "final_url": final_url,
            "loaded": loaded,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "errors": errors,
        },
        "control": control,
        "virtual_authenticator": {
            "protocol": "ctap2",
            "ctap2_version": "ctap2_1",
            "transport": "internal",
            "credentials_before": credentials_before,
            "credentials_after": credentials_after,
            "credential_material_retained": False,
            "real_authenticator_used": False,
        },
        "webauthn_observer": webauthn,
        "safe_interaction": interaction,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round-id", required=True)
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wait-seconds", type=float, default=8.0)
    args = parser.parse_args()
    if not 1 <= args.wait_seconds <= 15:
        parser.error("--wait-seconds must be between 1 and 15")
    if args.output.exists():
        parser.error("output already exists")
    config = _load_targets(args.targets.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("SITES_HEADLESS", "1")
    with args.output.open("x", encoding="utf-8") as output:
        for index, site in enumerate(config["sites"], start=1):
            print("[{}/{}] {}".format(index, len(config["sites"]), site["site_id"]), flush=True)
            record = {
                "schema_version": "webauthn-safe-interaction-observation-1.0",
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "round_id": args.round_id,
                "site_id": site["site_id"],
                "allowlist": {
                    "selection_evidence": config["selection_evidence"],
                    "selection_result": config["selection_result"],
                    "maximum_clicks": 1,
                    "allowed_ceremony": "authentication",
                },
                "result": _run_site(site, args.wait_seconds),
            }
            json.dump(record, output, ensure_ascii=False, sort_keys=True)
            output.write("\n")
            output.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
