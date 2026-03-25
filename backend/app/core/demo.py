"""Demo mode utilities and constants."""

from app.core.config import settings


def is_demo_mode() -> bool:
    """Check if the application is running in demo mode."""
    return settings.DEMO_MODE


DEMO_USER = {
    "email": "demo@example.com",
    "password": "demo1234!",
}

DEMO_REPO_URL = "https://github.com/smithadifd/investing_companion"

DEMO_BLOCKED_MESSAGE = "This action is disabled in demo mode."
