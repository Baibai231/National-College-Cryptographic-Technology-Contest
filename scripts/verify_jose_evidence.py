#!/usr/bin/env python3
"""Verify one compact JWT from stdin and emit redacted research evidence.

The compact token is never accepted as a command-line argument (which would
leak it through process listings) and is never included in stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application_security.jose_validation import (  # noqa: E402
    analyze_jose_metadata,
    verify_compact_jwt,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="RFC 7515/8725 JWT verification with redacted output")
    parser.add_argument("--jwks", type=Path, help="public JWKS JSON file")
    parser.add_argument("--allow-alg", action="append", default=[],
                        help="explicit accepted algorithm; repeat as needed")
    parser.add_argument("--issuer", help="expected issuer (not printed)")
    parser.add_argument("--audience", help="expected audience (not printed)")
    parser.add_argument("--nonce", help="expected nonce (not printed)")
    parser.add_argument("--typ", help="expected typ header (not printed)")
    parser.add_argument("--parameter", default="",
                        help="source parameter, e.g. id_token or response")
    args = parser.parse_args()

    token = sys.stdin.read().strip()
    if not token:
        parser.error("compact JWT must be supplied through stdin")
    jwks = None
    if args.jwks:
        jwks = json.loads(args.jwks.read_text(encoding="utf-8"))
    report = verify_compact_jwt(
        token,
        jwks=jwks,
        allowed_algorithms=args.allow_alg,
        expected_issuer=args.issuer,
        expected_audience=args.audience,
        expected_nonce=args.nonce,
        expected_typ=args.typ,
        parameter=args.parameter,
    )
    result = analyze_jose_metadata("offline", [report]).to_dict()
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
