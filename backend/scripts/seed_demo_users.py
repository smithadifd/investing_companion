#!/usr/bin/env python3
"""
Seed demo user account with sample watchlists, trades, and alerts.

Creates:
- Demo user (demo@example.com / demo1234!)
- 2 watchlists (Tech Giants, Growth Picks) with items
- Synthetic trades for a realistic portfolio
- Sample alerts (some triggered, some active)

Idempotent — skips creation if demo user already exists.

Usage:
    cd backend
    python -m scripts.seed_demo_users
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.db.models.user import User
from app.db.models.trade import Trade, TradeType
from app.db.models.watchlist import Watchlist, WatchlistItem
from app.db.models.alert import Alert
from app.services.auth import AuthService
from app.services.equity import EquityService

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo1234!"


async def ensure_equity(db, symbol: str, name: str) -> int:
    """Ensure an equity exists and return its ID."""
    equity_service = EquityService(db)
    equity = await equity_service.get_or_create_equity(symbol)
    if equity:
        return equity.id
    raise ValueError(f"Could not create equity for {symbol}")


async def seed_demo_user(db) -> User:
    """Create demo user if it doesn't exist."""
    result = await db.execute(select(User).where(User.email == DEMO_EMAIL))
    user = result.scalar_one_or_none()

    if user:
        print(f"Demo user already exists (id={user.id})")
        return user

    auth_service = AuthService(db)
    password_hash = auth_service.hash_password(DEMO_PASSWORD)

    user = User(
        email=DEMO_EMAIL,
        password_hash=password_hash,
        is_active=True,
        is_admin=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    print(f"Created demo user: {DEMO_EMAIL} (id={user.id})")
    return user


async def seed_watchlists(db, user_id: int) -> None:
    """Create sample watchlists with items."""
    # Check if watchlists already exist
    result = await db.execute(select(Watchlist).limit(1))
    if result.scalar_one_or_none():
        print("Watchlists already exist, skipping")
        return

    tech_tickers = [
        ("AAPL", "Apple Inc."),
        ("MSFT", "Microsoft Corporation"),
        ("GOOGL", "Alphabet Inc."),
        ("AMZN", "Amazon.com Inc."),
        ("NVDA", "NVIDIA Corporation"),
        ("META", "Meta Platforms Inc."),
    ]

    growth_tickers = [
        ("PLTR", "Palantir Technologies"),
        ("SNOW", "Snowflake Inc."),
        ("CRWD", "CrowdStrike Holdings"),
        ("NET", "Cloudflare Inc."),
        ("DDOG", "Datadog Inc."),
    ]

    # Tech Giants watchlist
    tech_wl = Watchlist(name="Tech Giants", description="Mega-cap tech leaders")
    db.add(tech_wl)
    await db.flush()

    for symbol, name in tech_tickers:
        equity_id = await ensure_equity(db, symbol, name)
        item = WatchlistItem(
            watchlist_id=tech_wl.id,
            equity_id=equity_id,
        )
        db.add(item)

    # Growth Picks watchlist
    growth_wl = Watchlist(name="Growth Picks", description="High-growth SaaS & cloud")
    db.add(growth_wl)
    await db.flush()

    for symbol, name in growth_tickers:
        equity_id = await ensure_equity(db, symbol, name)
        item = WatchlistItem(
            watchlist_id=growth_wl.id,
            equity_id=equity_id,
        )
        db.add(item)

    await db.commit()
    print(f"Created 2 watchlists ({len(tech_tickers)} + {len(growth_tickers)} items)")


async def seed_trades(db, user_id: int) -> None:
    """Create synthetic trades for a realistic portfolio."""
    result = await db.execute(select(Trade).where(Trade.user_id == user_id).limit(1))
    if result.scalar_one_or_none():
        print("Trades already exist, skipping")
        return

    now = datetime.now(timezone.utc)

    trade_data = [
        # AAPL - long position
        ("AAPL", "Apple Inc.", TradeType.BUY, 50, "178.50", 90),
        ("AAPL", "Apple Inc.", TradeType.BUY, 25, "185.20", 60),
        # MSFT - long position
        ("MSFT", "Microsoft Corporation", TradeType.BUY, 30, "365.00", 120),
        # NVDA - bought and partially sold
        ("NVDA", "NVIDIA Corporation", TradeType.BUY, 40, "480.00", 150),
        ("NVDA", "NVIDIA Corporation", TradeType.SELL, 15, "720.00", 45),
        # GOOGL - long position
        ("GOOGL", "Alphabet Inc.", TradeType.BUY, 60, "142.50", 100),
        # PLTR - swing trade (closed)
        ("PLTR", "Palantir Technologies", TradeType.BUY, 200, "22.50", 75),
        ("PLTR", "Palantir Technologies", TradeType.SELL, 200, "28.75", 30),
        # AMZN - long position
        ("AMZN", "Amazon.com Inc.", TradeType.BUY, 20, "175.00", 80),
    ]

    for symbol, name, trade_type, quantity, price, days_ago in trade_data:
        equity_id = await ensure_equity(db, symbol, name)
        trade = Trade(
            user_id=user_id,
            equity_id=equity_id,
            trade_type=trade_type,
            quantity=Decimal(str(quantity)),
            price=Decimal(price),
            fees=Decimal("0"),
            executed_at=now - timedelta(days=days_ago),
        )
        db.add(trade)

    await db.commit()
    print(f"Created {len(trade_data)} trades")


async def seed_alerts(db, user_id: int) -> None:
    """Create sample alerts."""
    result = await db.execute(select(Alert).limit(1))
    if result.scalar_one_or_none():
        print("Alerts already exist, skipping")
        return

    alert_data = [
        ("AAPL", "Apple Inc.", "AAPL Below $170", "below", 170.0, True),
        ("NVDA", "NVIDIA Corporation", "NVDA Above $800", "above", 800.0, True),
        ("MSFT", "Microsoft Corporation", "MSFT Drop 5%", "percent_down", 5.0, True),
        ("GOOGL", "Alphabet Inc.", "GOOGL Above $180", "above", 180.0, False),
    ]

    for symbol, name, alert_name, condition, threshold, active in alert_data:
        equity_id = await ensure_equity(db, symbol, name)
        alert = Alert(
            name=alert_name,
            equity_id=equity_id,
            condition_type=condition,
            threshold_value=threshold,
            is_active=active,
        )
        db.add(alert)

    await db.commit()
    print(f"Created {len(alert_data)} alerts")


async def main():
    """Run all seed operations."""
    print("=== Seeding Demo Data ===\n")

    async with AsyncSessionLocal() as db:
        user = await seed_demo_user(db)
        await seed_watchlists(db, user.id)
        await seed_trades(db, user.id)
        await seed_alerts(db, user.id)

    print("\n=== Demo seeding complete ===")


if __name__ == "__main__":
    asyncio.run(main())
