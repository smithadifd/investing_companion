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
        self.webhook_url = webhook_url or settings.DISCORD_WEBHOOK_URL
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def is_configured(self) -> bool:
        """Check if Discord webhook is configured."""
        return bool(self.webhook_url)

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
        if not self.is_configured:
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
            response = await client.post(self.webhook_url, json=payload)

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
        if not self.is_configured:
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
            response = await client.post(self.webhook_url, json=payload)

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
        if not self.is_configured:
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
            response = await client.post(self.webhook_url, json=payload)

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
