#!/usr/bin/env python3
"""Run the WebAuthn observer against an isolated, synthetic browser page.

The page replaces credential and lifecycle APIs with inert promises before the
observer is installed.  It cannot contact an authenticator or create a real
credential; it only verifies that page-initiated calls are redacted and
classified correctly by the production observer.
"""

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
from utils.util_test_password import _get_new_driver


FAKE_API_SCRIPT = r"""
(()=>{
  const inertCredentials={
    create:async()=>({synthetic:true}),
    get:async()=>({synthetic:true})
  };
  Object.defineProperty(navigator,'credentials',{
    value:inertCredentials,configurable:true
  });
  const FakePublicKeyCredential=function(){};
  for(const name of [
    'signalAllAcceptedCredentials','signalUnknownCredential',
    'signalCurrentUserDetails']){
    Object.defineProperty(FakePublicKeyCredential,name,{
      value:async()=>undefined,configurable:true
    });
  }
  Object.defineProperty(globalThis,'PublicKeyCredential',{
    value:FakePublicKeyCredential,configurable:true
  });
})();
"""


SYNTHETIC_HTML = r"""<!doctype html><meta charset="utf-8"><title>running</title>
<script>
const repeated=new Uint8Array(32).fill(7);
navigator.credentials.get({
  publicKey:{challenge:repeated,userVerification:'discouraged',allowCredentials:[]},
  mediation:'conditional'
});
navigator.credentials.get({
  publicKey:{challenge:repeated,userVerification:'discouraged',allowCredentials:[]},
  mediation:'conditional'
});
navigator.credentials.create({publicKey:{
  challenge:new Uint8Array(32).fill(9),
  user:{id:new Uint8Array(16)},
  pubKeyCredParams:[{type:'public-key',alg:-37},{type:'public-key',alg:-65535},
    {type:'public-key',alg:5}],
  authenticatorSelection:{residentKey:'required',requireResidentKey:true,
    userVerification:'required'},
  attestation:'none'
}});
PublicKeyCredential.signalAllAcceptedCredentials({
  userId:'synthetic-user-never-exported',
  allAcceptedCredentialIds:['synthetic-id-one','synthetic-id-two']
});
setTimeout(()=>{document.title='done';},250);
</script>"""


def main() -> int:
    class SyntheticHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = SYNTHETIC_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), SyntheticHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    driver = None
    try:
        driver = _get_new_driver()
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": FAKE_API_SCRIPT},
        )
        errors = install_webauthn_observer(driver)
        driver.get("http://localhost:{}/".format(server.server_port))
        WebDriverWait(driver, 5).until(lambda current: current.title == "done")
        WebDriverWait(driver, 5).until(lambda current: current.execute_script(
            "return globalThis.__cryptoscopeReadWebAuthnObserverV1().filter("
            "x=>x.challenge_equality_checked===true).length===3"))
        result = collect_webauthn_observations(
            driver, "synthetic.invalid", errors).to_dict()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        claims = {item["metric_id"]: item for item in result["claims"]}
        challenge = claims["auth.webauthn.challenge_length"]
        algorithms = claims["auth.webauthn.cose_algorithm_policy"]
        lifecycle = claims["auth.webauthn.lifecycle_sync"]
        return 0 if (
            challenge["value"]["reused_in_document_count"] == 1
            and algorithms["verdict"] == "weak"
            and lifecycle["value"]["invocation_count"] == 1
            and "synthetic-user-never-exported" not in json.dumps(result)
            and "synthetic-id-one" not in json.dumps(result)
        ) else 1
    finally:
        if driver is not None:
            driver.quit()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
