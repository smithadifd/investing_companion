"""GET /api/v1/export/contract-docs - the contract docs, from the deployed app."""

from pathlib import Path

from app.core.api_token_access import SCOPE_PACK_READ
from app.core.config import settings
from app.schemas.context_pack import ADVISOR_ACTIONS_VERSION, SCHEMA_VERSION
from app.services.contract_docs import (
    contract_docs_dir,
    parse_advisor_actions_stamp,
    parse_handoff_schema_stamp,
)
from app.services.api_token import ApiTokenService
from tests.test_api.test_route_guards import _bearer, _raw_token

URL = "/api/v1/export/contract-docs"


def _write_docs(directory: Path, schema_version: str, actions_version: str) -> None:
    (directory / "handoff-schema.md").write_text(
        f"# Handoff Loop Schema (v{schema_version})\n\nbody\n", encoding="utf-8"
    )
    (directory / "advisor-actions.md").write_text(
        f"# Advisor Action Vocabulary\n\n**`advisor_actions_version`: {actions_version}** - x\n",
        encoding="utf-8",
    )


def test_parsers():
    assert parse_handoff_schema_stamp("# Handoff Loop Schema (v2.10)\n") == "2.10"
    assert parse_handoff_schema_stamp("# No stamp here\n") is None
    assert parse_advisor_actions_stamp("**`advisor_actions_version`: 3.4** - x") == "3.4"
    assert parse_advisor_actions_stamp("advisor_actions_version: 3.4") is None


async def test_jwt_user_gets_both_docs_with_matching_stamps(authed_client, tmp_path, monkeypatch):
    _write_docs(tmp_path, SCHEMA_VERSION, ADVISOR_ACTIONS_VERSION)
    monkeypatch.setattr(settings, "CONTRACT_DOCS_DIR", str(tmp_path))

    resp = await authed_client.get(URL)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["schema_version"] == SCHEMA_VERSION
    assert body["advisor_actions_version"] == ADVISOR_ACTIONS_VERSION
    assert body["handoff_schema"]["filename"] == "handoff-schema.md"
    assert body["handoff_schema"]["stamp"] == SCHEMA_VERSION
    assert body["handoff_schema"]["stamp_matches"] is True
    assert body["advisor_actions"]["filename"] == "advisor-actions.md"
    assert body["advisor_actions"]["stamp"] == ADVISOR_ACTIONS_VERSION
    assert body["advisor_actions"]["stamp_matches"] is True
    assert "body" in body["handoff_schema"]["content"]


async def test_default_dir_serves_the_repo_docs_verbatim(authed_client):
    """With no override the endpoint serves docs/api/ byte-for-byte."""
    resp = await authed_client.get(URL)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    docs = contract_docs_dir()
    for key, name, parse, expected in (
        ("handoff_schema", "handoff-schema.md", parse_handoff_schema_stamp, SCHEMA_VERSION),
        ("advisor_actions", "advisor-actions.md", parse_advisor_actions_stamp,
         ADVISOR_ACTIONS_VERSION),
    ):
        text = (docs / name).read_text(encoding="utf-8")
        assert body[key]["content"] == text
        assert body[key]["stamp"] == parse(text) is not None
        assert body[key]["expected_stamp"] == expected
        assert body[key]["stamp_matches"] == (body[key]["stamp"] == expected)
    # Outcome: the repo docs served by the default dir carry exactly the
    # versions the pack emits.
    assert body["handoff_schema"]["stamp"] == SCHEMA_VERSION
    assert body["advisor_actions"]["stamp"] == ADVISOR_ACTIONS_VERSION
    assert body["handoff_schema"]["stamp_matches"] is True
    assert body["advisor_actions"]["stamp_matches"] is True


async def test_pack_read_token_gets_docs(client, db, test_user, tmp_path, monkeypatch):
    _write_docs(tmp_path, SCHEMA_VERSION, ADVISOR_ACTIONS_VERSION)
    monkeypatch.setattr(settings, "CONTRACT_DOCS_DIR", str(tmp_path))
    _, token = await ApiTokenService(db).create(test_user.id, "t", [SCOPE_PACK_READ])

    resp = await client.get(URL, headers=_bearer(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["handoff_schema"]["stamp_matches"] is True


async def test_unauthenticated_is_401(client):
    assert (await client.get(URL)).status_code == 401


async def test_token_without_pack_read_is_403(client, db, test_user):
    token = await _raw_token(db, test_user, [])
    assert (await client.get(URL, headers=_bearer(token))).status_code == 403


async def test_stamp_mismatch_is_served_and_flagged(authed_client, tmp_path, monkeypatch):
    _write_docs(tmp_path, "0.1", "0.2")
    monkeypatch.setattr(settings, "CONTRACT_DOCS_DIR", str(tmp_path))

    resp = await authed_client.get(URL)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["handoff_schema"]["stamp"] == "0.1"
    assert body["handoff_schema"]["stamp_matches"] is False
    assert body["advisor_actions"]["stamp"] == "0.2"
    assert body["advisor_actions"]["stamp_matches"] is False


async def test_unparseable_stamp_is_null_and_flagged(authed_client, tmp_path, monkeypatch):
    _write_docs(tmp_path, SCHEMA_VERSION, ADVISOR_ACTIONS_VERSION)
    (tmp_path / "advisor-actions.md").write_text("no stamp\n", encoding="utf-8")
    monkeypatch.setattr(settings, "CONTRACT_DOCS_DIR", str(tmp_path))

    body = (await authed_client.get(URL)).json()
    assert body["advisor_actions"]["stamp"] is None
    assert body["advisor_actions"]["stamp_matches"] is False
    assert body["handoff_schema"]["stamp_matches"] is True


async def test_missing_doc_is_503_with_message(authed_client, tmp_path, monkeypatch):
    _write_docs(tmp_path, SCHEMA_VERSION, ADVISOR_ACTIONS_VERSION)
    (tmp_path / "advisor-actions.md").unlink()
    monkeypatch.setattr(settings, "CONTRACT_DOCS_DIR", str(tmp_path))

    resp = await authed_client.get(URL)
    assert resp.status_code == 503
    assert "advisor-actions.md" in resp.json()["detail"]
