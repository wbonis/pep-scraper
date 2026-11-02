"""Minimal fake of the LOGA3 login + dashboard flow for browser tests."""

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

SHIFT_PATH = "/loga3/private/api/dashboard/pep/loadShiftsDashboard"

LOGIN_HTML = """<!doctype html><html><body>
<form action="/loga3/private/layout?action=afterlogin" method="post">
  <input id="username" type="text">
  <input id="password" type="password">
  <input id="twofatoken" type="text" style="{twofa_style}">
  <input id="captchaInput" type="text" style="{captcha_style}">
  <a id="submit" href="#">ANMELDEN</a>
</form>
<div id="message"></div>
<div id="errorMessage" class="message alert" style="display: none;">
  <p>Die Kennung bzw. das Kennwort ist falsch!</p></div>
<div id="loginLocked" class="message alert" style="display: none;">
  <p>Das System ist aktuell aufgrund von Wartungsarbeiten gesperrt.</p></div>
<script>
document.getElementById('submit').addEventListener('click', ev => {{
  ev.preventDefault();
  const u = document.getElementById('username').value;
  const p = document.getElementById('password').value;
  if ({maintenance}) {{
    document.getElementById('loginLocked').style.display = 'block';
  }} else if (u === 'alice' && p === 's3cret') {{
    location.href = '/loga3/private/layout?action=afterlogin';
  }} else {{
    setTimeout(() => {{
      document.getElementById('errorMessage').style.display = 'block';
    }}, 300);
  }}
}});
</script></body></html>"""

PASSWORD_CHANGE_HTML = """<!doctype html><html><body>
<p>Ihr Kennwort ist abgelaufen. Bitte vergeben Sie ein neues Kennwort.</p>
<input type="password" id="newPwd"></body></html>"""

DASHBOARD_HTML = """<!doctype html><html><body>Dashboard
<script>
fetch('/loga3/private/api/dashboard/common/loadSetting?xsrf=abc');
fetch('{shift_path}?millis=1&xsrf=abc&securityId=TESTID');
</script></body></html>"""


@dataclass(frozen=True)
class FakeOptions:
    payload: dict[str, Any]
    captcha_visible: bool = False
    twofa_visible: bool = False
    shift_status: int = 200
    maintenance: bool = False
    password_expired: bool = False


def _handler(opts: FakeOptions) -> type[BaseHTTPRequestHandler]:
    hidden = "display:none;"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            return

        def _send(self, status: int, body: str, ctype: str) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/loga3/":
                html = LOGIN_HTML.format(
                    captcha_style="" if opts.captcha_visible else hidden,
                    twofa_style="" if opts.twofa_visible else hidden,
                    maintenance="true" if opts.maintenance else "false",
                )
                self._send(200, html, "text/html")
            elif path == "/loga3/private/layout" and opts.password_expired:
                self._send(200, PASSWORD_CHANGE_HTML, "text/html")
            elif path == "/loga3/private/layout":
                html = DASHBOARD_HTML.format(shift_path=SHIFT_PATH)
                self._send(200, html, "text/html")
            elif path == SHIFT_PATH:
                body = json.dumps(opts.payload) if opts.shift_status == 200 else "x"
                self._send(opts.shift_status, body, "application/json")
            else:
                self._send(200, "{}", "application/json")

    return Handler


@contextmanager
def serve(opts: FakeOptions) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(opts))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
