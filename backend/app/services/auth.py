"""Authentication service - password hashing, JWT tokens, session management."""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import argon2
import jwt
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.session import Session
from app.db.models.user import User
from app.schemas.auth import TokenResponse, UserCreate


class AuthService:
    """Service for authentication operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.password_hasher = argon2.PasswordHasher(
            time_cost=2,
            memory_cost=65536,
            parallelism=1,
        )

    def hash_password(self, password: str) -> str:
        """Hash a password using argon2."""
        return self.password_hasher.hash(password)

    def verify_password(self, password: str, password_hash: str) -> bool:
        """Verify a password against its hash."""
        try:
            self.password_hasher.verify(password_hash, password)
            return True
        except argon2.exceptions.VerifyMismatchError:
            return False
        except argon2.exceptions.InvalidHashError:
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        """Check if a password hash needs to be rehashed."""
        return self.password_hasher.check_needs_rehash(password_hash)

    def _hash_token(self, token: str) -> str:
        """Hash a token for storage using SHA-256."""
        return hashlib.sha256(token.encode()).hexdigest()

    def _create_access_token(self, user_id: uuid.UUID) -> Tuple[str, datetime]:
        """Create a JWT access token."""
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
        payload = {
            "sub": str(user_id),
            "exp": expires_at,
            "iat": datetime.now(timezone.utc),
            "type": "access",
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        return token, expires_at

    def _create_refresh_token(self) -> str:
        """Create a secure random refresh token."""
        return secrets.token_urlsafe(32)

    def decode_access_token(self, token: str) -> Optional[uuid.UUID]:
        """Decode and validate a JWT access token, returning user_id if valid."""
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
            if payload.get("type") != "access":
                return None
            user_id = payload.get("sub")
            if user_id:
                return uuid.UUID(user_id)
            return None
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get a user by email address."""
        stmt = select(User).where(User.email == email.lower())
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        """Get a user by ID."""
        stmt = select(User).where(User.id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_user(self, user_data: UserCreate) -> User:
        """Create a new user."""
        password_hash = self.hash_password(user_data.password)
        user = User(
            email=user_data.email.lower(),
            password_hash=password_hash,
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def authenticate(self, email: str, password: str) -> Optional[User]:
        """Authenticate a user by email and password."""
        user = await self.get_user_by_email(email)
        if not user:
            return None
        if not user.is_active:
            return None
        if not self.verify_password(password, user.password_hash):
            return None

        # Rehash password if needed (algorithm parameters changed)
        if self.needs_rehash(user.password_hash):
            user.password_hash = self.hash_password(password)
            await self.db.commit()

        return user

    async def create_session(
        self,
        user: User,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> TokenResponse:
        """Create a new session with access and refresh tokens."""
        # Create tokens
        access_token, access_expires = self._create_access_token(user.id)
        refresh_token = self._create_refresh_token()
        refresh_token_hash = self._hash_token(refresh_token)

        # Calculate refresh token expiration
        refresh_expires = datetime.now(timezone.utc) + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )

        # Create session in database
        session = Session(
            user_id=user.id,
            refresh_token_hash=refresh_token_hash,
            user_agent=user_agent,
            ip_address=ip_address,
            expires_at=refresh_expires,
        )
        self.db.add(session)

        # Update last login time
        user.last_login_at = datetime.now(timezone.utc)

        await self.db.commit()

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def refresh_tokens(
        self,
        refresh_token: str,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Optional[TokenResponse]:
        """Refresh tokens using a valid refresh token."""
        refresh_token_hash = self._hash_token(refresh_token)

        # Find the session
        stmt = (
            select(Session)
            .join(User)
            .where(
                Session.refresh_token_hash == refresh_token_hash,
                Session.revoked_at.is_(None),
                Session.expires_at > datetime.now(timezone.utc),
                User.is_active.is_(True),
            )
        )
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()

        if not session:
            return None

        # Get the user
        user = await self.get_user_by_id(session.user_id)
        if not user:
            return None

        # Revoke old session
        session.revoked_at = datetime.now(timezone.utc)

        # Create new session
        return await self.create_session(user, user_agent, ip_address)

    async def revoke_session(self, refresh_token: str) -> bool:
        """Revoke a session by refresh token."""
        refresh_token_hash = self._hash_token(refresh_token)
        stmt = (
            update(Session)
            .where(
                Session.refresh_token_hash == refresh_token_hash,
                Session.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc))
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount > 0

    async def revoke_all_sessions(self, user_id: uuid.UUID) -> int:
        """Revoke all sessions for a user."""
        stmt = (
            update(Session)
            .where(
                Session.user_id == user_id,
                Session.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc))
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount

    async def get_user_sessions(self, user_id: uuid.UUID) -> list[Session]:
        """Get all active sessions for a user."""
        stmt = (
            select(Session)
            .where(
                Session.user_id == user_id,
                Session.revoked_at.is_(None),
                Session.expires_at > datetime.now(timezone.utc),
            )
            .order_by(Session.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions from the database."""
        stmt = delete(Session).where(
            Session.expires_at < datetime.now(timezone.utc)
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount

    async def change_password(
        self, user: User, current_password: str, new_password: str
    ) -> bool:
        """Change a user's password."""
        if not self.verify_password(current_password, user.password_hash):
            return False

        user.password_hash = self.hash_password(new_password)
        await self.db.commit()

        # Revoke all existing sessions (force re-login)
        await self.revoke_all_sessions(user.id)

        return True

    async def update_email(self, user: User, new_email: str) -> bool:
        """Update a user's email address."""
        # Check if email is already taken
        existing = await self.get_user_by_email(new_email)
        if existing and existing.id != user.id:
            return False

        user.email = new_email.lower()
        await self.db.commit()
        return True
