"""Rate limiting utilities using Redis."""

import hashlib
from typing import Optional

import redis.asyncio as redis
from fastapi import HTTPException, Request, status

from app.core.config import settings


class RateLimiter:
    """Token bucket rate limiter using Redis.

    Implements a simple rate limiting strategy for protecting
    authentication endpoints from brute force attacks.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        prefix: str = "ratelimit",
    ):
        self.redis = redis_client
        self.prefix = prefix

    def _get_key(self, identifier: str, action: str) -> str:
        """Generate a rate limit key."""
        # Hash the identifier to avoid storing raw IPs/emails
        hashed = hashlib.sha256(identifier.encode()).hexdigest()[:16]
        return f"{self.prefix}:{action}:{hashed}"

    async def is_rate_limited(
        self,
        identifier: str,
        action: str,
        max_attempts: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        """Check if an identifier is rate limited.

        Args:
            identifier: The identifier to rate limit (e.g., IP address, email)
            action: The action being rate limited (e.g., "login", "register")
            max_attempts: Maximum attempts allowed in the window
            window_seconds: Time window in seconds

        Returns:
            Tuple of (is_limited: bool, remaining_attempts: int)
        """
        key = self._get_key(identifier, action)

        # Get current count
        current = await self.redis.get(key)

        if current is None:
            # First attempt - set with expiry
            await self.redis.setex(key, window_seconds, 1)
            return False, max_attempts - 1

        count = int(current)
        if count >= max_attempts:
            # Get TTL for retry-after
            ttl = await self.redis.ttl(key)
            return True, 0

        # Increment count
        await self.redis.incr(key)
        return False, max_attempts - count - 1

    async def reset(self, identifier: str, action: str) -> None:
        """Reset rate limit for an identifier (e.g., after successful login)."""
        key = self._get_key(identifier, action)
        await self.redis.delete(key)


# Singleton rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


async def get_rate_limiter() -> RateLimiter:
    """Get or create the rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        redis_client = redis.from_url(settings.REDIS_URL)
        _rate_limiter = RateLimiter(redis_client)
    return _rate_limiter


async def check_login_rate_limit(
    request: Request,
    email: Optional[str] = None,
) -> None:
    """Check rate limit for login attempts.

    Rate limits by:
    - IP address: 20 attempts per 15 minutes
    - Email address: 5 attempts per 15 minutes (if provided)

    Raises HTTPException 429 if rate limited.
    """
    rate_limiter = await get_rate_limiter()

    # Get client IP
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    elif request.client:
        client_ip = request.client.host
    else:
        client_ip = "unknown"

    # Check IP rate limit (more lenient - 20 attempts per 15 min)
    ip_limited, ip_remaining = await rate_limiter.is_rate_limited(
        identifier=client_ip,
        action="login_ip",
        max_attempts=20,
        window_seconds=900,  # 15 minutes
    )

    if ip_limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts from this IP. Please try again later.",
            headers={"Retry-After": "900"},
        )

    # Check email rate limit if provided (stricter - 5 attempts per 15 min)
    if email:
        email_limited, email_remaining = await rate_limiter.is_rate_limited(
            identifier=email.lower(),
            action="login_email",
            max_attempts=5,
            window_seconds=900,  # 15 minutes
        )

        if email_limited:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many login attempts for this account. Please try again later.",
                headers={"Retry-After": "900"},
            )


async def reset_login_rate_limit(request: Request, email: str) -> None:
    """Reset login rate limit after successful authentication."""
    rate_limiter = await get_rate_limiter()

    # Reset email-based limit
    await rate_limiter.reset(email.lower(), "login_email")
