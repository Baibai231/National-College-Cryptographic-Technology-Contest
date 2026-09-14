#!/usr/bin/env python3
"""Safely probe explicit public OIDC/OAuth issuers and emit redacted evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application_security.oidc_discovery import probe_oidc_discovery  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bounded HTTPS OIDC Discovery/JWKS probe; output never contains "
            "raw metadata or JWK material"
        ))
    parser.add_argument(
        "issuer", nargs="+", help="explicit public HTTPS issuer URL (maximum 3)")
    args = parser.parse_args()
    candidates = [
        {"issuer": issuer, "role": "operator_supplied"}
        for issuer in args.issuer
    ]
    result = probe_oidc_discovery("operator-supplied", candidates).to_dict()
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
