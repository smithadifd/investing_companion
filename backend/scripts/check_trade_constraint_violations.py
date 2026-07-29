"""check_trade_constraint_violations.py - READ-ONLY pre-check for the trades
CHECK constraints.

Run this BEFORE applying migration ``20260729_001`` (``CHECK (quantity > 0)``),
and again before deciding on the deferred ``CHECK (price > 0)`` in
``alembic/deferred/``. Postgres validates a CHECK constraint against existing
rows at ADD time, so a single violator turns the migration into a failed deploy
step - this script answers "would it fail?" without touching anything.

It reports four buckets in two independent categories, because they mean
different things:

  QUANTITY (quantity = 0, quantity < 0)
      Blocking. ``quantity`` is an unsigned magnitude - direction is carried by
      ``trade_type`` (buy/sell/short/cover) - so either bucket is corruption,
      and either one fails migration 20260729_001. Non-empty => exit code 1.

  PRICE (price = 0, price < 0)
      Informational only; never affects the exit code, because no price
      constraint is being applied. ``price = 0`` may be entirely legitimate
      (vested RSU, gifted/inherited shares, a spin-off lot booked at 0), while
      ``price < 0`` never is. This section is the input to the deferred
      price-constraint decision - see ``alembic/deferred/README.md``.

Read-only by construction: it opens one transaction, issues
``SET TRANSACTION READ ONLY`` before any other statement, and only ever SELECTs.
Postgres itself rejects any write attempted on that connection.

Usage::

    # against whatever DATABASE_URL points at (backend/.env, or the env var)
    python backend/scripts/check_trade_constraint_violations.py

    # against a specific database
    python backend/scripts/check_trade_constraint_violations.py \
        --database-url postgresql+asyncpg://user:pass@host:5432/dbname

    # inside the deployed container
    docker exec investing_api python /app/scripts/check_trade_constraint_violations.py

    # no Python / no app deps handy: print the raw SQL and run it in psql
    python backend/scripts/check_trade_constraint_violations.py --print-sql

Exit codes::

    0  no quantity violators - migration 20260729_001 is safe to apply
    1  quantity violators found - fix the data before applying
    2  the check could not be run (connection/DB error); nothing was inspected
"""

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# Allow `python backend/scripts/check_trade_constraint_violations.py` from the
# repo root, not just from inside backend/ (mirrors seed_trades.py).
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.core.config import settings  # noqa: E402

DEFAULT_SAMPLE_LIMIT = 20

# Sample columns: enough to identify and triage a row without dumping notes.
SAMPLE_COLUMNS = """
    t.id,
    t.user_id,
    e.symbol,
    t.trade_type,
    t.quantity,
    t.price,
    t.executed_at,
    t.source,
    t.is_synthetic
"""


@dataclass(frozen=True)
class Bucket:
    """One violation bucket: a category, a predicate, and what it means."""

    category: str  # "quantity" | "price"
    name: str  # "zero" | "negative"
    predicate: str  # SQL boolean over the trades row
    note: str  # why the reader should (or should not) care

    @property
    def label(self) -> str:
        return f"{self.category}/{self.name}"

    def count_sql(self) -> str:
        return f"SELECT count(*) FROM trades t WHERE {self.predicate};"

    def sample_sql(self, limit: int) -> str:
        return (
            f"SELECT{SAMPLE_COLUMNS}"
            "FROM trades t JOIN equities e ON e.id = t.equity_id "
            f"WHERE {self.predicate} ORDER BY t.id LIMIT {limit};"
        )


BUCKETS: tuple[Bucket, ...] = (
    Bucket(
        "quantity",
        "zero",
        "t.quantity = 0",
        "malformed: a zero-quantity trade is a no-op row, not a position change",
    ),
    Bucket(
        "quantity",
        "negative",
        "t.quantity < 0",
        "malformed: direction lives in trade_type; a negative quantity is not a short",
    ),
    Bucket(
        "price",
        "zero",
        "t.price = 0",
        "MAY BE LEGITIMATE: vested RSU / gifted / inherited / spin-off lot at zero basis",
    ),
    Bucket(
        "price",
        "negative",
        "t.price < 0",
        "never legitimate: corruption, fix the data (do not widen the constraint)",
    ),
)

QUANTITY_BUCKETS = tuple(b for b in BUCKETS if b.category == "quantity")
PRICE_BUCKETS = tuple(b for b in BUCKETS if b.category == "price")


def print_sql(limit: int) -> None:
    """Emit the raw SQL so it can be pasted into psql, no Python needed."""
    print("-- READ-ONLY. Run inside a read-only transaction:")
    print("BEGIN; SET TRANSACTION READ ONLY;")
    for bucket in BUCKETS:
        print(f"\n-- [{bucket.label}] {bucket.note}")
        print(bucket.count_sql())
        print(bucket.sample_sql(limit))
    print("\nROLLBACK;")


async def collect(database_url: str, limit: int) -> dict[str, dict]:
    """Count + sample every bucket over one read-only transaction."""
    engine = create_async_engine(database_url)
    results: dict[str, dict] = {}
    try:
        async with engine.connect() as conn:
            # First statement in the transaction: Postgres then refuses any
            # write on this connection for its duration.
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            for bucket in BUCKETS:
                count = await conn.scalar(text(bucket.count_sql()))
                samples: list[dict] = []
                if count:
                    rows = await conn.execute(text(bucket.sample_sql(limit)))
                    samples = [
                        {k: (None if v is None else str(v)) for k, v in row._mapping.items()}
                        for row in rows
                    ]
                results[bucket.label] = {
                    "category": bucket.category,
                    "bucket": bucket.name,
                    "predicate": bucket.predicate,
                    "note": bucket.note,
                    "count": int(count or 0),
                    "samples": samples,
                }
    finally:
        await engine.dispose()
    return results


def _print_bucket(result: dict, limit: int) -> None:
    count = result["count"]
    flag = " " if count == 0 else "!"
    print(
        f"  {flag} {result['bucket']:<9} {result['predicate']:<16} "
        f"{count:>6} row(s)   {result['note']}"
    )
    if not result["samples"]:
        return
    header = list(result["samples"][0].keys())
    print("      " + " | ".join(header))
    for sample in result["samples"]:
        print("      " + " | ".join(str(sample[k]) for k in header))
    if count > len(result["samples"]):
        print(f"      ... {count - len(result['samples'])} more (raise --limit, currently {limit})")


def report(results: dict[str, dict], url_display: str, limit: int) -> int:
    """Print the human report; return the process exit code."""
    quantity_total = sum(results[b.label]["count"] for b in QUANTITY_BUCKETS)
    price_total = sum(results[b.label]["count"] for b in PRICE_BUCKETS)

    print(f"Trade constraint pre-check - {url_display}")
    print("READ-ONLY: every statement ran in a SET TRANSACTION READ ONLY transaction.\n")

    print("QUANTITY - gate for migration 20260729_001: CHECK (quantity > 0)")
    for bucket in QUANTITY_BUCKETS:
        _print_bucket(results[bucket.label], limit)
    if quantity_total == 0:
        print("  => CLEAR. ck_trades_quantity_positive will apply cleanly.\n")
    else:
        print(
            f"  => BLOCKED. {quantity_total} row(s) violate quantity > 0; "
            "`ALTER TABLE ... ADD CONSTRAINT` will fail with CheckViolation.\n"
            "     Correct or delete these rows first - do not weaken the "
            "constraint to fit them.\n"
        )

    print("PRICE - informational only; no price constraint is being applied")
    print("        (the CHECK (price > 0) migration is parked in alembic/deferred/)")
    for bucket in PRICE_BUCKETS:
        _print_bucket(results[bucket.label], limit)
    if price_total == 0:
        print(
            "  => No zero/negative prices. The deferred price > 0 constraint "
            "would apply cleanly\n     if the apply sitting decides to promote it.\n"
        )
    else:
        print(
            f"  => {price_total} row(s) at or below zero. Decide per "
            "alembic/deferred/README.md:\n"
            "     legitimate zero-basis lots => promote price >= 0 instead; "
            "negatives => fix the data.\n"
        )

    return 1 if quantity_total else 0


async def main_async(args: argparse.Namespace) -> int:
    database_url = args.database_url or settings.DATABASE_URL
    url_display = make_url(database_url).render_as_string(hide_password=True)
    try:
        results = await collect(database_url, args.limit)
    except Exception as exc:  # operational failure - nothing was inspected
        print(f"Pre-check could not run against {url_display}: {exc!r}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"database": url_display, "buckets": results}, indent=2))
        return 1 if any(
            results[b.label]["count"] for b in QUANTITY_BUCKETS
        ) else 0
    return report(results, url_display, args.limit)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "READ-ONLY pre-check: report trades rows that would violate the "
            "quantity > 0 constraint (blocking) and the deferred price > 0 "
            "constraint (informational)."
        )
    )
    parser.add_argument(
        "--database-url",
        help="SQLAlchemy async URL to inspect (default: settings.DATABASE_URL).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_SAMPLE_LIMIT,
        help=f"Sample rows to show per bucket (default {DEFAULT_SAMPLE_LIMIT}).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human report.",
    )
    parser.add_argument(
        "--print-sql",
        action="store_true",
        help="Print the SQL this script runs and exit, without connecting.",
    )
    args = parser.parse_args()

    if args.print_sql:
        print_sql(args.limit)
        return 0
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
