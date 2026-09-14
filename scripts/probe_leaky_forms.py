#!/usr/bin/env python3
"""Run the explicit B-10 safe-interaction probe on one public HTTPS page."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application_security.leaky_forms import (  # noqa: E402
    install_leaky_forms_observer,
    run_leaky_forms_safe_interaction,
)
from application_security.oidc_discovery import validate_public_https_url  # noqa: E402
from utils.util_test_password import _get_new_driver  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="explicit public HTTPS login/signup page")
    parser.add_argument("--wait-seconds", type=float, default=2.0)
    args = parser.parse_args()
    if not 0 <= args.wait_seconds <= 10:
        parser.error("--wait-seconds must be between 0 and 10")
    validate_public_https_url(args.url)
    os.environ.setdefault("SITES_HEADLESS", "1")
    driver = _get_new_driver()
    try:
        install_errors = install_leaky_forms_observer(driver)
        driver.get(args.url)
        result = run_leaky_forms_safe_interaction(driver, args.url).to_dict()
        if args.wait_seconds:
            time.sleep(args.wait_seconds)
            # Collect once more without filling again so delayed attempts enter the result.
            from application_security.leaky_forms import _COLLECT_SCRIPT, analyze_leaky_form_observation
            observation = driver.execute_script(_COLLECT_SCRIPT) or {}
            result = analyze_leaky_form_observation(args.url, observation, install_errors).to_dict()
    finally:
        driver.quit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
