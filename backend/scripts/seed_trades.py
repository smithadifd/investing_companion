"""Seed script to add dummy trade data for testing."""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.db.models.user import User
from app.db.models.trade import Trade, TradeType
from app.services.equity import EquityService
from app.services.trade import TradeService


async def seed_trades():
    """Insert dummy trades for testing."""
    async with AsyncSessionLocal() as db:
        # Get the first user (or create one if needed)
        result = await db.execute(select(User).limit(1))
        user = result.scalar_one_or_none()

        if not user:
            print("No user found. Please create a user first via the app.")
            return

        print(f"Using user: {user.email} (ID: {user.id})")

        equity_service = EquityService(db)
        trade_service = TradeService(db)

        # Define test trades
        # Format: (symbol, trade_type, quantity, price, fees, days_ago, notes)
        test_trades = [
            # AAPL - Complete round trip (profit)
            ("AAPL", "buy", 50, 175.00, 0, 30, "Initial AAPL position - bullish on iPhone sales"),
            ("AAPL", "buy", 25, 170.00, 0, 20, "Adding on dip"),
            ("AAPL", "sell", 75, 185.00, 0, 5, "Taking profits before earnings"),

            # MSFT - Partial position (still holding)
            ("MSFT", "buy", 30, 380.00, 4.95, 45, "Long-term hold, cloud growth"),
            ("MSFT", "buy", 20, 375.00, 4.95, 25, "DCA buy"),

            # NVDA - Quick trade (profit)
            ("NVDA", "buy", 15, 450.00, 0, 14, "AI momentum play"),
            ("NVDA", "sell", 15, 520.00, 0, 7, "Hit target, taking gains"),

            # TSLA - Loss trade
            ("TSLA", "buy", 20, 260.00, 0, 35, "Speculative buy"),
            ("TSLA", "sell", 20, 235.00, 0, 28, "Stop loss hit"),

            # GOOGL - Current position
            ("GOOGL", "buy", 25, 140.00, 0, 15, "Undervalued relative to AI potential"),

            # AMD - Multiple trades
            ("AMD", "buy", 40, 120.00, 0, 50, "Chip sector play"),
            ("AMD", "sell", 20, 135.00, 0, 40, "Partial profit taking"),
            ("AMD", "buy", 30, 125.00, 0, 20, "Re-entering on pullback"),
            ("AMD", "sell", 50, 145.00, 0, 3, "Full exit at resistance"),

            # META - Short trade example
            ("META", "short", 15, 520.00, 0, 12, "Overextended, expecting pullback"),
            ("META", "cover", 15, 505.00, 0, 8, "Covered for small profit"),

            # SPY - ETF position
            ("SPY", "buy", 20, 480.00, 0, 60, "Core portfolio holding"),
        ]

        print(f"\nInserting {len(test_trades)} test trades...")

        for symbol, trade_type, qty, price, fees, days_ago, notes in test_trades:
            # Get or create equity
            equity = await equity_service.get_or_create_equity(symbol)
            if not equity:
                print(f"  Could not find/create equity: {symbol}")
                continue

            # Calculate execution date
            executed_at = datetime.now(timezone.utc) - timedelta(days=days_ago)

            # Create trade
            trade = Trade(
                user_id=user.id,
                equity_id=equity.id,
                trade_type=TradeType(trade_type),
                quantity=Decimal(str(qty)),
                price=Decimal(str(price)),
                fees=Decimal(str(fees)),
                executed_at=executed_at,
                notes=notes,
            )
            db.add(trade)
            print(f"  Added: {trade_type.upper()} {qty} {symbol} @ ${price}")

        await db.commit()
        print("\nTrades committed to database.")

        # Recalculate P&L pairs for all affected equities
        print("\nRecalculating P&L pairs...")
        symbols_processed = set()
        for symbol, *_ in test_trades:
            if symbol not in symbols_processed:
                equity = await equity_service.get_or_create_equity(symbol)
                if equity:
                    await trade_service._recalculate_pairs(user.id, equity.id)
                    symbols_processed.add(symbol)
                    print(f"  Recalculated pairs for {symbol}")

        await db.commit()
        print("\nDone! Seed data inserted successfully.")

        # Print summary
        print("\n" + "="*50)
        print("EXPECTED RESULTS SUMMARY")
        print("="*50)
        print("""
AAPL (Closed Position):
  - Bought: 50 @ $175 + 25 @ $170 = $8,750 + $4,250 = $13,000
  - Sold: 75 @ $185 = $13,875
  - Realized P&L: $13,875 - $13,000 = $875 profit

MSFT (Open Position):
  - Holding: 50 shares
  - Cost: 30 @ $380 + 20 @ $375 + $9.90 fees = $11,400 + $7,500 + $9.90 = $18,909.90
  - Avg Cost: ~$378.20/share

NVDA (Closed Position):
  - Bought: 15 @ $450 = $6,750
  - Sold: 15 @ $520 = $7,800
  - Realized P&L: $7,800 - $6,750 = $1,050 profit

TSLA (Closed Position - Loss):
  - Bought: 20 @ $260 = $5,200
  - Sold: 20 @ $235 = $4,700
  - Realized P&L: $4,700 - $5,200 = -$500 loss

GOOGL (Open Position):
  - Holding: 25 shares @ $140 = $3,500 cost basis

AMD (Closed Position):
  - Trade 1: Buy 40 @ $120 = $4,800, Sell 20 @ $135 = $2,700 → P&L on 20 shares: +$300
  - Trade 2: Buy 30 @ $125 = $3,750
  - Remaining 20 from first buy + 30 from second = 50 shares
  - Sell 50 @ $145 = $7,250
  - Cost of 50: 20 @ $120 + 30 @ $125 = $2,400 + $3,750 = $6,150
  - P&L on close: $7,250 - $6,150 = $1,100
  - Total AMD P&L: $300 + $1,100 = $1,400 profit

META (Closed Short):
  - Shorted: 15 @ $520 = $7,800 received
  - Covered: 15 @ $505 = $7,575 paid
  - Realized P&L: $7,800 - $7,575 = $225 profit

SPY (Open Position):
  - Holding: 20 shares @ $480 = $9,600 cost basis

TOTAL REALIZED P&L: $875 + $1,050 - $500 + $1,400 + $225 = $3,050
Open Positions: MSFT (50), GOOGL (25), SPY (20)
Closed Trades: 8 complete round-trips
Winning: 5 (AAPL, NVDA, AMD, META partial, AMD final)
Losing: 1 (TSLA)
""")


if __name__ == "__main__":
    asyncio.run(seed_trades())
