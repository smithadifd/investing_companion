"""Add TimescaleDB retention + compression + daily continuous aggregate to price_history

``price_history`` has been a bare hypertable growing unbounded since it was
created (``20260131_001``). This migration adds the three standard TimescaleDB
lifecycle policies so it stays bounded and query-efficient:

Chosen defaults
---------------
* **Compression** — segment by ``equity_id``, order by ``timestamp DESC`` (mirrors
  the ``(equity_id, timestamp)`` primary key), and compress chunks older than
  **30 days**. Recent data (the alert/quote hot path) stays uncompressed and
  fast to write; older chunks shrink ~10-20x.
* **Retention** — drop raw chunks older than **24 months**. Two years of intraday
  bars is plenty for the app's percent-change / percent-from-high reference
  windows; the daily aggregate below preserves long-range history past that.
* **Continuous aggregate** — ``price_history_daily``, a daily OHLCV roll-up
  (first/max/min/last + summed volume), refreshed daily. It survives raw
  retention, so long-horizon charts keep working after the raw bars are dropped.
  It is created ``WITH NO DATA``; the first scheduled refresh (or a manual
  ``CALL refresh_continuous_aggregate(...)``) backfills it.

Apply-gated: this is NOT applied automatically. Per the repo's deploy contract,
Alembic runs against prod as a deploy step, and the TimescaleDB policy functions
here require a live TimescaleDB (they are no-ops / errors on vanilla Postgres).

Revision ID: 20260717_001
Revises: 20260715_002
Create Date: 2026-07-17

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20260717_001'
down_revision: Union[str, None] = '20260715_002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tunable defaults (kept as named constants so they are easy to review / change).
COMPRESS_AFTER = "30 days"
RETAIN_RAW_FOR = "24 months"
CAGG_NAME = "price_history_daily"


def upgrade() -> None:
    # --- Compression -----------------------------------------------------
    # Configure columnar compression, then schedule it for chunks older than
    # COMPRESS_AFTER. segmentby=equity_id keeps per-symbol scans efficient.
    op.execute(
        """
        ALTER TABLE price_history SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'equity_id',
            timescaledb.compress_orderby = 'timestamp DESC'
        );
        """
    )
    op.execute(
        f"SELECT add_compression_policy('price_history', INTERVAL '{COMPRESS_AFTER}');"
    )

    # --- Retention -------------------------------------------------------
    # Drop raw chunks older than RETAIN_RAW_FOR (the daily CAGG retains history).
    op.execute(
        f"SELECT add_retention_policy('price_history', INTERVAL '{RETAIN_RAW_FOR}');"
    )

    # --- Continuous aggregate: daily OHLCV ------------------------------
    op.execute(
        f"""
        CREATE MATERIALIZED VIEW {CAGG_NAME}
        WITH (timescaledb.continuous) AS
        SELECT
            equity_id,
            time_bucket(INTERVAL '1 day', "timestamp") AS bucket,
            first(open, "timestamp") AS open,
            max(high) AS high,
            min(low) AS low,
            last(close, "timestamp") AS close,
            last(adj_close, "timestamp") AS adj_close,
            sum(volume) AS volume
        FROM price_history
        GROUP BY equity_id, bucket
        WITH NO DATA;
        """
    )
    # Refresh the last few days daily so late-arriving bars settle; leaves the
    # most recent hour to real-time aggregation.
    op.execute(
        f"""
        SELECT add_continuous_aggregate_policy(
            '{CAGG_NAME}',
            start_offset => INTERVAL '3 days',
            end_offset => INTERVAL '1 hour',
            schedule_interval => INTERVAL '1 day'
        );
        """
    )


def downgrade() -> None:
    # Reverse order: drop the CAGG (and its policy) first, then retention, then
    # compression. Disabling compression requires decompressing any compressed
    # chunks first, so do that before clearing the compress settings.
    op.execute(
        f"SELECT remove_continuous_aggregate_policy('{CAGG_NAME}', if_exists => true);"
    )
    op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {CAGG_NAME};")

    op.execute(
        "SELECT remove_retention_policy('price_history', if_exists => true);"
    )
    op.execute(
        "SELECT remove_compression_policy('price_history', if_exists => true);"
    )

    # Decompress everything so compression can be turned off cleanly.
    op.execute(
        """
        SELECT decompress_chunk(c, if_compressed => true)
        FROM show_chunks('price_history') c;
        """
    )
    op.execute("ALTER TABLE price_history SET (timescaledb.compress = false);")
