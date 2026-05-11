from __future__ import annotations

import builtins
import json
import os
import ssl
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from dotenv import load_dotenv

DEFAULT_CALLBACK_URI = "https://localhost:8080/callback"
DEFAULT_TOKEN_PATH = Path.home() / ".yahoo_fantasy_token.json"
CALLBACK_SUCCESS_HTML = b"""<!doctype html>
<html>
  <head><title>Yahoo Auth Complete</title></head>
  <body>
    <h1>Yahoo authorization received.</h1>
    <p>You can close this window and return to the terminal.</p>
  </body>
</html>
"""


def _load_env() -> None:
    load_dotenv()


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable `{name}`. Add it to the project `.env` file first."
        )
    return value


def _token_path(token_path: str | Path | None = None) -> Path:
    configured_path = token_path or os.getenv("YAHOO_TOKEN_PATH", "").strip()
    return Path(configured_path).expanduser() if configured_path else DEFAULT_TOKEN_PATH


def _get_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _callback_uri() -> str:
    return os.getenv("YAHOO_CALLBACK_URI", "").strip() or DEFAULT_CALLBACK_URI


def _is_localhost_callback(callback_uri: str) -> bool:
    parsed = urlparse(callback_uri)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {"localhost", "127.0.0.1"}


def _seed_token_file(path: Path, client_id: str, client_secret: str) -> None:
    payload: dict[str, Any] = {}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}

    payload["consumer_key"] = client_id
    payload["consumer_secret"] = client_secret
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _oauth_data_is_present(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return bool(payload.get("access_token") and payload.get("refresh_token") and payload.get("token_time"))


def _extract_code_from_input(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        return candidate
    parsed = urlparse(candidate)
    if parsed.scheme and parsed.netloc:
        return parse_qs(parsed.query).get("code", [candidate])[0]
    return candidate


def _certificate_base_dir(token_path: Path) -> Path:
    configured_dir = os.getenv("YAHOO_CERT_DIR", "").strip()
    return Path(configured_dir).expanduser() if configured_dir else token_path.parent


def _ensure_localhost_certificate(cert_dir: Path) -> tuple[Path, Path]:
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / "localhost-cert.pem"
    key_path = cert_dir / "localhost-key.pem"
    if cert_path.exists() and key_path.exists():
        return cert_path, key_path

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Fantasy Baseball Analytics Manager"),
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ]
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=5))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(__import__("ipaddress").ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


class _OAuthCallbackServer:
    def __init__(self, callback_uri: str, token_path: Path) -> None:
        parsed = urlparse(callback_uri)
        self.host = parsed.hostname or "localhost"
        self.port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self.path = parsed.path or "/"
        self.scheme = parsed.scheme
        self.token_path = token_path
        self._event = threading.Event()
        self._code: str | None = None
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        handler = self._build_handler()
        self._server = HTTPServer((self.host, self.port), handler)
        if self.scheme == "https":
            cert_path, key_path = _ensure_localhost_certificate(_certificate_base_dir(self.token_path))
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
            self._server.socket = context.wrap_socket(self._server.socket, server_side=True)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def wait_for_code(self, timeout: float = 300.0) -> str:
        if not self._event.wait(timeout):
            raise TimeoutError("Timed out waiting for Yahoo OAuth callback on localhost.")
        assert self._code is not None
        return self._code

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _build_handler(self):
        outer = self

        class CallbackHandler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path != outer.path:
                    self.send_response(404)
                    self.end_headers()
                    return

                params = parse_qs(parsed.query)
                code = params.get("code", [None])[0]
                if not code:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Missing OAuth code.")
                    return

                outer._code = code
                outer._event.set()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(CALLBACK_SUCCESS_HTML)))
                self.end_headers()
                self.wfile.write(CALLBACK_SUCCESS_HTML)

        return CallbackHandler


def _run_localhost_oauth(OAuth2, oauth_kwargs: dict[str, Any], token_path: Path):
    callback_uri = str(oauth_kwargs["callback_uri"])
    server = _OAuthCallbackServer(callback_uri, token_path=token_path)
    server.start()
    original_input = builtins.input

    def _wait_for_callback(prompt: str = "") -> str:
        print(prompt, end="")
        if callback_uri.startswith("https://"):
            print("Your browser may show a one-time security warning for the local self-signed certificate.")
            print("Choose the advanced/continue option for `https://localhost:8080/callback` to finish Yahoo auth.")
        print(f"\nWaiting for Yahoo callback on {callback_uri} ...")
        return server.wait_for_code()

    try:
        builtins.input = _wait_for_callback
        return OAuth2(None, None, **oauth_kwargs)
    finally:
        builtins.input = original_input
        server.stop()


def _run_oob_oauth(OAuth2, oauth_kwargs: dict[str, Any]):
    original_input = builtins.input

    def _read_oob_code(prompt: str = "") -> str:
        print("Yahoo may show the authorization code in the browser URL after consent.")
        print("Paste either the raw code or the full browser URL here.")
        value = original_input(prompt)
        return _extract_code_from_input(value)

    try:
        builtins.input = _read_oob_code
        return OAuth2(None, None, **oauth_kwargs)
    finally:
        builtins.input = original_input


def get_league_id() -> str:
    _load_env()
    return _require_env("YAHOO_LEAGUE_ID")


def get_sc(token_path: str | Path | None = None):
    _load_env()

    try:
        from yahoo_oauth import OAuth2
    except ImportError as exc:
        raise RuntimeError(
            "Yahoo dependencies are not installed. Run `pip install -r requirements.txt` first."
        ) from exc

    client_id = _require_env("YAHOO_CLIENT_ID")
    client_secret = _require_env("YAHOO_CLIENT_SECRET")
    oauth_path = _token_path(token_path)
    _seed_token_file(oauth_path, client_id, client_secret)

    callback_uri = _callback_uri()
    open_browser = _get_bool_env("YAHOO_OPEN_BROWSER", True)
    oauth_kwargs: dict[str, Any] = {
        "from_file": str(oauth_path),
        "browser_callback": open_browser,
        "callback_uri": callback_uri,
    }

    first_time_auth = not _oauth_data_is_present(oauth_path)
    use_localhost_flow = _is_localhost_callback(callback_uri) and first_time_auth
    use_oob_flow = callback_uri == "oob" and first_time_auth
    if use_localhost_flow:
        session = _run_localhost_oauth(OAuth2, oauth_kwargs, token_path=oauth_path)
    elif use_oob_flow:
        session = _run_oob_oauth(OAuth2, oauth_kwargs)
    else:
        session = OAuth2(None, None, **oauth_kwargs)

    if hasattr(session, "token_is_valid") and not session.token_is_valid():
        if hasattr(session, "refresh_access_token"):
            session.refresh_access_token()
        if hasattr(session, "token_is_valid") and not session.token_is_valid():
            session = OAuth2(None, None, **oauth_kwargs)
    return session
