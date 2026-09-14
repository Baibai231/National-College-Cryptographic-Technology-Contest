#!/usr/bin/env python3
"""Exercise B-09 with a rotating synthetic QR-like canvas in real Chrome."""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application_security.qr_lifecycle import (  # noqa: E402
    _SAMPLE_SCRIPT,
    analyze_qr_observations,
    install_qr_lifecycle_observer,
)
from utils.util_test_password import _get_new_driver  # noqa: E402


HTML = """<!doctype html><html><body>
<section id='qr-login'><h1>Scan QR code to login</h1><canvas id='qrcode' width='64' height='64'></canvas></section>
<script>
const c=document.getElementById('qrcode'),x=c.getContext('2d');let n=0;
function paint(){n++;x.fillStyle=n%2?'black':'white';x.fillRect(0,0,64,64);x.fillStyle=n%2?'white':'black';x.fillRect(8,8,24,24);}
paint();setTimeout(paint,350);
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
        install_errors = install_qr_lifecycle_observer(driver)
        driver.get("http://127.0.0.1:{}/login".format(server.server_port))
        first = driver.execute_async_script(_SAMPLE_SCRIPT)
        time.sleep(0.6)
        second = driver.execute_async_script(_SAMPLE_SCRIPT)
        result = analyze_qr_observations(
            "synthetic.local", [first, second], install_errors).to_dict()
    finally:
        driver.quit()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    claims = {item["metric_id"]: item for item in result["claims"]}
    assert claims["auth.qr.rendered_login_code"]["verdict"] == "pass"
    assert claims["auth.qr.page_refresh"]["value"]["comparison_count"] == 1
    assert claims["auth.qr.page_refresh"]["value"]["change_count"] == 1
    assert claims["auth.qr.protocol_security_variables"]["verdict"] == "unknown"
    assert claims["auth.qr.passive_safety_guard"]["verdict"] == "pass"
    print(json.dumps({
        "presence": claims["auth.qr.rendered_login_code"],
        "refresh": claims["auth.qr.page_refresh"],
        "security": claims["auth.qr.protocol_security_variables"],
        "guard": claims["auth.qr.passive_safety_guard"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
