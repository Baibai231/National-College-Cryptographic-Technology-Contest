#!/usr/bin/env python3
"""End-to-end local smoke test for the empty virtual-authenticator path."""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from selenium.webdriver.support.ui import WebDriverWait

from application_security.webauthn_observer import (
    collect_webauthn_observations,
    install_webauthn_observer,
)
from application_security.webauthn_safe_interaction import (
    add_empty_virtual_authenticator,
    analyze_safe_interaction,
    install_registration_blocker,
    remove_virtual_authenticator,
    virtual_credential_count,
)
from utils.util_test_password import _get_new_driver


HTML = r"""<!doctype html><meta charset="utf-8"><title>ready</title>
<button id="passkey">Sign in with a passkey</button>
<script>
document.querySelector('#passkey').addEventListener('click',async()=>{
  try{
    await navigator.credentials.get({publicKey:{
      challenge:new Uint8Array(32).fill(11),
      rpId:'localhost',
      allowCredentials:[],
      userVerification:'required',
      timeout:1000
    }});
  }catch(e){}
  document.title='done';
});
</script>"""


def main() -> int:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    driver = None
    authenticator_id = None
    try:
        driver = _get_new_driver()
        errors = list(install_registration_blocker(driver))
        errors.extend(install_webauthn_observer(driver))
        authenticator_id, before, virtual_errors = add_empty_virtual_authenticator(driver)
        errors.extend(virtual_errors)
        driver.get("http://localhost:{}/".format(server.server_port))
        driver.find_element("id", "passkey").click()
        WebDriverWait(driver, 5).until(lambda current: current.title == "done")
        observed = collect_webauthn_observations(driver, "localhost", errors).to_dict()
        after = virtual_credential_count(driver, authenticator_id)
        interaction = analyze_safe_interaction(
            "localhost",
            control={
                "host_guard_passed": True,
                "exact_match_count": 1,
                "clicked": True,
                "click_count": 1,
                "control_kind": "button",
                "label_value_retained": False,
            },
            webauthn_result=observed,
            credentials_before=before,
            credentials_after=after,
            setup_errors=errors,
        ).to_dict()
        output = {
            "credentials_before": before,
            "credentials_after": after,
            "webauthn": observed,
            "interaction": interaction,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        claims = {item["metric_id"]: item for item in interaction["claims"]}
        configuration = next(
            item for item in observed["claims"]
            if item["metric_id"] == "auth.webauthn.request_configuration")
        serialized = json.dumps(output)
        return 0 if (
            claims["auth.webauthn.explicit_control_trigger"]["verdict"] == "pass"
            and claims["auth.webauthn.safe_interaction_guard"]["verdict"] == "pass"
            and configuration["value"]["invocations"][0]["challenge_bytes"] == 32
            and before == 0 and after == 0
            and "11, 11" not in serialized
            and "credentialId" not in serialized
        ) else 1
    finally:
        if driver is not None:
            remove_virtual_authenticator(driver, authenticator_id)
            driver.quit()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
