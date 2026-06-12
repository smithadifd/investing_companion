"""Schwab connection schemas (opt-in real-time quotes)."""

from typing import Optional

from pydantic import BaseModel


class SchwabStatus(BaseModel):
    """Connection state for the settings page. Never includes token material."""

    configured: bool  # server has SCHWAB_APP_KEY/SECRET/CALLBACK_URL set
    connected: bool  # a valid (non-expired) token is stored
    needs_reconnect: bool = False  # token exists but passed the 7-day expiry
    token_age_days: Optional[float] = None
    expires_in_days: Optional[float] = None


class SchwabConnectResponse(BaseModel):
    """Where to send the browser to start the Schwab OAuth login."""

    auth_url: str
