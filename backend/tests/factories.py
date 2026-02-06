"""Simple model factories for tests. No external dependencies (no factory-boy)."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.alert import Alert
from app.db.models.equity import Equity
from app.db.models.trade import Trade, TradeType
from app.db.models.user import User
from app.db.models.watchlist import Watchlist, WatchlistItem
from app.services.auth import AuthService


async def create_test_user(
    db: AsyncSession,
    *,
    email: str = "test@example.com",
    password: str = "TestPass123!",
    is_active: bool = True,
    is_admin: bool = False,
) -> User:
    """Create a user with a properly hashed password."""
    auth_service = AuthService(db)
    user = User(
        id=uuid.uuid4(),
        email=email.lower(),
        password_hash=auth_service.hash_password(password),
        is_active=is_active,
        is_admin=is_admin,
    )
    db.add(user)
    await db.flush()
    return user


async def create_test_equity(
    db: AsyncSession,
    *,
    symbol: str = "TEST",
    name: str = "Test Corp",
    exchange: str = "NASDAQ",
    asset_type: str = "stock",
    sector: Optional[str] = "Technology",
    industry: Optional[str] = "Software",
    country: str = "US",
    currency: str = "USD",
) -> Equity:
    """Create an equity record."""
    equity = Equity(
        symbol=symbol.upper(),
        name=name,
        exchange=exchange,
        asset_type=asset_type,
        sector=sector,
        industry=industry,
        country=country,
        currency=currency,
    )
    db.add(equity)
    await db.flush()
    return equity


async def create_test_watchlist(
    db: AsyncSession,
    *,
    name: str = "Test Watchlist",
    description: Optional[str] = None,
    user_id: Optional[uuid.UUID] = None,
    equities: Optional[list[Equity]] = None,
) -> Watchlist:
    """Create a watchlist, optionally with items."""
    watchlist = Watchlist(
        name=name,
        description=description,
        user_id=user_id,
    )
    db.add(watchlist)
    await db.flush()

    if equities:
        for eq in equities:
            item = WatchlistItem(
                watchlist_id=watchlist.id,
                equity_id=eq.id,
            )
            db.add(item)
        await db.flush()

    return watchlist


async def create_test_alert(
    db: AsyncSession,
    equity: Equity,
    *,
    name: str = "Test Alert",
    condition_type: str = "above",
    threshold_value: float = 100.0,
    comparison_period: Optional[str] = None,
    cooldown_minutes: int = 60,
    is_active: bool = True,
    last_checked_value: Optional[float] = None,
    was_above_threshold: Optional[bool] = None,
    last_triggered_at: Optional[datetime] = None,
    user_id: Optional[uuid.UUID] = None,
) -> Alert:
    """Create an alert attached to an equity."""
    alert = Alert(
        name=name,
        equity_id=equity.id,
        condition_type=condition_type,
        threshold_value=threshold_value,
        comparison_period=comparison_period,
        cooldown_minutes=cooldown_minutes,
        is_active=is_active,
        last_checked_value=last_checked_value,
        was_above_threshold=was_above_threshold,
        last_triggered_at=last_triggered_at,
        user_id=user_id,
    )
    db.add(alert)
    await db.flush()
    return alert


async def create_test_trade(
    db: AsyncSession,
    equity: Equity,
    user: User,
    *,
    trade_type: TradeType = TradeType.BUY,
    quantity: Decimal = Decimal("10"),
    price: Decimal = Decimal("100.00"),
    fees: Decimal = Decimal("0"),
    executed_at: Optional[datetime] = None,
    notes: Optional[str] = None,
) -> Trade:
    """Create a trade record."""
    trade = Trade(
        user_id=user.id,
        equity_id=equity.id,
        trade_type=trade_type,
        quantity=quantity,
        price=price,
        fees=fees,
        executed_at=executed_at or datetime.now(timezone.utc),
        notes=notes,
    )
    db.add(trade)
    await db.flush()
    return trade
