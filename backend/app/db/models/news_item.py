"""NewsItem model - stored news/catalyst articles for the News & Catalyst agent.

Schema-only for now (sub-PR 1 of the Tier-1 advisory agents wave, see
``docs/issues/014-intelligent-agents.md``). The News & Catalyst agent (a
follow-up sub-PR) will populate this table from a news provider and read it
back to enrich the morning pulse / EOD wrap ("UUUU up 5%" -> "UUUU up 5% -
DOE announced new uranium reserve program."). No ingestion or agent-run logic
lives here yet.

Not user-scoped: news articles are shared context, not per-user data (mirrors
how ``EconomicEvent`` links to an equity rather than a user for macro/earnings
rows). ``symbol`` is a plain string rather than an ``equity_id`` FK because a
news provider can return articles for tickers the app hasn't tracked/watch-
listed yet (no matching ``equities`` row), and general market news has no
symbol at all.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class NewsItem(Base, TimestampMixin):
    """A single stored news/catalyst article, optionally tied to a symbol."""

    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(primary_key=True)

    # NULL = general market news, not tied to one symbol.
    symbol: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    headline: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Agent-assigned relevance score in [0.0, 1.0]; NULL until the News &
    # Catalyst agent scores it. Deliberately a plain float, not Numeric — this
    # is a heuristic ranking signal, not a value requiring exact precision.
    relevance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index("idx_news_items_symbol_published", "symbol", "published_at"),
        Index("idx_news_items_published_at", "published_at"),
        # Dedup guard: a provider re-fetch of the same article should not
        # create a second row.
        Index("idx_news_items_url", "url", unique=True),
    )

    def __repr__(self) -> str:
        return f"<NewsItem(id={self.id}, symbol={self.symbol}, headline={self.headline[:40]!r})>"
