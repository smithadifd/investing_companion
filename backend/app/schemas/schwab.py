"""Schwab connection schemas (opt-in brokerage transaction/position sync)."""


from pydantic import BaseModel


class SchwabStatus(BaseModel):
    """Connection state for the settings page. Never includes token material."""

    configured: bool  # server has SCHWAB_APP_KEY/SECRET/CALLBACK_URL set
    connected: bool  # a valid (non-expired) token is stored
    needs_reconnect: bool = False  # token exists but passed the 7-day expiry
    token_age_days: float | None = None
    expires_in_days: float | None = None
    # Whether this server also opted Schwab into the extended-hours QUOTE role
    # (SCHWAB_QUOTES_ENABLED, default off — see #273). Purely informational:
    # it changes what the settings page can honestly claim connecting does,
    # never what the connection is for. Ingestion does not consult it.
    quotes_enabled: bool = False


class SchwabConnectResponse(BaseModel):
    """Where to send the browser to start the Schwab OAuth login."""

    auth_url: str
