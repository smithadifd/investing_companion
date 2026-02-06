"""Authentication and user schemas."""

import uuid
from datetime import datetime
from typing import Optional

import re

from pydantic import BaseModel, EmailStr, Field, field_validator

_PASSWORD_PATTERN = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^a-zA-Z\d]).{8,128}$"
)
_PASSWORD_HELP = (
    "Password must be 8-128 characters with at least one uppercase letter, "
    "one lowercase letter, one digit, and one special character"
)


def _validate_password_strength(v: str) -> str:
    if not _PASSWORD_PATTERN.match(v):
        raise ValueError(_PASSWORD_HELP)
    return v


class UserBase(BaseModel):
    """Base user schema with common fields."""

    email: EmailStr


class UserCreate(UserBase):
    """Schema for user registration."""

    password: str = Field(..., min_length=8, max_length=128)
    password_confirm: str = Field(..., min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)

    @field_validator("password_confirm")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("Passwords do not match")
        return v


class UserLogin(BaseModel):
    """Schema for user login."""

    email: EmailStr
    password: str


class UserResponse(UserBase):
    """Schema for user in responses."""

    id: uuid.UUID
    is_active: bool
    is_admin: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    """Schema for updating user profile."""

    email: Optional[EmailStr] = None


class PasswordChange(BaseModel):
    """Schema for changing password."""

    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)
    new_password_confirm: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)

    @field_validator("new_password_confirm")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match")
        return v


class TokenResponse(BaseModel):
    """Response containing access and refresh tokens."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token expiration in seconds")


class TokenRefresh(BaseModel):
    """Schema for refreshing tokens."""

    refresh_token: str


class SessionInfo(BaseModel):
    """Information about an active session."""

    id: uuid.UUID
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    is_current: bool = False

    model_config = {"from_attributes": True}


class UserSettingCreate(BaseModel):
    """Schema for creating/updating a user setting."""

    key: str = Field(..., max_length=100)
    value: Optional[str] = None
    is_encrypted: bool = False
    description: Optional[str] = Field(None, max_length=255)


class UserSettingResponse(BaseModel):
    """Schema for user setting in responses."""

    id: int
    key: str
    value: Optional[str] = None
    is_encrypted: bool
    description: Optional[str] = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserSettingUpdate(BaseModel):
    """Schema for updating a user setting."""

    value: Optional[str] = None
    description: Optional[str] = Field(None, max_length=255)


class AppSettings(BaseModel):
    """Aggregated application settings for the settings page."""

    claude_api_key: Optional[str] = None
    alpha_vantage_api_key: Optional[str] = None
    polygon_api_key: Optional[str] = None
    discord_webhook_url: Optional[str] = None
    default_watchlist_id: Optional[int] = None
    theme: str = "dark"
    morning_notification_time: str = "08:00"
    eod_notification_time: str = "16:30"


class AppSettingsUpdate(BaseModel):
    """Schema for updating application settings."""

    claude_api_key: Optional[str] = None
    alpha_vantage_api_key: Optional[str] = None
    polygon_api_key: Optional[str] = None
    discord_webhook_url: Optional[str] = None
    default_watchlist_id: Optional[int] = None
    theme: Optional[str] = None
    morning_notification_time: Optional[str] = None
    eod_notification_time: Optional[str] = None


class RegistrationStatus(BaseModel):
    """Status of registration availability."""

    enabled: bool
    message: Optional[str] = None
