"""API token lifecycle: mint, authenticate, revoke.

Token format: ``ict_<prefix>_<secret>``

* ``prefix`` - 8 random hex characters, stored in clear as the token's
  non-secret identifier (lookup / listing / revocation);
* ``secret`` - 32 random bytes, URL-safe base64; never stored.

Only ``sha256(full token)`` is persisted. Hashing is plain SHA-256 - the secret
has 256 bits of entropy, so a slow password hash buys nothing - and is not keyed
by ``SECRET_KEY``, so tokens are independent of it.

The plaintext token is returned from ``create`` exactly once and is never
logged, stored, or placed in an exception message by this module.
"""

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_token_access import API_TOKEN_PREFIX, KNOWN_SCOPES
from app.db.models.api_token import ApiToken

logger = logging.getLogger(__name__)

_PREFIX_HEX_CHARS = 8
_SECRET_BYTES = 32


class InvalidScopeError(ValueError):
    """Raised when a token is requested with a scope that does not exist."""


def hash_api_token(token: str) -> str:
    """Hex SHA-256 of a plaintext token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_api_token() -> tuple[str, str]:
    """Return (plaintext token, non-secret prefix)."""
    prefix = secrets.token_hex(_PREFIX_HEX_CHARS // 2)
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    return f"{API_TOKEN_PREFIX}{prefix}_{secret}", prefix


def parse_api_token_prefix(token: str) -> str | None:
    """Extract the identifier from a token, or None if it is malformed."""
    if not token.startswith(API_TOKEN_PREFIX):
        return None
    body = token[len(API_TOKEN_PREFIX):]
    prefix, sep, secret = body.partition("_")
    if (
        not sep
        or not secret
        or len(prefix) != _PREFIX_HEX_CHARS
        or any(c not in "0123456789abcdef" for c in prefix)
    ):
        return None
    return prefix


class ApiTokenService:
    """Database operations for API tokens."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        user_id: uuid.UUID,
        name: str,
        scopes: list[str],
        expires_at: datetime | None = None,
    ) -> tuple[ApiToken, str]:
        """Mint a token. Returns (row, plaintext); the plaintext is not kept."""
        unknown = sorted(set(scopes) - KNOWN_SCOPES)
        if unknown:
            raise InvalidScopeError(f"Unknown scope(s): {', '.join(unknown)}")
        if not scopes:
            raise InvalidScopeError("At least one scope is required")

        plaintext, prefix = generate_api_token()
        row = ApiToken(
            user_id=user_id,
            name=name,
            token_prefix=prefix,
            token_hash=hash_api_token(plaintext),
            scopes=sorted(set(scopes)),
            expires_at=expires_at,
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        logger.info(
            "API token minted id=%s prefix=%s user_id=%s scopes=%s",
            row.id, row.token_prefix, row.user_id, ",".join(row.scopes),
        )
        return row, plaintext

    async def authenticate(self, token: str) -> ApiToken | None:
        """Return the live token row for a plaintext token, else None.

        None covers unknown, malformed, wrong-secret, revoked and expired tokens
        alike. The hash comparison is constant-time. On success
        ``last_used_at`` is stamped and committed.
        """
        prefix = parse_api_token_prefix(token)
        if prefix is None:
            return None

        row = await self.get_by_prefix(prefix)
        if row is None:
            return None
        if not hmac.compare_digest(row.token_hash, hash_api_token(token)):
            logger.warning("API token rejected: hash mismatch prefix=%s", prefix)
            return None

        now = datetime.now(timezone.utc)
        if row.revoked_at is not None:
            logger.warning("API token rejected: revoked id=%s prefix=%s", row.id, prefix)
            return None
        if row.expires_at is not None and row.expires_at <= now:
            logger.warning("API token rejected: expired id=%s prefix=%s", row.id, prefix)
            return None

        row.last_used_at = now
        await self.db.commit()
        return row

    async def get_by_prefix(self, prefix: str) -> ApiToken | None:
        result = await self.db.execute(
            select(ApiToken).where(ApiToken.token_prefix == prefix)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, token_id: uuid.UUID) -> ApiToken | None:
        result = await self.db.execute(select(ApiToken).where(ApiToken.id == token_id))
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[ApiToken]:
        result = await self.db.execute(
            select(ApiToken)
            .where(ApiToken.user_id == user_id)
            .order_by(ApiToken.created_at)
        )
        return list(result.scalars().all())

    async def revoke(self, row: ApiToken) -> ApiToken:
        """Revoke a token (idempotent; the first revocation time is kept)."""
        if row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
            await self.db.commit()
            logger.info("API token revoked id=%s prefix=%s", row.id, row.token_prefix)
        return row
