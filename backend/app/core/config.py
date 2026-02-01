"""
Application configuration using Pydantic Settings
"""
import sys
from typing import List, Union
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Insecure defaults that must not be used in production
_INSECURE_SECRET_KEYS = {
    "dev-secret-key-change-in-production",
    "changeme",
    "secret",
    "password",
    "",
}


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # Ignore extra env vars not defined in Settings
    )

    # Application
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = "dev-secret-key-change-in-production"

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        """Validate that production has secure configuration."""
        if self.ENVIRONMENT == "production":
            errors = []

            # Check SECRET_KEY
            if self.SECRET_KEY in _INSECURE_SECRET_KEYS:
                errors.append(
                    "SECRET_KEY must be set to a secure value in production. "
                    "Generate with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
                )
            if len(self.SECRET_KEY) < 32:
                errors.append("SECRET_KEY must be at least 32 characters in production")

            # Check database password (extract from URL)
            if "investing_dev" in self.DATABASE_URL or ":investing@" in self.DATABASE_URL:
                errors.append(
                    "DATABASE_URL contains default development credentials. "
                    "Use strong credentials in production."
                )

            if errors:
                print("\n" + "=" * 60, file=sys.stderr)
                print("FATAL: Production configuration validation failed!", file=sys.stderr)
                print("=" * 60, file=sys.stderr)
                for error in errors:
                    print(f"  - {error}", file=sys.stderr)
                print("=" * 60 + "\n", file=sys.stderr)
                sys.exit(1)

        return self

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://investing:investing_dev@localhost:5432/investing_companion"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # CORS
    CORS_ORIGINS: Union[List[str], str] = ["http://localhost:3000", "http://localhost:3001"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        """Parse CORS_ORIGINS from comma-separated string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # Authentication
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    REGISTRATION_ENABLED: bool = True  # Set to False for single-user mode

    # External APIs
    ALPHA_VANTAGE_API_KEY: str = ""
    POLYGON_API_KEY: str = ""
    DISCORD_WEBHOOK_URL: str = ""

    # AI (fallback, users provide their own)
    CLAUDE_API_KEY: str = ""

    # Cache TTLs (seconds)
    QUOTE_CACHE_TTL: int = 900  # 15 minutes
    FUNDAMENTALS_CACHE_TTL: int = 86400  # 24 hours
    HISTORY_CACHE_TTL: int = 3600  # 1 hour

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


settings = Settings()
