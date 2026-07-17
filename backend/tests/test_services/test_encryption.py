"""Secrets-at-rest encryption: the versioned, non-bricking scheme.

These tests are the load-bearing proof for the S8 crypto change. They run
without a database — SettingsService's cipher construction touches only config,
not the session — so they exercise pure encrypt/decrypt behavior.

The single most important property: introducing a dedicated ENCRYPTION_KEY must
NOT make any previously-stored ciphertext undecryptable. Old ciphertext
(unversioned or v1) must keep decrypting under the new code and the new key.
"""

import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.core.config import settings as app_settings
from app.services.settings import SettingsService

SECRET = "unit-test-secret-key-at-least-32-chars-long!!"


def _legacy_fernet(secret: str) -> Fernet:
    """Reproduce EXACTLY what the original code did (PBKDF2 + static salt)."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"investing_companion_salt",
        iterations=100000,
    )
    return Fernet(base64.urlsafe_b64encode(kdf.derive(secret.encode())))


def _service(monkeypatch, *, secret: str = SECRET, encryption_key: str = "") -> SettingsService:
    monkeypatch.setattr(app_settings, "SECRET_KEY", secret)
    monkeypatch.setattr(app_settings, "ENCRYPTION_KEY", encryption_key)
    return SettingsService(db=None)  # db unused by cipher construction


# ---------------------------------------------------------------------------
# THE non-bricking proof
# ---------------------------------------------------------------------------

def test_old_ciphertext_written_by_original_code_still_decrypts(monkeypatch):
    """A raw, UNVERSIONED Fernet token (what the original code wrote) must
    decrypt under the new code — even after a dedicated ENCRYPTION_KEY is set."""
    plaintext = "sk-ant-super-secret-token"
    # Simulate the ORIGINAL code path: legacy Fernet, no version prefix.
    old_ciphertext = _legacy_fernet(SECRET).encrypt(plaintext.encode()).decode()
    assert not old_ciphertext.startswith(("v1:", "v2:"))  # genuinely unversioned

    # New code with a brand-new dedicated ENCRYPTION_KEY provisioned.
    svc = _service(monkeypatch, encryption_key=Fernet.generate_key().decode())
    assert svc._decrypt(old_ciphertext) == plaintext


def test_v1_value_decrypts_after_encryption_key_is_provisioned(monkeypatch):
    """A value encrypted before ENCRYPTION_KEY existed (v1 fallback) must still
    decrypt once ENCRYPTION_KEY is set."""
    plaintext = "discord-webhook-secret"
    # Transition state: no ENCRYPTION_KEY yet -> writes v1 (legacy derivation).
    pre = _service(monkeypatch, encryption_key="")
    v1_value = pre._encrypt(plaintext)
    assert v1_value.startswith("v1:")

    # Post-provisioning: ENCRYPTION_KEY now set. Old v1 value must still read.
    post = _service(monkeypatch, encryption_key=Fernet.generate_key().decode())
    assert post._decrypt(v1_value) == plaintext


def test_v2_round_trips_under_the_new_key(monkeypatch):
    plaintext = "schwab-oauth-token-payload"
    key = Fernet.generate_key().decode()
    svc = _service(monkeypatch, encryption_key=key)

    ciphertext = svc._encrypt(plaintext)
    assert ciphertext.startswith("v2:")
    assert plaintext not in ciphertext
    assert svc._decrypt(ciphertext) == plaintext

    # A fresh service with the SAME key decrypts it too (durable key, not boot-random).
    again = _service(monkeypatch, encryption_key=key)
    assert again._decrypt(ciphertext) == plaintext


# ---------------------------------------------------------------------------
# Write-version behavior + key independence
# ---------------------------------------------------------------------------

def test_writes_v1_when_encryption_key_absent(monkeypatch):
    svc = _service(monkeypatch, encryption_key="")
    assert svc._has_dedicated_key is False
    assert svc._encrypt("x").startswith("v1:")


def test_writes_v2_when_encryption_key_present(monkeypatch):
    svc = _service(monkeypatch, encryption_key=Fernet.generate_key().decode())
    assert svc._has_dedicated_key is True
    assert svc._encrypt("x").startswith("v2:")


def test_v2_is_independent_of_secret_key_rotation(monkeypatch):
    """Rotating SECRET_KEY must NOT brick v2 ciphertext (the whole point of the
    split): decrypt with the same ENCRYPTION_KEY but a rotated SECRET_KEY."""
    plaintext = "token-that-must-survive-jwt-rotation"
    key = Fernet.generate_key().decode()

    before = _service(monkeypatch, secret=SECRET, encryption_key=key)
    ciphertext = before._encrypt(plaintext)

    after = _service(monkeypatch, secret="a-completely-different-rotated-secret-key!!", encryption_key=key)
    assert after._decrypt(ciphertext) == plaintext


def test_v2_ciphertext_not_readable_after_secret_key_rotation_would_have_broken_v1(monkeypatch):
    """Contrast: a v1 value IS coupled to SECRET_KEY (documents why the split
    matters). Rotating SECRET_KEY breaks v1 decryption -> swallowed to a raise."""
    import pytest

    plaintext = "legacy-coupled-token"
    pre = _service(monkeypatch, secret=SECRET, encryption_key="")
    v1_value = pre._encrypt(plaintext)

    rotated = _service(monkeypatch, secret="rotated-secret-key-32-chars-minimum-xx!!", encryption_key="")
    with pytest.raises(Exception):
        rotated._decrypt(v1_value)


def test_encryption_key_accepts_passphrase_not_only_fernet_key(monkeypatch):
    """A non-Fernet-format ENCRYPTION_KEY is stretched deterministically."""
    svc = _service(monkeypatch, encryption_key="just-a-human-chosen-passphrase")
    ct = svc._encrypt("v")
    assert ct.startswith("v2:")
    assert svc._decrypt(ct) == "v"


# ---------------------------------------------------------------------------
# ENCRYPTED_KEYS membership (fix #2)
# ---------------------------------------------------------------------------

def test_discord_webhook_url_is_encrypted_at_rest():
    assert SettingsService.DISCORD_WEBHOOK_URL in SettingsService.ENCRYPTED_KEYS


def test_existing_encrypted_keys_still_present():
    # Backward-compat: S5 reads the AI key through the existing accessor, which
    # depends on CLAUDE_API_KEY staying in ENCRYPTED_KEYS.
    for key in (
        SettingsService.CLAUDE_API_KEY,
        SettingsService.ALPHA_VANTAGE_API_KEY,
        SettingsService.POLYGON_API_KEY,
        SettingsService.SCHWAB_TOKEN,
    ):
        assert key in SettingsService.ENCRYPTED_KEYS
