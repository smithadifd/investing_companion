"""Decrypt failures must be observable, not silent (crypto-path hardening).

If ENCRYPTION_KEY is later dropped/changed, a v2 secret stops decrypting and
callers degrade to None — which looks identical to "the secret was never set."
_decrypt now logs LOUDLY on failure (still re-raising so callers stay fail-safe),
distinguishing a decrypt failure from a genuinely-absent value. DB-free: the
caller path is exercised with a fake async session.
"""

import logging

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings as app_settings
from app.services.settings import SettingsService

SECRET = "unit-test-secret-key-at-least-32-chars-long!!"


def _service(monkeypatch, *, encryption_key="", db=None):
    monkeypatch.setattr(app_settings, "SECRET_KEY", SECRET)
    monkeypatch.setattr(app_settings, "ENCRYPTION_KEY", encryption_key)
    return SettingsService(db=db)


# --- fake async session so get_setting runs without a database ---
class _FakeResult:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _FakeSession:
    def __init__(self, obj):
        self._obj = obj

    async def execute(self, stmt):
        return _FakeResult(self._obj)


class _FakeSetting:
    def __init__(self, value, is_encrypted):
        self.value = value
        self.is_encrypted = is_encrypted


# ---------------------------------------------------------------------------
# _decrypt-level: fires on a tagged-but-undecryptable token
# ---------------------------------------------------------------------------

def test_decrypt_of_tagged_token_logs_error(monkeypatch, caplog):
    svc = _service(monkeypatch, encryption_key=Fernet.generate_key().decode())
    with caplog.at_level(logging.ERROR, logger="app.services.settings"):
        with pytest.raises(InvalidToken):
            svc._decrypt("v2:this-is-not-a-valid-fernet-token")
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "a decrypt failure of a tagged token must log an error"
    msg = errors[0].getMessage()
    assert "DECRYPT FAILURE" in msg
    assert "ENCRYPTION_KEY" in msg
    assert "version=v2" in msg


def test_successful_decrypt_does_not_log(monkeypatch, caplog):
    key = Fernet.generate_key().decode()
    svc = _service(monkeypatch, encryption_key=key)
    ciphertext = svc._encrypt("a-real-secret")
    with caplog.at_level(logging.ERROR, logger="app.services.settings"):
        assert svc._decrypt(ciphertext) == "a-real-secret"
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


def test_decrypt_never_logs_plaintext(monkeypatch, caplog):
    svc = _service(monkeypatch, encryption_key=Fernet.generate_key().decode())
    secret_marker = "SUPERSECRETPLAINTEXTVALUE"
    with caplog.at_level(logging.ERROR, logger="app.services.settings"):
        with pytest.raises(InvalidToken):
            svc._decrypt(f"v2:{secret_marker}")
    for record in caplog.records:
        assert secret_marker not in record.getMessage()


# ---------------------------------------------------------------------------
# Caller-level (get_setting): fires for undecryptable ciphertext, NOT for a
# genuinely-absent value or a legacy-plaintext (unencrypted) row.
# ---------------------------------------------------------------------------

async def test_get_setting_logs_on_undecryptable_ciphertext(monkeypatch, caplog):
    setting = _FakeSetting(value="v2:garbage-ciphertext", is_encrypted=True)
    svc = _service(
        monkeypatch,
        encryption_key=Fernet.generate_key().decode(),
        db=_FakeSession(setting),
    )
    with caplog.at_level(logging.ERROR, logger="app.services.settings"):
        result = await svc.get_setting("SCHWAB_TOKEN")
    assert result is None  # fail-safe preserved
    assert [r for r in caplog.records if r.levelno >= logging.ERROR], (
        "undecryptable stored ciphertext must be logged loudly"
    )


async def test_get_setting_does_not_log_for_legacy_plaintext(monkeypatch, caplog):
    setting = _FakeSetting(value="https://plain.example/webhook", is_encrypted=False)
    svc = _service(monkeypatch, db=_FakeSession(setting))
    with caplog.at_level(logging.ERROR, logger="app.services.settings"):
        result = await svc.get_setting("DISCORD_WEBHOOK_URL")
    assert result == "https://plain.example/webhook"
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


async def test_get_setting_does_not_log_for_absent_value(monkeypatch, caplog):
    svc = _service(monkeypatch, db=_FakeSession(None))
    with caplog.at_level(logging.ERROR, logger="app.services.settings"):
        result = await svc.get_setting("CLAUDE_API_KEY")
    assert result is None
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
