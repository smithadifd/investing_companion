"""Discord webhook notification service."""

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Discord's hard cap on an embed's ``description``. The batched alert embed is
# rendered inside this budget; the caller (AlertService.deliver_pending) chunks
# by DELIVERY_GROUP_LIMIT so the cap is unreachable in practice, and the
# overflow path below states what it left out rather than dropping it silently.
EMBED_DESCRIPTION_LIMIT = 4096

# Per-line cap on the (user-authored, unbounded) alert name, so one pathological
# name cannot crowd every other alert out of a batched embed.
BATCH_LINE_NAME_LIMIT = 60

# Discord markdown-link structural characters, removed from any text
# interpolated into a link LABEL. `[LABEL](URL)` ends its label at the first
# unescaped `]`, and a following `(` opens a new destination — so text carrying
# these characters could close the real link early and retarget the rendered
# hyperlink at an attacker's URL. The destination half is already hardened by
# percent-encoding (``quote(symbol, safe="")``); this closes the display half.
#
# Removal rather than the zero-width-space trick used for mentions in
# catalysts.py / strategy_brief.py: a ZWSP defangs a MULTI-character token
# (`@everyone`, `<@&id>`) by breaking the pattern, but a `]` is a single
# structural delimiter — a ZWSP after it still lets it close the label.
_LINK_LABEL_DELIMITERS = str.maketrans({character: None for character in "[]()"})


class DiscordNotificationService:
    """Service for sending notifications via Discord webhooks."""

    def __init__(self, webhook_url: str | None = None):
        """Initialize the Discord notification service.

        Args:
            webhook_url: Discord webhook URL. Falls back to settings if not provided.
        """
        self._env_webhook_url = webhook_url or settings.DISCORD_WEBHOOK_URL
        self._client: httpx.AsyncClient | None = None
        self._cached_db_url: str | None = None
        self._cache_checked: bool = False

    async def _get_webhook_url(self) -> str | None:
        """Get webhook URL, checking database if not in environment."""
        # If we have an environment URL, use it (takes precedence)
        if self._env_webhook_url:
            return self._env_webhook_url

        # Check database for user setting
        if not self._cache_checked:
            try:
                from sqlalchemy import select
                from app.db.session import AsyncSessionLocal
                from app.db.models.user_settings import UserSetting

                async with AsyncSessionLocal() as session:
                    # Find any Discord webhook setting (single-user app)
                    stmt = select(UserSetting).where(
                        UserSetting.key == "DISCORD_WEBHOOK_URL",
                        UserSetting.value.isnot(None),
                    )
                    result = await session.execute(stmt)
                    setting = result.scalar_one_or_none()

                    if setting and setting.value:
                        # DISCORD_WEBHOOK_URL is an encrypted-at-rest key (see
                        # SettingsService.ENCRYPTED_KEYS); decrypt when the row
                        # is flagged as such. Older rows saved before that
                        # change stay plaintext (is_encrypted=False) and are
                        # used as-is.
                        value = setting.value
                        if setting.is_encrypted:
                            from app.services.settings import SettingsService

                            try:
                                value = SettingsService(session)._decrypt(value)
                            except Exception:
                                logger.warning(
                                    "Failed to decrypt Discord webhook URL from settings"
                                )
                                value = None
                        self._cached_db_url = value
                        if value:
                            logger.info("Discord webhook URL loaded from user settings")

                self._cache_checked = True
            except Exception as e:
                logger.warning(f"Could not load Discord webhook from database: {e}")
                self._cache_checked = True

        return self._cached_db_url

    def clear_cache(self) -> None:
        """Clear the cached webhook URL to force re-reading from database."""
        self._cached_db_url = None
        self._cache_checked = False

    @property
    def is_configured(self) -> bool:
        """Check if Discord webhook is configured (sync check for env only)."""
        return bool(self._env_webhook_url)

    async def is_configured_async(self) -> bool:
        """Check if Discord webhook is configured (async, includes database)."""
        url = await self._get_webhook_url()
        return bool(url)

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _post_webhook(self, webhook_url: str, payload: dict) -> httpx.Response:
        """POST a payload to the Discord webhook, hardened against mention pings.

        Single choke point for all outbound webhook POSTs. Injects
        ``allowed_mentions: {"parse": []}`` into every payload, which tells
        Discord to resolve zero mentions from the message content/embeds into
        actual pings - regardless of what mention-shaped text (``@everyone``,
        ``@here``, ``<@id>``, ``<@&role>``) made it through. This is
        defense-in-depth *underneath* the per-agent text-sanitization layers
        (catalysts.py, strategy_brief.py, trade_journal.py) - it does not
        replace them, it backstops them: even if a sanitizer regression or a
        new untrusted-text path forgot to neutralize mention syntax, Discord
        itself is told never to act on it.

        Any ``allowed_mentions`` key already present in ``payload`` is
        overridden - this helper is the single source of truth for the field.
        """
        hardened_payload = {**payload, "allowed_mentions": {"parse": []}}
        client = await self._get_client()
        return await client.post(webhook_url, json=hardened_payload)

    def _format_price(self, value: Decimal | float) -> str:
        """Format a price value for display."""
        val = float(value)
        if val >= 1000:
            return f"${val:,.2f}"
        elif val >= 1:
            return f"${val:.2f}"
        else:
            return f"${val:.4f}"

    def _format_percent(self, value: Decimal | float) -> str:
        """Format a percentage value for display."""
        val = float(value)
        sign = "+" if val > 0 else ""
        return f"{sign}{val:.2f}%"

    @staticmethod
    def _frontend_base() -> str:
        """The configured frontend origin, or "" when unset.

        Matches the convention in ``app/tasks/schwab.py`` (`_reconnect_link` /
        `_import_link`): read ``settings.FRONTEND_URL``, strip a trailing slash,
        and degrade gracefully rather than emitting a relative URL that would
        render as a dead link inside Discord.
        """
        return (settings.FRONTEND_URL or "").rstrip("/")

    @classmethod
    def _equity_deep_link(cls, symbol: str, is_ratio: bool = False) -> str | None:
        """``{FRONTEND_URL}/equity/{symbol}``, or None when there is no page.

        Returns None for a ratio (the frontend has ``/ratios`` but no per-pair
        route, and a ratio's "symbol" is a ``GLD/SLV`` pair that would forge a
        bogus two-segment path) and when FRONTEND_URL is unset. Callers render
        a plain bold symbol in that case.
        """
        if is_ratio or not symbol:
            return None
        base = cls._frontend_base()
        if not base:
            return None
        return f"{base}/equity/{quote(symbol, safe='')}"

    @staticmethod
    def _safe_link_text(text: str) -> str:
        """Strip markdown-link delimiters from text used as a link LABEL.

        See ``_LINK_LABEL_DELIMITERS``. Applied to the display half of the
        symbol markup; the URL half is hardened separately by percent-encoding
        in ``_equity_deep_link``.
        """
        return text.translate(_LINK_LABEL_DELIMITERS)

    @classmethod
    def _symbol_markup(cls, symbol: str, is_ratio: bool = False) -> str:
        """Bold symbol, wrapped in a Discord markdown link when one exists.

        The label is delimiter-stripped so a symbol can never break out of the
        link boundary and retarget the hyperlink. Both branches are stripped,
        not just the linked one, so the two cannot drift apart. Note the label
        is sanitized but the URL is built from the RAW symbol — the link must
        still point at the real equity page.
        """
        label = cls._safe_link_text(symbol)
        if not label:
            # Nothing survived stripping, so the symbol was only delimiters —
            # not a real ticker. `[](url)` would render as an empty-label link;
            # emit an inert placeholder and no link at all.
            return "**?**"
        url = cls._equity_deep_link(symbol, is_ratio)
        return f"**[{label}]({url})**" if url else f"**{label}**"

    def _get_condition_description(
        self,
        condition_type: str,
        threshold: Decimal | float,
        comparison_period: str | None = None,
    ) -> str:
        """Get human-readable condition description."""
        threshold_str = self._format_price(threshold) if condition_type not in (
            "percent_up", "percent_down", "percent_from_high"
        ) else f"{threshold}%"

        descriptions = {
            "above": f"above {threshold_str}",
            "below": f"below {threshold_str}",
            "crosses_above": f"crossed above {threshold_str}",
            "crosses_below": f"crossed below {threshold_str}",
            "percent_up": f"up {threshold}% in {comparison_period}",
            "percent_down": f"down {threshold}% in {comparison_period}",
            "percent_from_high": f"down {threshold}% from {comparison_period or '1y'} high",
            "entry_zone": "in a tiered entry zone",
        }
        return descriptions.get(condition_type, f"{condition_type} {threshold_str}")

    async def send_alert_notification(
        self,
        alert_name: str,
        target_symbol: str,
        target_name: str,
        condition_type: str,
        threshold_value: Decimal | float,
        current_value: Decimal | float,
        comparison_period: str | None = None,
        is_ratio: bool = False,
        notes: str | None = None,
        condition_override: str | None = None,
    ) -> tuple[bool, str | None]:
        """Send an alert notification to Discord.

        Args:
            alert_name: Name of the alert
            target_symbol: Symbol of the equity or ratio (e.g., "AAPL" or "GLD/SLV")
            target_name: Display name
            condition_type: Type of condition that triggered
            threshold_value: The threshold that was crossed
            current_value: Current value that triggered the alert
            comparison_period: Period for percent change conditions
            is_ratio: Whether this is a ratio alert
            notes: Optional notes to include
            condition_override: Pre-built condition description (entry-zone
                alerts pass the tier name and price band here)

        Returns:
            Tuple of (success, error_message)
        """
        webhook_url = await self._get_webhook_url()
        if not webhook_url:
            return False, "Discord webhook URL not configured"

        try:
            # Build the embed
            condition_desc = condition_override or self._get_condition_description(
                condition_type, threshold_value, comparison_period
            )

            # Color based on condition
            if condition_type == "entry_zone":
                color = 0xF59E0B  # Amber - a buy zone, not a warning
                emoji = "🎯"
            elif condition_type in ("above", "crosses_above", "percent_up"):
                color = 0x00FF00  # Green
                emoji = "🟢"
            else:
                color = 0xFF0000  # Red
                emoji = "🔴"

            target_type = "Ratio" if is_ratio else "Equity"
            current_str = (
                f"{float(current_value):.4f}" if is_ratio else self._format_price(current_value)
            )

            embed = {
                "title": f"{emoji} Alert Triggered: {alert_name}",
                "description": (
                    f"{self._symbol_markup(target_symbol, is_ratio)} "
                    f"({target_name}) is {condition_desc}"
                ),
                "color": color,
                "fields": [
                    {
                        "name": "Current Value",
                        "value": current_str,
                        "inline": True,
                    },
                    {
                        "name": "Threshold",
                        "value": (
                            f"{float(threshold_value):.4f}"
                            if is_ratio
                            else self._format_price(threshold_value)
                        ),
                        "inline": True,
                    },
                    {
                        "name": "Type",
                        "value": target_type,
                        "inline": True,
                    },
                ],
                "timestamp": datetime.utcnow().isoformat(),
                "footer": {
                    "text": "Investing Companion",
                },
            }

            if notes:
                embed["fields"].append({
                    "name": "Notes",
                    "value": notes[:200] + ("..." if len(notes) > 200 else ""),
                    "inline": False,
                })

            payload = {
                "embeds": [embed],
            }

            response = await self._post_webhook(webhook_url, payload)

            if response.status_code == 204:
                logger.info(f"Discord notification sent for alert: {alert_name}")
                return True, None
            else:
                error = f"Discord API returned status {response.status_code}: {response.text}"
                logger.error(error)
                return False, error

        except httpx.TimeoutException:
            error = "Discord notification timed out"
            logger.error(error)
            return False, error
        except Exception as e:
            error = f"Failed to send Discord notification: {str(e)}"
            logger.error(error, exc_info=True)
            return False, error

    @staticmethod
    def _as_decimal(value: Decimal | float | str | None) -> Decimal:
        """Coerce an outbox payload's numeric field to Decimal, never raising.

        Payloads are JSON snapshots taken at enqueue time (Decimals stringified
        by ``AlertService._build_delivery_payload``), so this accepts str as
        well as Decimal/float. A missing or unparseable value degrades to 0
        rather than raising: one malformed row must not poison the whole
        batched send it happens to share a group with.
        """
        if value is None:
            return Decimal(0)
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return Decimal(0)

    def _batch_alert_line(self, alert: dict) -> str:
        """One bullet line for the batched embed.

        Shape (hand-pinned by tests/test_services/test_alert_batching.py)::

            • **[AAPL](https://host/equity/AAPL)** — <name>: <condition> (now <value>)

        Every field is read with ``.get`` and coerced defensively: a batched
        send covers N outbox rows at once, so a single malformed payload must
        degrade its own line, not fail the other N-1 alerts' notification.
        """
        symbol = str(alert.get("target_symbol") or "?")
        is_ratio = bool(alert.get("is_ratio", False))
        name = str(alert.get("alert_name") or "Alert")
        if len(name) > BATCH_LINE_NAME_LIMIT:
            name = name[:BATCH_LINE_NAME_LIMIT] + "…"

        threshold = self._as_decimal(alert.get("threshold_value"))
        current = self._as_decimal(alert.get("current_value"))
        condition_desc = alert.get("condition_override") or (
            self._get_condition_description(
                str(alert.get("condition_type") or ""),
                threshold,
                alert.get("comparison_period"),
            )
        )
        current_str = (
            f"{float(current):.4f}" if is_ratio else self._format_price(current)
        )
        return (
            f"• {self._symbol_markup(symbol, is_ratio)} — "
            f"{name}: {condition_desc} (now {current_str})"
        )

    def _batch_description(self, alerts: list[dict]) -> str:
        """Join the per-alert lines inside Discord's description budget.

        Normal path: every alert gets a line. Overflow path (only reachable if
        a caller ignores ``DELIVERY_GROUP_LIMIT``): keep as many whole lines as
        fit and append a counted "…and N more" line linking the alerts page —
        the leftovers are *stated*, never silently dropped, and the outbox rows
        behind them are still marked delivered exactly once.
        """
        lines = [self._batch_alert_line(alert) for alert in alerts]
        joined = "\n".join(lines)
        if len(joined) <= EMBED_DESCRIPTION_LIMIT:
            return joined

        base = self._frontend_base()
        kept: list[str] = []
        used = 0
        for index, line in enumerate(lines):
            remaining = len(lines) - index
            more_line = f"• …and {remaining} more"
            if base:
                more_line = f"• …and {remaining} more — [see all alerts]({base}/alerts)"
            # +1 for the newline this line would add, + the tail it must leave
            # room for if it turns out to be the last one kept.
            if used + len(line) + 1 + len(more_line) + 1 > EMBED_DESCRIPTION_LIMIT:
                break
            kept.append(line)
            used += len(line) + 1

        dropped = len(lines) - len(kept)
        tail = f"• …and {dropped} more"
        if base:
            tail = f"• …and {dropped} more — [see all alerts]({base}/alerts)"
        logger.warning(
            "Batched alert embed exceeded Discord's description limit; "
            "%d of %d alerts summarized as an overflow line",
            dropped,
            len(lines),
        )
        return "\n".join([*kept, tail])

    async def send_alert_batch(
        self, alerts: list[dict]
    ) -> tuple[bool, str | None]:
        """Send ONE Discord embed covering every alert that tripped in a cycle.

        This is the batched counterpart of ``send_alert_notification``: the
        outbox drain calls it once per claimed group instead of once per row,
        so a broad selloff produces one message with N deep-linked lines
        instead of N webhook posts.

        Args:
            alerts: Outbox payload dicts as snapshotted by
                ``AlertService._build_delivery_payload`` — ``alert_name``,
                ``target_symbol``, ``target_name``, ``condition_type``,
                ``threshold_value``, ``current_value``, and the optional
                ``comparison_period`` / ``is_ratio`` / ``condition_override``.
                Numeric fields may be Decimal, float or str. Line order follows
                list order (the drain claims in ``created_at`` order, so the
                embed reads oldest-trigger-first).

        Interface notes callers must know:
            * ALL-OR-NOTHING. One POST covers the whole list, so the returned
              outcome applies to every member — the drain records the same
              success/failure against each row in the group. Per-line rendering
              is defensive so a single bad payload cannot fail its groupmates.
            * ``notes`` are deliberately NOT rendered (N x 200 chars would blow
              the description budget); the per-line deep link is the route to
              full context. The unbatched single-alert embed still shows them.
            * An empty list is a no-op success — nothing is posted.

        Returns:
            Tuple of (success, error_message)
        """
        if not alerts:
            return True, None

        webhook_url = await self._get_webhook_url()
        if not webhook_url:
            return False, "Discord webhook URL not configured"

        try:
            count = len(alerts)
            embed = {
                "title": f"🔔 {count} Alert{'s' if count != 1 else ''} Triggered",
                "description": self._batch_description(alerts),
                # Blurple, the repo's neutral summary color (movers / EOD /
                # test embeds). A batch mixes bullish and bearish triggers, so
                # the single-alert green/red coding has no honest answer here.
                "color": 0x5865F2,
                "timestamp": datetime.utcnow().isoformat(),
                "footer": {
                    "text": "Investing Companion",
                },
            }

            payload = {"embeds": [embed]}
            response = await self._post_webhook(webhook_url, payload)

            if response.status_code == 204:
                logger.info(f"Discord batched alert notification sent: {count} alerts")
                return True, None
            error = (
                f"Discord API returned status {response.status_code}: "
                f"{response.text}"
            )
            logger.error(error)
            return False, error

        except httpx.TimeoutException:
            error = "Discord batched alert notification timed out"
            logger.error(error)
            return False, error
        except Exception as e:  # noqa: BLE001 - a send error must not crash the drain
            error = f"Failed to send batched alert notification: {str(e)}"
            logger.error(error, exc_info=True)
            return False, error

    async def send_test_notification(self) -> tuple[bool, str | None]:
        """Send a test notification to verify webhook configuration.

        Returns:
            Tuple of (success, error_message)
        """
        webhook_url = await self._get_webhook_url()
        if not webhook_url:
            return False, "Discord webhook URL not configured"

        try:
            embed = {
                "title": "🔔 Test Notification",
                "description": "Your Discord webhook is configured correctly!",
                "color": 0x5865F2,  # Discord blurple
                "fields": [
                    {
                        "name": "Status",
                        "value": "✅ Connected",
                        "inline": True,
                    },
                ],
                "timestamp": datetime.utcnow().isoformat(),
                "footer": {
                    "text": "Investing Companion",
                },
            }

            payload = {
                "embeds": [embed],
            }

            response = await self._post_webhook(webhook_url, payload)

            if response.status_code == 204:
                logger.info("Discord test notification sent successfully")
                return True, None
            else:
                error = f"Discord API returned status {response.status_code}"
                return False, error

        except Exception as e:
            error = f"Failed to send test notification: {str(e)}"
            logger.error(error, exc_info=True)
            return False, error

    async def send_plain_text(
        self,
        message: str,
    ) -> tuple[bool, str | None]:
        """Send a plain-text message to Discord (not an embed).

        Args:
            message: Pre-formatted plain text message (max 2000 chars).

        Returns:
            Tuple of (success, error_message)
        """
        webhook_url = await self._get_webhook_url()
        if not webhook_url:
            return False, "Discord webhook URL not configured"

        try:
            payload = {"content": message}

            response = await self._post_webhook(webhook_url, payload)

            if response.status_code == 204:
                logger.info("Discord plain-text message sent")
                return True, None
            else:
                error = f"Discord API returned status {response.status_code}: {response.text}"
                logger.error(error)
                return False, error

        except httpx.TimeoutException:
            error = "Discord notification timed out"
            logger.error(error)
            return False, error
        except Exception as e:
            error = f"Failed to send Discord message: {str(e)}"
            logger.error(error, exc_info=True)
            return False, error

    async def send_movers_summary(
        self,
        gainers: list[dict],
        losers: list[dict],
        threshold_percent: float,
        total_items: int,
        watchlist_count: int,
    ) -> tuple[bool, str | None]:
        """Send a daily movers summary to Discord.

        Args:
            gainers: List of top gainers with symbol, name, price, change_percent, watchlist_name
            losers: List of top losers with symbol, name, price, change_percent, watchlist_name
            threshold_percent: The threshold used to filter movers
            total_items: Total number of items across all watchlists
            watchlist_count: Number of watchlists

        Returns:
            Tuple of (success, error_message)
        """
        webhook_url = await self._get_webhook_url()
        if not webhook_url:
            return False, "Discord webhook URL not configured"

        # Filter to only those above threshold
        big_gainers = [g for g in gainers if float(g.get("change_percent", 0)) >= threshold_percent]
        big_losers = [loser for loser in losers if float(loser.get("change_percent", 0)) <= -threshold_percent]

        # If no big movers, don't send notification
        total_movers = len(big_gainers) + len(big_losers)
        if total_movers == 0:
            logger.info(f"No movers above {threshold_percent}% threshold, skipping notification")
            return True, None

        try:
            today = datetime.utcnow().strftime("%b %d, %Y")
            fields = []

            # Gainers section
            if big_gainers:
                gainers_text = "\n".join(
                    f"• **{g['symbol']}** {self._format_percent(g['change_percent'])} ({self._format_price(g['price'])}) - {g.get('watchlist_name', 'Watchlist')}"
                    for g in big_gainers[:5]
                )
                fields.append({
                    "name": f"🚀 Big Gainers (>{threshold_percent}%)",
                    "value": gainers_text,
                    "inline": False,
                })

            # Losers section
            if big_losers:
                losers_text = "\n".join(
                    f"• **{loser['symbol']}** {self._format_percent(loser['change_percent'])} ({self._format_price(loser['price'])}) - {loser.get('watchlist_name', 'Watchlist')}"
                    for loser in big_losers[:5]
                )
                fields.append({
                    "name": f"📉 Big Losers (<-{threshold_percent}%)",
                    "value": losers_text,
                    "inline": False,
                })

            # Summary
            fields.append({
                "name": "📈 Summary",
                "value": f"{total_movers} of {total_items} equities moved >{threshold_percent}% across {watchlist_count} watchlist{'s' if watchlist_count != 1 else ''}",
                "inline": False,
            })

            embed = {
                "title": f"📊 Daily Movers Summary - {today}",
                "color": 0x5865F2,  # Discord blurple
                "fields": fields,
                "timestamp": datetime.utcnow().isoformat(),
                "footer": {
                    "text": "Investing Companion",
                },
            }

            payload = {"embeds": [embed]}

            response = await self._post_webhook(webhook_url, payload)

            if response.status_code == 204:
                logger.info(f"Discord movers summary sent: {len(big_gainers)} gainers, {len(big_losers)} losers")
                return True, None
            else:
                return False, f"Discord API returned status {response.status_code}"

        except Exception as e:
            error = f"Failed to send movers summary: {str(e)}"
            logger.error(error, exc_info=True)
            return False, error

    async def send_upcoming_events(
        self,
        events: list[dict],
        days_label: str = "Today & Tomorrow",
    ) -> tuple[bool, str | None]:
        """Send an upcoming events notification to Discord.

        Args:
            events: List of events with event_date, title, event_type, symbol (optional)
            days_label: Label for the time period (e.g., "Today", "This Week")

        Returns:
            Tuple of (success, error_message)
        """
        webhook_url = await self._get_webhook_url()
        if not webhook_url:
            return False, "Discord webhook URL not configured"

        if not events:
            logger.info("No upcoming events to send")
            return True, None

        try:
            # Group by date
            events_by_date: dict[str, list[dict]] = {}
            for event in events:
                date_str = event.get("event_date", "Unknown")
                if date_str not in events_by_date:
                    events_by_date[date_str] = []
                events_by_date[date_str].append(event)

            fields = []
            event_type_icons = {
                "earnings": "💰",
                "ex_dividend": "💵",
                "dividend_pay": "💵",
                "fomc": "🏛️",
                "cpi": "📊",
                "ppi": "📊",
                "nfp": "👔",
                "gdp": "📈",
            }

            for date_str in sorted(events_by_date.keys()):
                date_events = events_by_date[date_str]
                try:
                    from datetime import datetime as dt
                    date_obj = dt.strptime(date_str, "%Y-%m-%d")
                    formatted_date = date_obj.strftime("%a, %b %d")
                except Exception:
                    formatted_date = date_str

                event_lines = []
                for evt in date_events[:8]:  # Max 8 per day
                    icon = event_type_icons.get(evt.get("event_type", ""), "📅")
                    symbol = evt.get("symbol")
                    title = evt.get("title", "Event")
                    time_str = evt.get("event_time", "")
                    time_part = f" at {time_str}" if time_str else ""

                    if symbol:
                        event_lines.append(f"{icon} **{symbol}**: {title}{time_part}")
                    else:
                        event_lines.append(f"{icon} {title}{time_part}")

                if date_events and len(date_events) > 8:
                    event_lines.append(f"... and {len(date_events) - 8} more")

                fields.append({
                    "name": formatted_date,
                    "value": "\n".join(event_lines) or "No events",
                    "inline": False,
                })

            embed = {
                "title": f"📅 Upcoming Events - {days_label}",
                "color": 0x5865F2,  # Discord blurple
                "fields": fields[:6],  # Max 6 date sections
                "timestamp": datetime.utcnow().isoformat(),
                "footer": {
                    "text": "Investing Companion",
                },
            }

            payload = {"embeds": [embed]}

            response = await self._post_webhook(webhook_url, payload)

            if response.status_code == 204:
                logger.info(f"Discord upcoming events sent: {len(events)} events")
                return True, None
            else:
                return False, f"Discord API returned status {response.status_code}"

        except Exception as e:
            error = f"Failed to send upcoming events: {str(e)}"
            logger.error(error, exc_info=True)
            return False, error

    async def send_end_of_day_summary(
        self,
        gainers: list[dict],
        losers: list[dict],
        threshold_percent: float,
        total_items: int,
        watchlist_count: int,
        alerts_triggered: int,
        active_alerts: int,
        top_triggers: list[dict],
    ) -> tuple[bool, str | None]:
        """Send combined end-of-day summary: movers + alert activity.

        Returns:
            Tuple of (success, error_message)
        """
        webhook_url = await self._get_webhook_url()
        if not webhook_url:
            return False, "Discord webhook URL not configured"

        try:
            today = datetime.utcnow().strftime("%b %d, %Y")
            fields = []

            # --- Movers section ---
            big_gainers = [g for g in gainers if float(g.get("change_percent", 0)) >= threshold_percent]
            big_losers = [loser for loser in losers if float(loser.get("change_percent", 0)) <= -threshold_percent]

            if big_gainers:
                gainers_text = "\n".join(
                    f"• **{g['symbol']}** {self._format_percent(g['change_percent'])} ({self._format_price(g['price'])})"
                    for g in big_gainers[:5]
                )
                fields.append({
                    "name": f"Big Gainers (>{threshold_percent}%)",
                    "value": gainers_text,
                    "inline": False,
                })

            if big_losers:
                losers_text = "\n".join(
                    f"• **{loser['symbol']}** {self._format_percent(loser['change_percent'])} ({self._format_price(loser['price'])})"
                    for loser in big_losers[:5]
                )
                fields.append({
                    "name": f"Big Losers (<-{threshold_percent}%)",
                    "value": losers_text,
                    "inline": False,
                })

            if not big_gainers and not big_losers:
                fields.append({
                    "name": "Movers",
                    "value": f"No equities moved more than {threshold_percent}% today",
                    "inline": False,
                })

            # Top gainers/losers regardless of threshold
            top_movers_parts = []
            if gainers:
                g = gainers[0]
                top_movers_parts.append(f"Top gainer: **{g['symbol']}** {self._format_percent(g['change_percent'])}")
            if losers:
                top_loser = losers[0]
                top_movers_parts.append(f"Top loser: **{top_loser['symbol']}** {self._format_percent(top_loser['change_percent'])}")
            if top_movers_parts:
                fields.append({
                    "name": f"Watchlist Overview ({total_items} equities)",
                    "value": "\n".join(top_movers_parts),
                    "inline": False,
                })

            # --- Alerts section ---
            alert_parts = [f"**{alerts_triggered}** triggered today | **{active_alerts}** active"]
            if top_triggers:
                for t in top_triggers[:3]:
                    alert_parts.append(f"• {t['name']}: {t['count']}x")

            fields.append({
                "name": "Alerts",
                "value": "\n".join(alert_parts),
                "inline": False,
            })

            embed = {
                "title": f"End of Day Summary - {today}",
                "color": 0x5865F2,
                "fields": fields,
                "timestamp": datetime.utcnow().isoformat(),
                "footer": {
                    "text": "Investing Companion",
                },
            }

            payload = {"embeds": [embed]}

            response = await self._post_webhook(webhook_url, payload)

            if response.status_code == 204:
                logger.info("Discord end-of-day summary sent")
                return True, None
            else:
                return False, f"Discord API returned status {response.status_code}"

        except Exception as e:
            error = f"Failed to send end-of-day summary: {str(e)}"
            logger.error(error, exc_info=True)
            return False, error


# Singleton instance
discord_service = DiscordNotificationService()


async def get_discord_service_configured() -> bool:
    """Helper to check if Discord is configured (async, for use in endpoints)."""
    return await discord_service.is_configured_async()
