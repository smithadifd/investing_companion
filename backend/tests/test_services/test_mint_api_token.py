"""The mint script prints the token once, stores only its hash, never logs it."""

import logging

from sqlalchemy import select

from app.db.models.api_token import ApiToken
from app.services.api_token import ApiTokenService, hash_api_token
from scripts import mint_api_token


async def test_mint_prints_token_once_and_stores_only_hash(db, test_user, capsys, caplog):
    caplog.set_level(logging.DEBUG)

    code = await mint_api_token.run(
        db, ["mint", "--user", test_user.email, "--name", "advisor pull"]
    )
    out, err = capsys.readouterr()

    assert code == 0
    lines = out.splitlines()
    assert len(lines) == 1, "stdout must carry the token and nothing else"
    token = lines[0]
    assert token.startswith("ict_")
    secret = token.split("_", 2)[2]

    row = (
        await db.execute(select(ApiToken).where(ApiToken.user_id == test_user.id))
    ).scalar_one()
    assert row.scopes == ["pack:read"]
    assert row.name == "advisor pull"
    assert row.token_hash == hash_api_token(token)
    assert token not in row.token_hash
    assert row.token_prefix in err

    for text in (err, caplog.text):
        assert token not in text
        assert secret not in text

    # The printed token authenticates.
    assert (await ApiTokenService(db).authenticate(token)).id == row.id


async def test_mint_by_user_id_with_expiry(db, test_user, capsys):
    code = await mint_api_token.run(
        db,
        ["mint", "--user", str(test_user.id), "--name", "ci", "--expires-days", "30"],
    )
    capsys.readouterr()
    assert code == 0
    row = (
        await db.execute(select(ApiToken).where(ApiToken.user_id == test_user.id))
    ).scalar_one()
    assert row.expires_at is not None


async def test_mint_rejects_unknown_scope_and_unknown_user(db, test_user, capsys):
    assert await mint_api_token.run(
        db, ["mint", "--user", test_user.email, "--name", "x", "--scope", "trades:write"]
    ) == 1
    assert await mint_api_token.run(
        db, ["mint", "--user", "nobody@example.com", "--name", "x"]
    ) == 1
    out, _ = capsys.readouterr()
    assert out == ""
    rows = (await db.execute(select(ApiToken))).scalars().all()
    assert rows == []


async def test_revoke_by_prefix_and_by_pasted_token(db, test_user, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    service = ApiTokenService(db)
    row1, token1 = await service.create(test_user.id, "one", ["pack:read"])
    row2, token2 = await service.create(test_user.id, "two", ["pack:read"])

    assert await mint_api_token.run(db, ["revoke", row1.token_prefix]) == 0
    assert await mint_api_token.run(db, ["revoke", token2]) == 0
    out, err = capsys.readouterr()

    await db.refresh(row1)
    await db.refresh(row2)
    assert row1.revoked_at is not None
    assert row2.revoked_at is not None
    assert await service.authenticate(token1) is None
    assert await service.authenticate(token2) is None
    for text in (out, err, caplog.text):
        assert token1 not in text
        assert token2 not in text


async def test_revoke_unknown_does_not_echo_input(db, capsys):
    pasted = "ict_0123abcd_" + "s" * 43
    assert await mint_api_token.run(db, ["revoke", pasted]) == 1
    out, err = capsys.readouterr()
    assert pasted not in out + err


async def test_list_shows_no_secret(db, test_user, capsys):
    row, token = await ApiTokenService(db).create(test_user.id, "listed", ["pack:read"])
    assert await mint_api_token.run(db, ["list", "--user", test_user.email]) == 0
    out, _ = capsys.readouterr()
    assert row.token_prefix in out
    assert token not in out
