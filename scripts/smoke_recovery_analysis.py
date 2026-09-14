#!/usr/bin/env python3
"""Run the B-08 passive recovery probe against a local synthetic page."""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application_security.recovery_analysis import collect_recovery_surface  # noqa: E402
from utils.util_test_password import _get_new_driver  # noqa: E402


HTML = """<!doctype html><html><body>
<form class='login-auth'>
  <input type='password' autocomplete='current-password'>
  <a href='/reset/password'>Forgot password?</a>
  <section><label>Email <input type='email' name='email'></label></section>
</form></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    driver = _get_new_driver()
    try:
        driver.get("http://127.0.0.1:{}/login".format(server.server_port))
        result = collect_recovery_surface(driver, "synthetic.local").to_dict()
    finally:
        driver.quit()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    claims = {item["metric_id"]: item for item in result["claims"]}
    entry = claims["auth.recovery.public_entry"]
    factors = claims["auth.recovery.factor_surface"]
    assert entry["verdict"] == "pass" and entry["value"]["control_count"] == 1
    assert entry["value"]["recovery_path_observed"] is False
    assert "email" in factors["value"]["factor_hints"]
    assert claims["auth.recovery.token_lifecycle"]["verdict"] == "unknown"
    print(json.dumps({
        "entry": entry["value"],
        "factor_surface": factors["value"],
        "token_lifecycle_verdict": claims["auth.recovery.token_lifecycle"]["verdict"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
