"""Extended-hours watchlist movers, shared by the morning pulse and EOD wrap.

Both briefings want the same thing: "which watchlist symbols are moving in the
current extended session?" — with an honest fallback when the session has no
data (weekend, holiday, pre-open before any trades). Keeping the collection
logic here means the two tasks can't drift apart on dedup, thresholds, or
labeling rules.
"""

import logging
from typing import Protocol
from collections.abc import Iterable

logger = logging.getLogger(__name__)

MOVER_THRESHOLD_PERCENT = 2.0


class ExtendedQuoteProvider(Protocol):
    async def get_extended_quote(self, symbol: str) -> dict | None: ...


async def collect_extended_movers(
    symbols: Iterable[str],
    provider: ExtendedQuoteProvider,
    *,
    target_session: str,
    threshold: float = MOVER_THRESHOLD_PERCENT,
) -> tuple[list[dict], str]:
    """Collect movers (abs change >= threshold) for an extended session.

    Returns (movers, session_label):
    - If any symbol reports the target session ('pre' or 'post'), the label is
      the target session and only live quotes count — quotes in that session,
      plus 'regular' quotes (24h instruments like futures/forex whose change
      is also live vs the prior close). Symbols with no extended data are
      excluded rather than letting a stale at-close move masquerade as a
      pre/post-market move.
    - Otherwise the label is 'closed' and all quotes fall back to their last
      regular-session change, for the caller to label honestly ("at close").

    Symbols are deduped preserving order; one failing symbol never breaks the
    batch. Movers are sorted by absolute change, descending.
    """
    quotes: list[dict] = []
    seen: set[str] = set()
    for symbol in symbols:
        if symbol in seen:
            continue
        seen.add(symbol)
        try:
            quote = await provider.get_extended_quote(symbol)
        except Exception as e:
            logger.warning(f"Failed to fetch extended quote for {symbol}: {e}")
            continue
        if quote and quote.get("change_percent") is not None:
            quotes.append({"symbol": symbol, **quote})

    has_target = any(q["session"] == target_session for q in quotes)
    if has_target:
        session_label = target_session
        candidates = [q for q in quotes if q["session"] in (target_session, "regular")]
    else:
        session_label = "closed"
        candidates = quotes

    movers = [
        {"symbol": q["symbol"], "change_percent": float(q["change_percent"])}
        for q in candidates
        if abs(float(q["change_percent"])) >= threshold
    ]
    movers.sort(key=lambda m: abs(m["change_percent"]), reverse=True)
    return movers, session_label


def dedupe_movers(movers: list[dict]) -> list[dict]:
    """Drop repeat symbols (keep first occurrence).

    A ticker held in N watchlists otherwise prints N times in the EOD
    big-movers section.
    """
    seen: set[str] = set()
    deduped: list[dict] = []
    for mover in movers:
        if mover["symbol"] in seen:
            continue
        seen.add(mover["symbol"])
        deduped.append(mover)
    return deduped
