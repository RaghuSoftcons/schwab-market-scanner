# ============================================================================
# File:          test_auth.py
# Project:       Schwab Market Scanner
# Created:       2026-07-01 (EST)
# Author:        Claude (Anthropic) + Raghu
# Purpose:       Unit tests for the dashboard auth module ported from nt-bridge-v2
#                (password hashing, signed sessions, user store, machine key).
#                The full login-flow (middleware/redirect/cookie) mirrors
#                nt-bridge-v2 where it is TestClient-tested; here the app is a
#                module-level singleton so flow tests are covered manually + there.
# ============================================================================
import json
import time

from nt_schwab_bridge.auth import (
    AuthConfig,
    UserStore,
    hash_password,
    sign_session,
    verify_machine_key,
    verify_password,
    verify_session,
)


def test_password_hash_roundtrip():
    stored = hash_password("scanner-pass-1")
    assert stored.startswith("pbkdf2_sha256$")
    assert verify_password("scanner-pass-1", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("x", "garbage")


def test_password_salted_unique():
    assert hash_password("same") != hash_password("same")


def test_session_roundtrip_and_tamper():
    tok = sign_session("vara", "secret", ttl_seconds=3600)
    assert verify_session(tok, "secret") == "vara"
    assert verify_session(tok, "other") is None
    body, _, sig = tok.partition(".")
    assert verify_session(body + "." + sig[:-2] + "xx", "secret") is None


def test_session_expiry():
    past = int(time.time()) - 7200
    assert verify_session(sign_session("v", "s", ttl_seconds=3600, issued_at=past), "s") is None


def test_userstore_inline_and_case_insensitive():
    users = {"users": {
        "vara": {"display_name": "Vara", "password_hash": hash_password("varapass1")},
        "dhanu": {"display_name": "Dhanu", "password_hash": hash_password("dhanupass1")},
    }}
    store = UserStore(None, users_json=json.dumps(users))
    assert store.verify("vara", "varapass1") == "vara"
    assert store.verify("VARA", "varapass1") == "vara"
    assert store.verify("vara", "nope") is None
    assert set(store.usernames()) == {"vara", "dhanu"}
    assert store.display_name("dhanu") == "Dhanu"


def test_userstore_file_roundtrip(tmp_path):
    p = tmp_path / "users.json"
    s = UserStore(p)
    s.upsert("raghu", hash_password("ownerpass1"), display_name="Raghu")
    assert UserStore(p).verify("raghu", "ownerpass1") == "raghu"
    assert UserStore(p).remove("raghu") is True
    assert UserStore(p).verify("raghu", "ownerpass1") is None


def test_machine_key_constant_time():
    assert verify_machine_key("abc", "abc")
    assert not verify_machine_key("abc", "abd")
    assert not verify_machine_key("", "abc")
    assert not verify_machine_key("abc", "")


def test_auth_config_from_env_defaults(monkeypatch):
    for k in ("DASHBOARD_AUTH_ENABLED", "DASHBOARD_SESSION_SECRET", "DASHBOARD_USERS_JSON"):
        monkeypatch.delenv(k, raising=False)
    cfg = AuthConfig.from_env()
    assert cfg.enabled is False
    assert cfg.misconfigured is False
    monkeypatch.setenv("DASHBOARD_AUTH_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "")
    assert AuthConfig.from_env().misconfigured is True  # enabled w/o secret -> fail closed
