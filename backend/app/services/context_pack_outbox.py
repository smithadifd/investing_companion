"""Context pack outbox - publish the pack to a local dir for the Drive bridge.

Writes a self-describing snapshot the claude.ai "IC Advisor" Project reads via
its Google Drive connector. A host-side ``rclone`` job syncs the directory up;
the app never holds Google credentials. The write is atomic (``.tmp`` -> rename)
so the sync never picks up a half-written ``latest.md``.

See ``docs/api/handoff-schema.md`` for the pack contract and the master bridge
plan for the host/Project wiring.
"""

import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.context_pack import ContextPackService, render_markdown

logger = logging.getLogger(__name__)

# History snapshots are stamped in ET so "one per day" lines up with the user's
# trading day rather than UTC midnight. Fall back to UTC if tzdata is missing
# (e.g. on slim container images without the timezone database).
try:
    _ET = ZoneInfo("America/New_York")
except ZoneInfoNotFoundError:  # pragma: no cover - environment dependent
    _ET = timezone.utc

# Advisor contract docs copied into <outbox>/reference/ when a source dir is set.
_REFERENCE_DOCS = ("handoff-schema.md", "advisor-actions.md")


@dataclass
class OutboxResult:
    latest_path: str
    history_path: str
    generated_at: datetime


@dataclass
class OutboxStatus:
    configured: bool
    dir: Optional[str]
    last_published_at: Optional[datetime]
    last_file: Optional[str]


class ContextPackOutboxService:
    """Publishes the rendered context pack to the configured outbox directory."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.pack_service = ContextPackService(db)

    @staticmethod
    def _outbox_dir() -> Optional[Path]:
        raw = settings.CONTEXT_PACK_OUTBOX_DIR.strip()
        return Path(raw) if raw else None

    @classmethod
    def is_configured(cls) -> bool:
        return cls._outbox_dir() is not None

    @classmethod
    def status(cls) -> OutboxStatus:
        outbox = cls._outbox_dir()
        if outbox is None:
            return OutboxStatus(
                configured=False, dir=None, last_published_at=None, last_file=None
            )
        latest = outbox / "latest.md"
        last_published_at: Optional[datetime] = None
        last_file: Optional[str] = None
        if latest.exists():
            last_published_at = datetime.fromtimestamp(
                latest.stat().st_mtime, tz=timezone.utc
            )
            last_file = str(latest)
        return OutboxStatus(
            configured=True,
            dir=str(outbox),
            last_published_at=last_published_at,
            last_file=last_file,
        )

    async def publish(self, user_id: UUID) -> OutboxResult:
        outbox = self._outbox_dir()
        if outbox is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Context pack outbox is not configured "
                    "(set CONTEXT_PACK_OUTBOX_DIR on the server)."
                ),
            )

        pack = await self.pack_service.build(user_id)
        markdown = render_markdown(pack)

        try:
            history_dir = outbox / "history"
            history_dir.mkdir(parents=True, exist_ok=True)

            latest = outbox / "latest.md"
            self._atomic_write(latest, markdown)

            stamp = pack.generated_at.astimezone(_ET).strftime("%Y%m%d_%H%M")
            history_file = history_dir / f"{stamp}.md"
            self._atomic_write(history_file, markdown)

            self._prune_history(history_dir)
            self._copy_reference_docs(outbox)
        except OSError as e:
            logger.error("Context pack publish failed: %s", e, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to write the context pack to the outbox.",
            )

        return OutboxResult(
            latest_path=str(latest),
            history_path=str(history_file),
            generated_at=pack.generated_at,
        )

    @staticmethod
    def _atomic_write(target: Path, content: str) -> None:
        """Write via a temp file + rename so readers never see a partial file."""
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, target)

    @staticmethod
    def _prune_history(history_dir: Path) -> None:
        retention_days = settings.CONTEXT_PACK_HISTORY_RETENTION_DAYS
        if retention_days <= 0:
            return
        cutoff = datetime.now(timezone.utc).timestamp() - retention_days * 86400
        for f in history_dir.glob("*.md"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                logger.warning("Could not prune outbox history file %s", f)

    @staticmethod
    def _copy_reference_docs(outbox: Path) -> None:
        ref_src = settings.CONTEXT_PACK_REFERENCE_DIR.strip()
        if not ref_src:
            return
        src_dir = Path(ref_src)
        if not src_dir.is_dir():
            return
        dest_dir = outbox / "reference"
        dest_dir.mkdir(parents=True, exist_ok=True)
        for name in _REFERENCE_DOCS:
            src = src_dir / name
            if src.is_file():
                try:
                    shutil.copyfile(src, dest_dir / name)
                except OSError:
                    logger.warning("Could not copy reference doc %s to outbox", name)
