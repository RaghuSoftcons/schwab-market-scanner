# ============================================================================
# File:          auth.py
# Project:       Schwab Market Scanner
# Created:       2026-07-01 07:35 EST
# Author:        Claude (Anthropic) + Raghu
# Version:       1.0.0
# Purpose:       Dashboard authentication for multi-trader access. Stdlib-only
#                (pbkdf2 password hashing + HMAC-signed session cookies), a
#                file/env-backed user store, and a per-request "current trader"
#                context var used to stamp order-audit attribution. Enforcement
#                (middleware + /login) lives in app.py; this module is the engine.
# Last Modified: 2026-07-01 07:35 EST
# Change Log:
#   2026-07-01 07:35 EST  v1.0.0  Initial multi-trader auth engine (Claude + Raghu).
# ============================================================================
"""Password hashing, signed sessions, and the user store for dashboard login.

Design notes:
- No third-party crypto deps: password hashing is `hashlib.pbkdf2_hmac` and
  session tokens are HMAC-SHA256 signed. This keeps the deploy footprint tiny.
- Passwords are NEVER stored or logged in plaintext. Only pbkdf2 digests live in
  the user store (a gitignored JSON file locally, or the `DASHBOARD_USERS_JSON`
  env var on Railway).
- Attribution: `set_current_trader()` is called by the auth middleware per
  request; `current_trader_name()` is read by `OrderAuditStore.append` so every
  order event is stamped with who was logged in.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

_ALGO = "pbkdf2_sha256"
_PBKDF2_ROUNDS = 240_000
DEFAULT_COOKIE_NAME = "uts_session"


# --------------------------------------------------------------------------- #
# Password hashing (pbkdf2_sha256$rounds$salt_b64$hash_b64)
# --------------------------------------------------------------------------- #
def hash_password(password: str, *, salt: bytes | None = None, rounds: int = _PBKDF2_ROUNDS) -> str:
    """Return a self-describing pbkdf2 hash string for ``password``."""
    if not password:
        raise ValueError("password cannot be empty")
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return f"{_ALGO}${rounds}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verify of ``password`` against a stored pbkdf2 hash."""
    try:
        algo, rounds_s, salt_b64, hash_b64 = str(stored).split("$", 3)
        if algo != _ALGO:
            return False
        rounds = int(rounds_s)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, rounds)
    return hmac.compare_digest(dk, expected)


# --------------------------------------------------------------------------- #
# Signed session tokens (body.sig, HMAC-SHA256, with expiry)
# --------------------------------------------------------------------------- #
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_session(username: str, secret: str, *, ttl_seconds: int, issued_at: int | None = None) -> str:
    """Return a signed ``body.sig`` session token carrying username + expiry."""
    if not secret:
        raise ValueError("session secret required")
    if not username:
        raise ValueError("username required")
    iat = int(issued_at if issued_at is not None else time.time())
    payload = {"u": username, "exp": iat + int(ttl_seconds)}
    body = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64e(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_session(token: str, secret: str, *, now: int | None = None) -> str | None:
    """Return the username if ``token`` has a valid signature and is unexpired, else None."""
    if not token or not secret or "." not in token:
        return None
    body, _, sig = token.partition(".")
    expected = _b64e(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64d(body))
    except (ValueError, json.JSONDecodeError):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)):
        return None
    if (now if now is not None else time.time()) >= exp:
        return None
    user = payload.get("u")
    return user if isinstance(user, str) and user else None


# --------------------------------------------------------------------------- #
# Current-trader attribution (set by middleware, read by the order audit store)
# --------------------------------------------------------------------------- #
_current_trader: ContextVar[str] = ContextVar("current_trader", default="")


def set_current_trader(name: str) -> None:
    _current_trader.set((name or "").strip())


def verify_machine_key(provided: str, expected: str) -> bool:
    """Constant-time check for the machine-to-machine API key (signal relay, etc.)."""
    if not expected or not provided:
        return False
    return hmac.compare_digest(str(provided), str(expected))


def current_trader_name(default: str = "") -> str:
    """The logged-in trader for this request, or ``default`` (or DASHBOARD_OWNER_NAME)."""
    value = _current_trader.get()
    if value:
        return value
    if default:
        return default
    return os.environ.get("DASHBOARD_OWNER_NAME", "Raghu").strip() or "Raghu"


# --------------------------------------------------------------------------- #
# User store (JSON file locally, or inline DASHBOARD_USERS_JSON for Railway)
# --------------------------------------------------------------------------- #
def _normalize_users(raw: Any) -> dict[str, dict[str, Any]]:
    """Accept ``{"users": {...}}`` or a bare ``{...}`` map; key by lowercase username."""
    if isinstance(raw, dict) and isinstance(raw.get("users"), dict):
        raw = raw["users"]
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name, rec in raw.items():
        key = str(name).strip().lower()
        if not key or not isinstance(rec, dict):
            continue
        out[key] = {
            "username": key,
            "display_name": str(rec.get("display_name") or name).strip() or key,
            "password_hash": str(rec.get("password_hash") or ""),
        }
    return out


class UserStore:
    """Loads users from an inline JSON blob (env) or a JSON file on disk."""

    def __init__(self, path: str | Path | None, *, users_json: str = "") -> None:
        self.path = Path(path) if path else None
        self._lock = Lock()
        self._inline: dict[str, dict[str, Any]] | None = None
        if users_json:
            try:
                self._inline = _normalize_users(json.loads(users_json))
            except (ValueError, json.JSONDecodeError):
                self._inline = None

    def _read(self) -> dict[str, dict[str, Any]]:
        if self._inline is not None:
            return self._inline
        if self.path and self.path.exists():
            try:
                return _normalize_users(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, ValueError, json.JSONDecodeError):
                return {}
        return {}

    def get(self, username: str) -> dict[str, Any] | None:
        return self._read().get((username or "").strip().lower())

    def verify(self, username: str, password: str) -> str | None:
        """Return the canonical username on success, else None."""
        rec = self.get(username)
        if not rec:
            return None
        if verify_password(password, rec.get("password_hash", "")):
            return rec.get("username")
        return None

    def display_name(self, username: str) -> str:
        rec = self.get(username)
        return (rec or {}).get("display_name") or (username or "").strip()

    def usernames(self) -> list[str]:
        return sorted(self._read().keys())

    # -- mutation (used by scripts/manage_users.py; the file is gitignored) --
    def upsert(self, username: str, password_hash: str, display_name: str = "") -> None:
        if self.path is None:
            raise RuntimeError("UserStore has no file path; cannot write.")
        key = (username or "").strip().lower()
        if not key:
            raise ValueError("username required")
        with self._lock:
            data = self._read()
            data[key] = {
                "username": key,
                "display_name": (display_name or key).strip() or key,
                "password_hash": password_hash,
            }
            self._write(data)

    def remove(self, username: str) -> bool:
        if self.path is None:
            raise RuntimeError("UserStore has no file path; cannot write.")
        key = (username or "").strip().lower()
        with self._lock:
            data = self._read()
            if key not in data:
                return False
            del data[key]
            self._write(data)
            return True

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        assert self.path is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"users": data}, indent=2, sort_keys=True), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Auth configuration (env-driven; off by default so local is unchanged)
# --------------------------------------------------------------------------- #
@dataclass
class AuthConfig:
    enabled: bool
    secret: str
    users_file: str
    users_json: str
    session_ttl_seconds: int
    cookie_secure: bool
    owner_name: str
    machine_api_key: str = ""
    cookie_name: str = DEFAULT_COOKIE_NAME

    @classmethod
    def from_env(cls) -> "AuthConfig":
        enabled = os.environ.get("DASHBOARD_AUTH_ENABLED", "false").strip().lower() == "true"
        try:
            ttl_hours = float(os.environ.get("DASHBOARD_SESSION_TTL_HOURS", "12") or 12)
        except ValueError:
            ttl_hours = 12.0
        return cls(
            enabled=enabled,
            secret=os.environ.get("DASHBOARD_SESSION_SECRET", "").strip(),
            users_file=os.environ.get("DASHBOARD_USERS_FILE", ".local_state/dashboard_users.json").strip(),
            users_json=os.environ.get("DASHBOARD_USERS_JSON", "").strip(),
            session_ttl_seconds=max(300, int(ttl_hours * 3600)),
            cookie_secure=os.environ.get("DASHBOARD_COOKIE_SECURE", "true").strip().lower() != "false",
            owner_name=os.environ.get("DASHBOARD_OWNER_NAME", "Raghu").strip() or "Raghu",
            machine_api_key=os.environ.get("DASHBOARD_MACHINE_API_KEY", "").strip(),
        )

    @property
    def misconfigured(self) -> bool:
        """Enabled but no signing secret -> fail closed rather than run open."""
        return self.enabled and not self.secret


# --------------------------------------------------------------------------- #
# Login page (small self-contained HTML; no external assets)
# --------------------------------------------------------------------------- #
def render_login_html(*, error: bool = False) -> str:
    msg = (
        '<p class="err">Invalid username or password.</p>' if error else ""
    )
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in — Schwab Market Scanner</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         background:#0b0f14; color:#e6edf3; font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif; }}
  .card {{ width:340px; max-width:92vw; background:#131a22; border:1px solid #223; border-radius:14px;
          padding:26px 24px; box-shadow:0 10px 40px rgba(0,0,0,.5); }}
  h1 {{ font-size:17px; margin:0 0 4px; }}
  .sub {{ color:#8aa; font-size:12px; margin:0 0 18px; }}
  label {{ display:block; font-size:12px; color:#9fb; margin:12px 0 5px; }}
  input {{ width:100%; padding:10px 12px; border-radius:9px; border:1px solid #2a3a4a;
           background:#0e141b; color:#e6edf3; font-size:15px; }}
  input:focus {{ outline:none; border-color:#3b82f6; }}
  button {{ width:100%; margin-top:20px; padding:11px; border:0; border-radius:9px; cursor:pointer;
            background:#2563eb; color:#fff; font-size:15px; font-weight:600; }}
  button:hover {{ background:#1d4ed8; }}
  .err {{ background:#3a1620; border:1px solid #7f1d1d; color:#fca5a5; font-size:12px;
          padding:8px 10px; border-radius:8px; margin:0 0 6px; }}
</style></head>
<body>
  <form class="card" method="post" action="/login" autocomplete="off">
    <h1>Schwab Market Scanner</h1>
    <p class="sub">Sign in to continue</p>
    {msg}
    <label for="u">Username</label>
    <input id="u" name="username" autocapitalize="off" autocomplete="username" autofocus required>
    <label for="p">Password</label>
    <input id="p" name="password" type="password" autocomplete="current-password" required>
    <button type="submit">Sign in</button>
  </form>
</body></html>"""
