"""Discord webhook notification service."""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class DiscordNotificationService:
    """Service for sending notifications via Discord webhooks."""

    def __init__(self, webhook_url: Optional[str] = None):
        """Initialize the Discord notification service.

        Args:
            webhook_url: Discord webhook URL. Falls back to settings if not provided.
        """
        self._env_webhook_url = webhook_url or settings.DISCORD_WEBHOOK_URL
        self._client: Optional[httpx.AsyncClient] = None
        self._cached_db_url: Optional[str] = None
        self._cache_checked: bool = False

    async def _get_webhook_url(self) -> Optional[str]:
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
                        # Discord webhook URLs are not encrypted, use directly
                        self._cached_db_url = setting.value
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

    def _get_condition_description(
        self,
        condition_type: str,
        threshold: Decimal | float,
        comparison_period: Optional[str] = None,
    ) -> str:
        """Get human-readable condition description."""
        threshold_str = self._format_price(threshold) if condition_type not in (
            "percent_up", "percent_down"
        ) else f"{threshold}%"

        descriptions = {
            "above": f"above {threshold_str}",
            "below": f"below {threshold_str}",
            "crosses_above": f"crossed above {threshold_str}",
            "crosses_below": f"crossed below {threshold_str}",
            "percent_up": f"up {threshold}% in {comparison_period}",
            "percent_down": f"down {threshold}% in {comparison_period}",
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
        comparison_period: Optional[str] = None,
        is_ratio: bool = False,
        notes: Optional[str] = None,
    ) -> tuple[bool, Optional[str]]:
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

        Returns:
            Tuple of (success, error_message)
        """
        webhook_url = await self._get_webhook_url()
        if not webhook_url:
            return False, "Discord webhook URL not configured"

        try:
            # Build the embed
            condition_desc = self._get_condition_description(
                condition_type, threshold_value, comparison_period
            )

            # Color based on condition
            if condition_type in ("above", "crosses_above", "percent_up"):
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
                "description": f"**{target_symbol}** ({target_name}) is {condition_desc}",
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

            client = await self._get_client()
            response = await client.post(webhook_url, json=payload)

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

    async def send_test_notification(self) -> tuple[bool, Optional[str]]:
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

            client = await self._get_client()
            response = await client.post(webhook_url, json=payload)

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

    async def send_movers_summary(
        self,
        gainers: list[dict],
        losers: list[dict],
        threshold_percent: float,
        total_items: int,
        watchlist_count: int,
    ) -> tuple[bool, Optional[str]]:
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
        big_losers = [l for l in losers if float(l.get("change_percent", 0)) <= -threshold_percent]

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
                    f"• **{l['symbol']}** {self._format_percent(l['change_percent'])} ({self._format_price(l['price'])}) - {l.get('watchlist_name', 'Watchlist')}"
                    for l in big_losers[:5]
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

            client = await self._get_client()
            response = await client.post(webhook_url, json=payload)

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
    ) -> tuple[bool, Optional[str]]:
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

            client = await self._get_client()
            response = await client.post(webhook_url, json=payload)

            if response.status_code == 204:
                logger.info(f"Discord upcoming events sent: {len(events)} events")
                return True, None
            else:
                return False, f"Discord API returned status {response.status_code}"

        except Exception as e:
            error = f"Failed to send upcoming events: {str(e)}"
            logger.error(error, exc_info=True)
            return False, error

    async def send_daily_summary(
        self,
        alerts_triggered: int,
        active_alerts: int,
        top_triggers: list[dict],
    ) -> tuple[bool, Optional[str]]:
        """Send a daily summary of alert activity.

        Args:
            alerts_triggered: Number of alerts triggered today
            active_alerts: Total number of active alerts
            top_triggers: List of most triggered alerts with details

        Returns:
            Tuple of (success, error_message)
        """
        webhook_url = await self._get_webhook_url()
        if not webhook_url:
            return False, "Discord webhook URL not configured"

        try:
            # Build summary fields
            fields = [
                {
                    "name": "Alerts Triggered Today",
                    "value": str(alerts_triggered),
                    "inline": True,
                },
                {
                    "name": "Active Alerts",
                    "value": str(active_alerts),
                    "inline": True,
                },
            ]

            if top_triggers:
                triggers_text = "\n".join(
                    f"• **{t['name']}** ({t['symbol']}): {t['count']} times"
                    for t in top_triggers[:5]
                )
                fields.append({
                    "name": "Top Triggered",
                    "value": triggers_text,
                    "inline": False,
                })

            embed = {
                "title": "📊 Daily Alert Summary",
                "color": 0x5865F2,
                "fields": fields,
                "timestamp": datetime.utcnow().isoformat(),
                "footer": {
                    "text": "Investing Companion",
                },
            }

            payload = {"embeds": [embed]}

            client = await self._get_client()
            response = await client.post(webhook_url, json=payload)

            if response.status_code == 204:
                return True, None
            else:
                return False, f"Discord API returned status {response.status_code}"

        except Exception as e:
            error = f"Failed to send daily summary: {str(e)}"
            logger.error(error, exc_info=True)
            return False, error


# Singleton instance
discord_service = DiscordNotificationService()


async def get_discord_service_configured() -> bool:
    """Helper to check if Discord is configured (async, for use in endpoints)."""
    return await discord_service.is_configured_async()
