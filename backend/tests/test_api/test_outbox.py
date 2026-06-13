"""Tests for the context pack outbox (service + endpoints)."""

import os
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.context_pack_outbox import ContextPackOutboxService
from tests.factories import create_test_alert, create_test_equity


async def _seed(db: AsyncSession):
    equity = await create_test_equity(db, symbol="OBX1", name="Outbox Corp")
    await create_test_alert(
        db, equity, name="OBX1 alert", condition_type="below",
        threshold_value=95.0, last_checked_value=96.0,
    )
    await db.flush()


class TestOutboxService:
    async def test_status_not_configured(self, db: AsyncSession, monkeypatch):
        monkeypatch.setattr(settings, "CONTEXT_PACK_OUTBOX_DIR", "")
        status = ContextPackOutboxService.status()
        assert status.configured is False
        assert status.dir is None
        assert status.last_published_at is None

    async def test_status_configured_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "CONTEXT_PACK_OUTBOX_DIR", str(tmp_path))
        status = ContextPackOutboxService.status()
        assert status.configured is True
        assert status.dir == str(tmp_path)
        assert status.last_published_at is None

    async def test_publish_not_configured_raises_409(
        self, db: AsyncSession, test_user, monkeypatch
    ):
        monkeypatch.setattr(settings, "CONTEXT_PACK_OUTBOX_DIR", "")
        service = ContextPackOutboxService(db)
        with pytest.raises(HTTPException) as exc:
            await service.publish(test_user.id)
        assert exc.value.status_code == 409

    async def test_publish_writes_latest_and_history(
        self, db: AsyncSession, test_user, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "CONTEXT_PACK_OUTBOX_DIR", str(tmp_path))
        await _seed(db)
        service = ContextPackOutboxService(db)

        result = await service.publish(test_user.id)

        latest = tmp_path / "latest.md"
        assert latest.exists()
        body = latest.read_text(encoding="utf-8")
        assert body.startswith("# IC Context Pack")
        assert "OBX1 alert" in body
        # one history snapshot with the same content
        history_files = list((tmp_path / "history").glob("*.md"))
        assert len(history_files) == 1
        assert history_files[0].read_text(encoding="utf-8") == body
        assert result.latest_path == str(latest)
        # no leftover temp file
        assert not (tmp_path / "latest.md.tmp").exists()

        # status now reports the publish
        status = ContextPackOutboxService.status()
        assert status.last_published_at is not None

    async def test_republish_overwrites_latest(
        self, db: AsyncSession, test_user, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "CONTEXT_PACK_OUTBOX_DIR", str(tmp_path))
        await _seed(db)
        service = ContextPackOutboxService(db)

        await service.publish(test_user.id)
        await service.publish(test_user.id)

        # a single canonical latest.md, no temp residue
        assert (tmp_path / "latest.md").exists()
        assert not (tmp_path / "latest.md.tmp").exists()
        # at least one history entry (same minute => same filename, overwritten)
        assert list((tmp_path / "history").glob("*.md"))

    async def test_prune_removes_old_history(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "CONTEXT_PACK_HISTORY_RETENTION_DAYS", 30)
        history = tmp_path / "history"
        history.mkdir()
        old = history / "20200101_0900.md"
        old.write_text("old", encoding="utf-8")
        fresh = history / "20990101_0900.md"
        fresh.write_text("fresh", encoding="utf-8")
        # backdate the old file well past the retention window
        old_ts = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
        os.utime(old, (old_ts, old_ts))

        ContextPackOutboxService._prune_history(history)

        assert not old.exists()
        assert fresh.exists()

    async def test_copy_reference_docs(self, tmp_path, monkeypatch):
        ref_src = tmp_path / "src"
        ref_src.mkdir()
        (ref_src / "handoff-schema.md").write_text("schema", encoding="utf-8")
        (ref_src / "advisor-actions.md").write_text("actions", encoding="utf-8")
        outbox = tmp_path / "outbox"
        outbox.mkdir()
        monkeypatch.setattr(settings, "CONTEXT_PACK_REFERENCE_DIR", str(ref_src))

        ContextPackOutboxService._copy_reference_docs(outbox)

        assert (outbox / "reference" / "handoff-schema.md").read_text() == "schema"
        assert (outbox / "reference" / "advisor-actions.md").read_text() == "actions"


class TestOutboxEndpoints:
    async def test_publish_requires_auth(self, client: AsyncClient):
        response = await client.post("/api/v1/export/context-pack/publish")
        assert response.status_code == 401

    async def test_publish_409_when_unconfigured(
        self, authed_client: AsyncClient, monkeypatch
    ):
        monkeypatch.setattr(settings, "CONTEXT_PACK_OUTBOX_DIR", "")
        response = await authed_client.post("/api/v1/export/context-pack/publish")
        assert response.status_code == 409

    async def test_publish_201_when_configured(
        self, authed_client: AsyncClient, db: AsyncSession, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "CONTEXT_PACK_OUTBOX_DIR", str(tmp_path))
        await _seed(db)
        response = await authed_client.post("/api/v1/export/context-pack/publish")

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["latest_path"] == str(tmp_path / "latest.md")
        assert (tmp_path / "latest.md").exists()

    async def test_publish_blocked_in_demo(
        self, authed_client: AsyncClient, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "CONTEXT_PACK_OUTBOX_DIR", str(tmp_path))
        monkeypatch.setattr(settings, "DEMO_MODE", True)
        response = await authed_client.post("/api/v1/export/context-pack/publish")
        assert response.status_code == 403

    async def test_outbox_status_requires_auth(self, client: AsyncClient):
        response = await client.get("/api/v1/export/outbox-status")
        assert response.status_code == 401

    async def test_outbox_status_endpoint(
        self, authed_client: AsyncClient, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "CONTEXT_PACK_OUTBOX_DIR", str(tmp_path))
        response = await authed_client.get("/api/v1/export/outbox-status")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["configured"] is True
        assert data["dir"] == str(tmp_path)


class TestOutboxTask:
    def test_publish_task_skips_when_unconfigured(self, monkeypatch):
        """The daily-drop task is a no-op (and never touches the DB) when no
        outbox is configured, so it is safe to leave wired before enabling."""
        monkeypatch.setattr(settings, "CONTEXT_PACK_OUTBOX_DIR", "")
        from app.tasks.export import publish_context_pack

        assert publish_context_pack() == {"skipped": "outbox_not_configured"}
