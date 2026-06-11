"""Tests for handoff execution receipts."""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.handoff import HandoffActionResult, HandoffReceiptCreate
from app.services.context_pack import ContextPackService
from app.services.handoff import HandoffService


def _receipt() -> HandoffReceiptCreate:
    return HandoffReceiptCreate(
        summary="Test handoff block",
        actions=[
            HandoffActionResult(action="ADD_ALERT", target="KTOS", result="applied", detail="id 1"),
            HandoffActionResult(action="ADD_TO_WATCHLIST", target="RCAT", result="skipped", detail="amendment"),
            HandoffActionResult(action="ADD_RATIO", target="USD/JPY", result="flagged", detail="unsupported"),
        ],
    )


class TestHandoffService:
    async def test_record_counts_results(self, db: AsyncSession, test_user):
        service = HandoffService(db)

        receipt = await service.record(_receipt(), user_id=test_user.id)

        assert receipt.applied_count == 1
        assert receipt.skipped_count == 1
        assert receipt.flagged_count == 1
        assert receipt.actions[0].target == "KTOS"

    async def test_receipts_appear_in_context_pack(self, db: AsyncSession, test_user):
        await HandoffService(db).record(_receipt(), user_id=test_user.id)

        pack = await ContextPackService(db).build(test_user.id)

        assert pack.schema_version == "1.1"
        assert len(pack.recent_handoffs) == 1
        assert pack.recent_handoffs[0].summary == "Test handoff block"
        assert pack.recent_handoffs[0].applied_count == 1


class TestHandoffEndpoint:
    async def test_requires_auth(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/export/handoff-receipts", json=_receipt().model_dump()
        )
        assert response.status_code == 401

    async def test_creates_receipt(self, authed_client: AsyncClient):
        response = await authed_client.post(
            "/api/v1/export/handoff-receipts", json=_receipt().model_dump()
        )

        assert response.status_code == 201
        body = response.json()
        assert body["applied_count"] == 1
        assert body["source"] == "investing_hub"

    async def test_rejects_bad_result_value(self, authed_client: AsyncClient):
        payload = _receipt().model_dump()
        payload["actions"][0]["result"] = "exploded"

        response = await authed_client.post(
            "/api/v1/export/handoff-receipts", json=payload
        )
        assert response.status_code == 422
