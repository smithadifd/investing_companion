"""The ``advisor:write`` API-token scope: allow-list matching and end-to-end writes."""

import pytest
from sqlalchemy import select

from app.core.api_token_access import (
    API_TOKEN_ROUTE_ALLOWLIST,
    API_TOKEN_ROUTE_DENIED_DETAIL,
    KNOWN_SCOPES,
    SCOPE_ADVISOR_WRITE,
    SCOPE_PACK_READ,
    required_scope,
    route_path,
)
from app.db.models.alert import Alert
from app.db.models.watchlist import WatchlistItem
from tests.factories import (
    create_test_alert,
    create_test_equity,
    create_test_trade,
    create_test_user,
    create_test_watchlist,
    create_test_watchlist_item,
)
from tests.test_api.test_route_guards import _bearer, _mint

A = "/api/v1"
W = SCOPE_ADVISOR_WRITE


def test_scope_is_known():
    assert W in KNOWN_SCOPES and SCOPE_PACK_READ in KNOWN_SCOPES


# ---------------------------------------------------------------------------
# Pure matching (no DB)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", f"{A}/alerts"),
        ("PUT", f"{A}/alerts/7"),
        ("DELETE", f"{A}/alerts/123456"),
        ("GET", f"{A}/alerts"),
        ("POST", f"{A}/watchlists/3/items"),
        ("PUT", f"{A}/watchlists/3/items/9"),
        ("POST", f"{A}/triggers/5/retire"),
        ("GET", f"{A}/events/3f2b8c1e-9d4a-4e7b-8c2f-1a5b6c7d8e9f"),
        ("PUT", f"{A}/events/3f2b8c1e-9d4a-4e7b-8c2f-1a5b6c7d8e9f"),
        ("DELETE", f"{A}/events/3F2B8C1E-9D4A-4E7B-8C2F-1A5B6C7D8E9F"),
        ("GET", f"{A}/equity/AAPL"),
        ("GET", f"{A}/equity/BRK.B"),
        ("GET", f"{A}/equity/^GSPC"),
        ("GET", f"{A}/equity/BF-B"),
        ("post", f"{A}/trades"),  # method case-insensitive
        ("GET", f"{A}/accounts"),
        ("POST", f"{A}/export/handoff-receipts"),
    ],
)
def test_allowed_paths_need_advisor_write(method, path):
    assert required_scope(method, path) == W


@pytest.mark.parametrize(
    "method,path",
    [
        ("PUT", f"{A}/alerts/abc"),             # non-digit id
        ("PUT", f"{A}/alerts/"),                # empty id / trailing slash
        ("PUT", f"{A}/alerts/1a"),
        ("PUT", f"{A}/alerts/-1"),
        ("PUT", f"{A}/alerts/1.0"),
        ("PUT", f"{A}/alerts/٣"),          # non-ASCII digit
        ("PUT", f"{A}/alerts/{{id}}"),          # the template text itself
        ("PUT", f"{A}/alerts/1/extra"),         # extra segment
        ("PUT", f"{A}/alerts/1/"),              # trailing slash
        ("POST", f"{A}/alerts/1/toggle"),       # not in the table
        ("POST", f"{A}/alerts/1/check"),
        ("GET", f"{A}/alerts/1"),               # method not allowed for template
        ("GET", f"{A}/alerts/stats"),
        ("POST", f"{A}/alerts/1"),              # method mismatch
        ("PATCH", f"{A}/alerts/1"),
        ("PUT", f"{A}/alerts"),                 # method mismatch on literal
        ("POST", f"{A}/alertsX"),
        ("POST", f"{A}/alerts/extra"),
        ("PUT", f"{A}/watchlists/3/items"),
        ("DELETE", f"{A}/watchlists/3/items/9"),  # delete item not allowed
        ("DELETE", f"{A}/watchlists/3"),
        ("PUT", f"{A}/watchlists/3"),
        ("POST", f"{A}/watchlists/import"),
        ("GET", f"{A}/watchlists/movers"),
        ("POST", f"{A}/watchlists/3/items/9"),
        ("PUT", f"{A}/watchlists/x/items/9"),
        ("PUT", f"{A}/watchlists/3/items/x"),
        ("PUT", f"{A}/trades/1"),               # trades: create only
        ("DELETE", f"{A}/trades/1"),
        ("GET", f"{A}/trades"),
        ("POST", f"{A}/accounts"),
        ("PUT", f"{A}/accounts/1"),
        ("POST", f"{A}/cash/deposit"),
        ("POST", f"{A}/triggers/1/execute"),
        ("POST", f"{A}/triggers/1/rearm"),
        ("DELETE", f"{A}/triggers/1"),
        ("PUT", f"{A}/settings"),
        ("GET", f"{A}/settings"),
        ("POST", f"{A}/auth/login"),
        ("POST", f"{A}/auth/logout"),
        ("GET", f"{A}/equity/search"),          # lowercase is not a symbol
        ("GET", f"{A}/equity/aapl"),
        ("GET", f"{A}/equity/.."),
        ("GET", f"{A}/equity/."),
        ("GET", f"{A}/equity/AAPL/quote"),
        ("GET", f"{A}/equity/AAPL/history"),
        ("GET", f"{A}/equity/AA PL"),
        ("GET", f"{A}/equity/"),
        ("POST", f"{A}/events/refresh/AAPL"),
        ("DELETE", f"{A}/events/equity/AAPL"),
        ("POST", f"{A}/export/context-pack/publish"),
        ("GET", f"/prefix{A}/alerts"),          # prefix match must not work
        ("GET", f"{A}/alerts/../settings"),
        ("GET", "/health"),
    ],
)
def test_denied_paths(method, path):
    assert required_scope(method, path) is None


def test_literal_scope_assignments_unchanged():
    assert required_scope("GET", f"{A}/export/context-pack") == SCOPE_PACK_READ
    assert required_scope("GET", f"{A}/export/outbox-status") == SCOPE_PACK_READ
    assert required_scope("GET", f"{A}/export/contract-docs") == SCOPE_PACK_READ


def test_no_trade_mutation_or_account_creation_in_table():
    table = set(API_TOKEN_ROUTE_ALLOWLIST)
    for forbidden in (
        ("PUT", f"{A}/trades/{{id}}"),
        ("DELETE", f"{A}/trades/{{id}}"),
        ("POST", f"{A}/accounts"),
        ("POST", f"{A}/cash"),
    ):
        assert forbidden not in table


def test_route_path_root_path_then_template_match():
    scope = {"path": f"/invest{A}/alerts/5", "root_path": "/invest"}
    assert required_scope("PUT", route_path(scope)) == W
    # a root_path that is not a segment-boundary prefix is not stripped
    scope = {"path": f"/investx{A}/alerts/5", "root_path": "/invest"}
    assert required_scope("PUT", route_path(scope)) is None


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------
async def _write_token(db, user):
    return (await _mint(db, user, scopes=(SCOPE_PACK_READ, W)))[1]


ALERT = {
    "name": "AAPL above 200",
    "condition_type": "above",
    "threshold_value": "200",
    "equity_symbol": "AAPL",
}


async def test_pack_read_only_token_refused_on_write_routes(client, db, test_user):
    token = (await _mint(db, test_user))[1]
    for method, path in [
        ("POST", f"{A}/alerts"),
        ("PUT", f"{A}/alerts/1"),
        ("DELETE", f"{A}/alerts/1"),
        ("POST", f"{A}/watchlists/1/items"),
        ("PUT", f"{A}/watchlists/1/items/1"),
        ("POST", f"{A}/trades"),
        ("POST", f"{A}/triggers"),
        ("POST", f"{A}/lessons"),
        ("POST", f"{A}/export/handoff-receipts"),
        ("GET", f"{A}/accounts"),
        ("GET", f"{A}/alerts"),
    ]:
        resp = await client.request(method, path, headers=_bearer(token), json={})
        assert resp.status_code == 403, (method, path)
        assert resp.json()["detail"] == "API token lacks the required scope"


async def test_advisor_write_token_creates_and_modifies_alert_for_owner(
    client, db, test_user
):
    await create_test_equity(db, symbol="AAPL")
    other = await create_test_user(db, email="other@example.com")
    token = await _write_token(db, test_user)

    created = await client.post(f"{A}/alerts", json=ALERT, headers=_bearer(token))
    assert created.status_code == 201, created.text
    alert_id = created.json()["data"]["id"]
    row = (await db.execute(select(Alert).where(Alert.id == alert_id))).scalar_one()
    assert row.user_id == test_user.id and row.user_id != other.id

    updated = await client.put(
        f"{A}/alerts/{alert_id}", json={"threshold_value": "250"}, headers=_bearer(token)
    )
    assert updated.status_code == 200, updated.text

    listed = await client.get(f"{A}/alerts", headers=_bearer(token))
    assert listed.status_code == 200
    assert alert_id in [a["id"] for a in listed.json()["data"]]

    deleted = await client.delete(f"{A}/alerts/{alert_id}", headers=_bearer(token))
    assert deleted.status_code == 204


async def test_advisor_write_token_cannot_touch_another_users_alert(client, db, test_user):
    equity = await create_test_equity(db, symbol="AAPL")
    other = await create_test_user(db, email="other@example.com")
    theirs = await create_test_alert(db, equity, user_id=other.id)
    token = await _write_token(db, test_user)
    resp = await client.put(
        f"{A}/alerts/{theirs.id}", json={"notes": "x"}, headers=_bearer(token)
    )
    assert resp.status_code == 404
    resp = await client.delete(f"{A}/alerts/{theirs.id}", headers=_bearer(token))
    assert resp.status_code == 404


async def test_advisor_write_token_updates_watchlist_item(client, db, test_user):
    equity = await create_test_equity(db, symbol="MSFT")
    watchlist = await create_test_watchlist(db, user_id=test_user.id)
    item = await create_test_watchlist_item(db, watchlist, equity)
    token = await _write_token(db, test_user)

    resp = await client.put(
        f"{A}/watchlists/{watchlist.id}/items/{item.id}",
        json={"thesis": "updated by advisor", "target_price": "410"},
        headers=_bearer(token),
    )
    assert resp.status_code == 200, resp.text
    row = (
        await db.execute(select(WatchlistItem).where(WatchlistItem.id == item.id))
    ).scalar_one()
    await db.refresh(row)
    assert row.thesis == "updated by advisor"

    got = await client.get(f"{A}/watchlists/{watchlist.id}", headers=_bearer(token))
    assert got.status_code == 200


async def test_advisor_write_token_still_refused_elsewhere(client, db, test_user):
    equity = await create_test_equity(db, symbol="AAPL")
    trade = await create_test_trade(db, equity, test_user)
    token = await _write_token(db, test_user)
    denied = [
        ("DELETE", f"{A}/trades/{trade.id}"),
        ("PUT", f"{A}/trades/{trade.id}"),
        ("POST", f"{A}/accounts"),
        ("POST", f"{A}/cash/deposit"),
        ("GET", f"{A}/settings"),
        ("PUT", f"{A}/settings"),
        ("POST", f"{A}/auth/login"),
        ("POST", f"{A}/auth/logout-all"),
        ("GET", f"{A}/auth/me"),
        ("POST", f"{A}/triggers/1/execute"),
        ("DELETE", f"{A}/watchlists/1"),
    ]
    for method, path in denied:
        resp = await client.request(method, path, headers=_bearer(token), json={})
        assert resp.status_code == 403, (method, path)
        assert resp.json()["detail"] == API_TOKEN_ROUTE_DENIED_DETAIL


async def test_advisor_write_token_blocked_in_demo_mode(client, db, test_user, monkeypatch):
    monkeypatch.setattr("app.core.demo.is_demo_mode", lambda: True)
    token = await _write_token(db, test_user)
    resp = await client.post(f"{A}/alerts", json=ALERT, headers=_bearer(token))
    assert resp.status_code == 403
    assert "demo" in resp.json()["detail"].lower()


@pytest.mark.parametrize(
    "path",
    [
        f"{A}/events/2",  # events are UUID-keyed; an integer is not an event id
        f"{A}/events/3f2b8c1e-9d4a-4e7b-8c2f-1a5b6c7d8e9fx",
        f"{A}/events/3f2b8c1e9d4a4e7b8c2f1a5b6c7d8e9f",  # unhyphenated
        f"{A}/events/{{3f2b8c1e-9d4a-4e7b-8c2f-1a5b6c7d8e9f}}",  # braced
        f"{A}/events/3f2b8c1e-9d4a-4e7b-8c2f-1a5b6c7d8e9g",
        f"{A}/events/3f2b8c1e-9d4a-4e7b-8c2f-1a5b6c7d8e9f/extra",
    ],
)
def test_event_uuid_template_matches_canonical_uuids_only(path):
    assert required_scope("PUT", path) is None
