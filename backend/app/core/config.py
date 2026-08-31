"""
Application configuration using Pydantic Settings
"""
import sys
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

    # Encryption key for secrets-at-rest (Schwab/Claude tokens in user_settings).
    # SEPARATE from SECRET_KEY on purpose: rotating the JWT signing key must not
    # touch the data-encryption key (and vice versa). Provision a durable value
    # with:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # A raw 32-byte urlsafe-base64 Fernet key is used directly; any other string
    # is stretched via PBKDF2. When EMPTY the app falls back to the legacy
    # SECRET_KEY-derived key (v1) for backward-compat during the transition and
    # logs a warning — see app/services/settings.py. New ciphertext is written
    # under this key (v2) only when it is set.
    ENCRYPTION_KEY: str = ""

    # Reverse proxies whose X-Forwarded-For we trust (IPs or CIDRs, comma-sep).
    # Empty (default) = trust NO proxy: XFF is ignored and the direct peer is
    # used for rate-limit identity, so a client can't spoof its rate-limit key.
    # Set this to your Caddy/ingress address(es) when deployed behind a proxy.
    TRUSTED_PROXIES: list[str] | str = []

    # Content-Security-Policy applied to responses (see SecurityHeadersMiddleware).
    # Default is API-appropriate: deny everything (JSON API serves no page assets).
    # Interactive docs (/docs, /redoc) get a relaxed policy in the middleware.
    CONTENT_SECURITY_POLICY: str = (
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
        "form-action 'none'"
    )

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

            # Encourage (but don't yet require) a dedicated ENCRYPTION_KEY in
            # production. Absent it, secrets fall back to the legacy
            # SECRET_KEY-derived key — which couples rotation of the two keys.
            # This is a WARNING (not fatal) so live installs keep booting during
            # the transition; the re-encrypt migration (§3) flips it to required.
            if not self.ENCRYPTION_KEY:
                print(
                    "WARNING: ENCRYPTION_KEY is not set. Secrets-at-rest fall back "
                    "to the legacy SECRET_KEY-derived key; rotating SECRET_KEY will "
                    "then brick stored Schwab/Claude tokens. Set ENCRYPTION_KEY "
                    "(python -c \"from cryptography.fernet import Fernet; "
                    "print(Fernet.generate_key().decode())\").",
                    file=sys.stderr,
                )

            # Check database password (extract from URL)
            if "investing_dev" in self.DATABASE_URL or ":investing@" in self.DATABASE_URL:
                errors.append(
                    "DATABASE_URL contains default development credentials. "
                    "Use strong credentials in production."
                )

            # Check CORS origins
            origins = self.CORS_ORIGINS if isinstance(self.CORS_ORIGINS, list) else [self.CORS_ORIGINS]
            if "*" in origins:
                errors.append(
                    "CORS_ORIGINS must not contain '*' in production. "
                    "Specify explicit origins."
                )
            if any("localhost" in o for o in origins):
                print(
                    "WARNING: CORS_ORIGINS contains localhost origins in production. "
                    "Set CORS_ORIGINS to your production frontend URL.",
                    file=sys.stderr,
                )

            # Check Schwab OAuth URLs (Schwab requires HTTPS callbacks; the
            # frontend URL is used as a 302 redirect target)
            if self.SCHWAB_CALLBACK_URL and not self.SCHWAB_CALLBACK_URL.startswith(
                "https://"
            ):
                errors.append(
                    "SCHWAB_CALLBACK_URL must be an https:// URL in production"
                )
            if not self.FRONTEND_URL.startswith(("http://", "https://")):
                errors.append("FRONTEND_URL must be an http(s):// URL")

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
    CORS_ORIGINS: list[str] | str = ["http://localhost:3000", "http://localhost:3001"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        """Parse CORS_ORIGINS from comma-separated string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @field_validator("TRUSTED_PROXIES", mode="before")
    @classmethod
    def parse_trusted_proxies(cls, v):
        """Parse TRUSTED_PROXIES from comma-separated string or list."""
        if isinstance(v, str):
            return [entry.strip() for entry in v.split(",") if entry.strip()]
        return v

    @field_validator("MASSIVE_ENTITLEMENTS", mode="before")
    @classmethod
    def parse_massive_entitlements(cls, v):
        """Parse MASSIVE_ENTITLEMENTS from a comma-separated string or list.

        Normalizes to lower-case, whitespace-stripped names. **An empty value
        falls back to the full default set** rather than to "nothing entitled":
        ``MASSIVE_ENTITLEMENTS=`` is what a copied ``.env.example`` looks like,
        and silently disabling every Massive surface on a blank line would be
        exactly the invisible capability loss this declaration exists to
        prevent. "Nothing" is spelled by clearing ``POLYGON_API_KEY``.

        Unknown names are *not* rejected here — the surface vocabulary belongs
        to the provider layer, which validates them and logs loudly (importing
        ``ProviderCapability`` into core config would be a circular import).
        """
        if isinstance(v, str):
            v = [entry.strip() for entry in v.split(",") if entry.strip()]
        if isinstance(v, (list, tuple, set, frozenset)):
            names = [str(entry).strip().lower() for entry in v if str(entry).strip()]
            return names or ["quote", "history", "fundamentals", "search"]
        return v

    # Authentication
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    # Closed by default: this is a single-user, self-hosted app (see AGENTS.md
    # non-goals). Open it explicitly to onboard the first account, then leave it
    # false. The login page already gates its Register link on this via
    # /auth/registration-status.
    REGISTRATION_ENABLED: bool = False
    DEMO_MODE: bool = False  # Set to True for public demo deployment

    # External APIs
    ALPHA_VANTAGE_API_KEY: str = ""
    # Massive (formerly Polygon.io). Keeps the POLYGON_ spelling so existing
    # deployments keep working across the rebrand. Key-gated: when empty,
    # ``get_quote_provider()`` never builds the provider and the free chain is
    # exactly what it always was.
    #
    # Setting it PROMOTES Massive to primary on every surface — quote, history,
    # fundamentals, search — with the free chain (Yahoo -> Stooq -> Alpha
    # Vantage) behind it. Starter-plan quotes are 15 minutes delayed; that is
    # made honest by the label the UI renders, not by demoting the feed. See
    # app/services/data_providers/__init__.py for the election and
    # app/services/data_providers/massive.py for the provider.
    POLYGON_API_KEY: str = ""
    # Which Massive products the key above actually holds, comma-separated, in
    # the app's own surface vocabulary: quote, history, fundamentals, search.
    # Massive sells these as separate products (a plan can include stock
    # aggregates but not Stocks Financials), and the app has no way to ask —
    # so it is declared here rather than discovered one 403 at a time.
    #
    # A surface left out of this list is treated exactly like a provider
    # failure: the call never leaves the process and the request falls through
    # to the next provider in the chain (Yahoo), instead of returning an empty
    # result that is indistinguishable from "this ticker has no data".
    #
    # UNSET or EMPTY means "not declared" and entitles every surface — i.e. the
    # historical behaviour, where reality is discovered from 403s at runtime.
    # To turn Massive off entirely, clear POLYGON_API_KEY; that is the key gate
    # and it is the only way to declare "nothing". The runtime 403 handler stays
    # as the backstop and corrects a wrong declaration loudly
    # (see app/services/data_providers/massive.py).
    MASSIVE_ENTITLEMENTS: list[str] | str = [
        "quote",
        "history",
        "fundamentals",
        "search",
    ]
    FINNHUB_API_KEY: str = ""
    # FRED (St. Louis Fed) — free API key gating the live macro-release calendar
    # (CPI/NFP/GDP/PCE). Get one at https://fredaccount.stlouisfed.org/apikeys.
    # When empty, the macro-calendar seeder falls back to its hand-maintained
    # date lists so the calendar never runs dry (see scripts/seed_macro_events.py).
    FRED_API_KEY: str = ""
    DISCORD_WEBHOOK_URL: str = ""

    # Schwab (opt-in OAuth integration; never required). Connecting Schwab is
    # an INGESTION integration: brokerage transactions and positions, which no
    # market-data vendor can supply. See SCHWAB_QUOTES_ENABLED below for its
    # (now separate, default-off) quote role.
    SCHWAB_APP_KEY: str = ""
    SCHWAB_APP_SECRET: str = ""
    # Must exactly match the callback URL registered with the Schwab developer
    # portal, e.g. https://your-host/api/v1/schwab/callback
    SCHWAB_CALLBACK_URL: str = ""
    # Where the OAuth callback redirects the browser after the token exchange
    FRONTEND_URL: str = "http://localhost:3000"
    # Opt-in, DEFAULT OFF: also use the Schwab connection as the extended-hours
    # (pre/post-market) QUOTE provider for briefings.
    #
    # Schwab's two roles are deliberately decoupled (#273). Ingestion is the one
    # thing only Schwab can do and is always on when connected. Quotes are not:
    # Yahoo already serves pre/post-market data everywhere this flag reaches,
    # and futures/forex/indices never routed through Schwab in the first place
    # (``_SCHWAB_SYMBOL_RE`` delegates them per-symbol). Leaving the quote role
    # on means an expired refresh token — which Schwab hard-caps at 7 days with
    # no way to extend — has a blast radius over prices it has no business
    # having.
    #
    # WHAT IT REACHES: the flag governs one thing — which provider
    # ``get_extended_quote_provider`` returns — and that selector has exactly
    # three consumers, all of which this flag therefore moves between Schwab
    # and Yahoo:
    #   1. the briefing extended-hours movers (``tasks/alerts.py``, morning
    #      pulse + EOD wrap, via ``collect_extended_movers``);
    #   2. the strategy brief's extended-hours quote block
    #      (``services/agents/strategy_brief.py``, up to MAX_QUOTE_SYMBOLS=30
    #      symbols, which consumes ``price`` and not just ``session``);
    #   3. ``scripts/premarket_pulse.py``, the morning-brief market block.
    # Ingestion (``schwab_ingestion.get_connected_provider``) is not a consumer
    # and never consults this flag.
    #
    # Set to true only if you specifically want Schwab's real-time all-session
    # equity/ETF quotes and accept the weekly re-authorization that keeps them
    # alive. Flipping it is reversible and touches nothing but those three
    # extended-quote surfaces; ingestion is unaffected either way.
    SCHWAB_QUOTES_ENABLED: bool = False

    # AI (fallback, users provide their own)
    CLAUDE_API_KEY: str = ""
    # Default Claude model for in-app analysis. Configurable so the default is
    # never hardcoded to an id that can go EOL; must be one of AIModel's values.
    AI_DEFAULT_MODEL: str = "claude-sonnet-5"
    # Redis response-cache TTL for AI analyses (seconds); 0 disables the cache.
    AI_RESPONSE_CACHE_TTL: int = 3600
    # Per-user, per-day token ceiling (input+output) for in-app AI. Fails closed
    # when exceeded (429 to the caller). 0 disables the budget.
    AI_DAILY_TOKEN_BUDGET: int = 1_000_000

    # Context pack outbox (advisor bridge). When set, the app can publish the
    # context pack to this directory; a host-side rclone job syncs it to a
    # private Google Drive folder the claude.ai "IC Advisor" Project reads. The
    # app never holds Google credentials. Empty = feature disabled.
    CONTEXT_PACK_OUTBOX_DIR: str = ""
    CONTEXT_PACK_HISTORY_RETENTION_DAYS: int = 30
    # Optional source dir for the advisor contract docs (handoff-schema.md,
    # advisor-actions.md). When set, they are copied into <outbox>/reference/ on
    # publish so the Drive folder carries the contract beside latest.md.
    CONTEXT_PACK_REFERENCE_DIR: str = ""

    # Cache TTLs (seconds)
    QUOTE_CACHE_TTL: int = 900  # 15 minutes
    FUNDAMENTALS_CACHE_TTL: int = 86400  # 24 hours
    HISTORY_CACHE_TTL: int = 3600  # 1 hour

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


settings = Settings()
