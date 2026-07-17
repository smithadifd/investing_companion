"""Health endpoint auth gating (fix #5), integration-level.

Requires the test DB (uses the client fixture), so it is skipped where
TimescaleDB/Redis aren't available.
"""


class TestHealthGate:
    async def test_basic_health_is_public(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in {"healthy", "degraded"}
        assert "checks" not in body  # basic variant leaks nothing

    async def test_detailed_requires_auth(self, client):
        resp = await client.get("/health", params={"detailed": "true"})
        assert resp.status_code == 401

    async def test_detailed_with_auth_allowed(self, authed_client):
        resp = await authed_client.get("/health", params={"detailed": "true"})
        assert resp.status_code == 200
        assert "checks" in resp.json()
