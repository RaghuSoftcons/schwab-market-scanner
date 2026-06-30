from datetime import UTC, datetime, timedelta

from market_scanner.config import load_settings
from nt_schwab_bridge.config import SchwabConfig
from nt_schwab_bridge.schwab_adapter import SchwabOAuthManager


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.get_calls = []
        self.post_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url, headers=None):
        self.get_calls.append({"url": url, "headers": dict(headers or {})})
        return self.response

    def post(self, *args, **kwargs):
        self.post_calls.append({"args": args, "kwargs": kwargs})
        raise AssertionError("scanner consumer must not call Schwab token refresh")


def test_schwab_oauth_manager_uses_token_authority_without_refreshing():
    expires_at = (datetime.now(UTC) + timedelta(minutes=20)).replace(microsecond=0).isoformat()
    fake_client = _FakeClient(
        _FakeResponse(
            payload={
                "success": True,
                "access_token": "authority-access-token",
                "access_token_expires_at": expires_at,
                "token_type": "Bearer",
            }
        )
    )
    manager = SchwabOAuthManager(
        SchwabConfig(
            token_authority_url="https://token-authority.example/schwab/token",
            token_authority_api_key="authority-key",
            auto_refresh_enabled=False,
            refresh_token="stale-refresh-token-that-must-not-be-used",
            client_id="client-id-that-must-not-be-used",
            client_secret="client-secret-that-must-not-be-used",
        ),
        http_client_factory=lambda: fake_client,
    )

    assert manager.get_access_token() == "authority-access-token"
    assert fake_client.get_calls == [
        {
            "url": "https://token-authority.example/schwab/token",
            "headers": {"Accept": "application/json", "X-API-Key": "authority-key"},
        }
    ]
    assert fake_client.post_calls == []


def test_scanner_load_settings_reads_token_authority_env(monkeypatch):
    monkeypatch.setenv("SCHWAB_MARKET_DATA_ENABLED", "true")
    monkeypatch.setenv("SCHWAB_AUTO_REFRESH_ENABLED", "false")
    monkeypatch.setenv("SCHWAB_TOKEN_AUTHORITY_URL", "https://token-authority.example/schwab/token")
    monkeypatch.setenv("SCHWAB_TOKEN_AUTHORITY_API_KEY", "authority-key")
    monkeypatch.setenv("SCHWAB_TOKEN_AUTHORITY_CACHE_SECONDS", "45")

    settings = load_settings().settings

    assert settings.schwab.market_data_enabled is True
    assert settings.schwab.auto_refresh_enabled is False
    assert settings.schwab.token_authority_url == "https://token-authority.example/schwab/token"
    assert settings.schwab.token_authority_api_key == "authority-key"
    assert settings.schwab.token_authority_cache_seconds == 45