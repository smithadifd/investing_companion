"""Simple model factories for tests. No external dependencies (no factory-boy)."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.account import Account
from app.db.models.alert import Alert
from app.db.models.equity import Equity
from app.db.models.lesson import Lesson
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
    sector: str | None = "Technology",
    industry: str | None = "Software",
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
    description: str | None = None,
    user_id: uuid.UUID | None = None,
    equities: list[Equity] | None = None,
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
    comparison_period: str | None = None,
    cooldown_minutes: int = 60,
    is_active: bool = True,
    last_checked_value: float | None = None,
    last_checked_at: datetime | None = None,
    was_above_threshold: bool | None = None,
    last_triggered_at: datetime | None = None,
    confirm_checks: int | None = None,
    watchlist_item_id: int | None = None,
    zone_state: dict | None = None,
    user_id: uuid.UUID | None = None,
) -> Alert:
    """Create an alert attached to an equity.

    Alerts are strictly owned (user_id is non-null). When no ``user_id`` is
    given, reuse the existing test user if there is one, else create an owner —
    so callers that don't care about ownership keep working.

    ``last_checked_at`` defaults to *now* whenever a ``last_checked_value`` is
    given, mirroring the check loop, which only ever writes the two together
    (``AlertService._mark_checked``). A value with no timestamp is a state the
    running app cannot produce, and the read side treats it as stale — so
    defaulting it keeps fixtures describing live alerts rather than accidentally
    exercising the staleness path. Pass an explicit datetime to age one on
    purpose.
    """
    if user_id is None:
        user_id = await db.scalar(select(User.id).order_by(User.created_at))
        if user_id is None:
            owner = await create_test_user(
                db, email=f"alert-owner-{uuid.uuid4().hex[:8]}@example.com"
            )
            user_id = owner.id
    alert = Alert(
        name=name,
        equity_id=equity.id,
        condition_type=condition_type,
        threshold_value=threshold_value,
        comparison_period=comparison_period,
        cooldown_minutes=cooldown_minutes,
        is_active=is_active,
        last_checked_value=last_checked_value,
        last_checked_at=(
            last_checked_at
            if last_checked_at is not None or last_checked_value is None
            else datetime.now(timezone.utc)
        ),
        was_above_threshold=was_above_threshold,
        last_triggered_at=last_triggered_at,
        confirm_checks=confirm_checks,
        watchlist_item_id=watchlist_item_id,
        zone_state=zone_state,
        user_id=user_id,
    )
    db.add(alert)
    await db.flush()
    return alert


async def create_test_watchlist_item(
    db: AsyncSession,
    watchlist: Watchlist,
    equity: Equity,
    *,
    notes: str | None = None,
    target_price: Decimal | None = None,
    thesis: str | None = None,
    entry_zones: list | None = None,
    catalyst_tags: list | None = None,
    track_calendar: bool = True,
) -> WatchlistItem:
    """Create a watchlist item (entry_zones as raw JSON: [{tier, low, high}])."""
    item = WatchlistItem(
        watchlist_id=watchlist.id,
        equity_id=equity.id,
        notes=notes,
        target_price=target_price,
        thesis=thesis,
        entry_zones=entry_zones,
        catalyst_tags=catalyst_tags,
        track_calendar=track_calendar,
    )
    db.add(item)
    await db.flush()
    return item


async def create_test_lesson(
    db: AsyncSession,
    equity: Equity,
    user: User,
    *,
    thesis_outcome: str = "wrong",
    lesson: str = "Sized too big into earnings.",
    tags: list | None = None,
    trade_id: int | None = None,
) -> Lesson:
    """Create a lesson record (tags as a lowercase string list)."""
    record = Lesson(
        user_id=user.id,
        equity_id=equity.id,
        trade_id=trade_id,
        thesis_outcome=thesis_outcome,
        lesson=lesson,
        tags=tags,
    )
    db.add(record)
    await db.flush()
    return record


async def create_test_account(
    db: AsyncSession,
    user: User,
    *,
    name: str = "Roth",
    broker: str | None = "Schwab",
    account_type: str | None = "roth",
    risk_profile: str | None = "aggressive",
    display_order: int = 0,
) -> Account:
    """Create a brokerage account owned by a user."""
    account = Account(
        user_id=user.id,
        name=name,
        broker=broker,
        account_type=account_type,
        risk_profile=risk_profile,
        display_order=display_order,
    )
    db.add(account)
    await db.flush()
    return account


async def create_test_trade(
    db: AsyncSession,
    equity: Equity,
    user: User,
    *,
    trade_type: TradeType = TradeType.BUY,
    quantity: Decimal = Decimal("10"),
    price: Decimal = Decimal("100.00"),
    fees: Decimal = Decimal("0"),
    executed_at: datetime | None = None,
    notes: str | None = None,
    account_id: int | None = None,
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
        account_id=account_id,
    )
    db.add(trade)
    await db.flush()
    return trade
