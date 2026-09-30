#!/usr/bin/env python3
"""Mint, list or revoke read-only API tokens.

An API token lets a script or external tool fetch the context pack
(``GET /api/v1/export/context-pack``) and the outbox status without a login
session. It is sent as ``Authorization: Bearer ict_...`` and is refused (403)
on every other endpoint.

The plaintext token is printed ONCE, alone, on stdout - capture it then; only
its hash is stored and it cannot be shown again. Everything else (the token's
id, prefix, scopes) goes to stderr, so ``TOKEN=$(python ... mint ...)`` works.

Usage::

    cd backend

    # mint (scope defaults to pack:read)
    python -m scripts.mint_api_token mint --user you@example.com --name "advisor pull"
    python -m scripts.mint_api_token mint --user <user-uuid> --name ci --expires-days 90

    # list a user's tokens (never shows the secret)
    python -m scripts.mint_api_token list --user you@example.com

    # revoke by token id or by its 8-character prefix
    python -m scripts.mint_api_token revoke <id|prefix>

Exit codes: 0 ok, 1 not found / invalid input.
"""

import argparse
import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow `python backend/scripts/mint_api_token.py` from the repo root too.
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.api_token_access import SCOPE_PACK_READ, is_api_token  # noqa: E402
from app.db.models.user import User  # noqa: E402
from app.services.api_token import (  # noqa: E402
    ApiTokenService,
    InvalidScopeError,
    parse_api_token_prefix,
)
from app.services.auth import AuthService  # noqa: E402


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


async def _resolve_user(db: AsyncSession, ref: str) -> User | None:
    auth = AuthService(db)
    try:
        return await auth.get_user_by_id(uuid.UUID(ref))
    except ValueError:
        return await auth.get_user_by_email(ref)


async def _cmd_mint(db: AsyncSession, args: argparse.Namespace) -> int:
    user = await _resolve_user(db, args.user)
    if user is None:
        _err(f"No user matches {args.user!r}")
        return 1
    expires_at = None
    if args.expires_days is not None:
        if args.expires_days <= 0:
            _err("--expires-days must be positive")
            return 1
        expires_at = datetime.now(timezone.utc) + timedelta(days=args.expires_days)

    scopes = args.scope or [SCOPE_PACK_READ]
    try:
        row, plaintext = await ApiTokenService(db).create(
            user.id, args.name, scopes, expires_at=expires_at
        )
    except InvalidScopeError as e:
        _err(str(e))
        return 1

    _err(
        f"Minted API token id={row.id} prefix={row.token_prefix} "
        f"scopes={','.join(row.scopes)} expires_at={row.expires_at or 'never'}"
    )
    _err("The token below is shown once. Store it now; it cannot be recovered.")
    print(plaintext)
    return 0


async def _cmd_list(db: AsyncSession, args: argparse.Namespace) -> int:
    user = await _resolve_user(db, args.user)
    if user is None:
        _err(f"No user matches {args.user!r}")
        return 1
    for row in await ApiTokenService(db).list_for_user(user.id):
        state = "revoked" if row.revoked_at else "active"
        print(
            f"{row.id}  {row.token_prefix}  {state:7}  {','.join(row.scopes):12}  "
            f"created={row.created_at:%Y-%m-%d}  "
            f"last_used={row.last_used_at or '-'}  expires={row.expires_at or 'never'}  "
            f"{row.name}"
        )
    return 0


async def _cmd_revoke(db: AsyncSession, args: argparse.Namespace) -> int:
    service = ApiTokenService(db)
    ref = args.token
    if is_api_token(ref):
        # Someone pasted the whole token: use its prefix, never echo it back.
        ref = parse_api_token_prefix(ref) or ""
    try:
        row = await service.get_by_id(uuid.UUID(ref))
    except ValueError:
        row = await service.get_by_prefix(ref)
    if row is None:
        _err("No API token matches that id or prefix")
        return 1
    await service.revoke(row)
    _err(f"Revoked API token id={row.id} prefix={row.token_prefix} at {row.revoked_at}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    mint = sub.add_parser("mint", help="create a token and print it once")
    mint.add_argument("--user", required=True, help="owning user's email or id")
    mint.add_argument("--name", required=True, help="human label, e.g. what uses it")
    mint.add_argument(
        "--scope", action="append",
        help=f"scope to grant (repeatable; default {SCOPE_PACK_READ})",
    )
    mint.add_argument("--expires-days", type=int, default=None)

    lst = sub.add_parser("list", help="list a user's tokens (no secrets)")
    lst.add_argument("--user", required=True, help="owning user's email or id")

    rev = sub.add_parser("revoke", help="revoke a token by id or prefix")
    rev.add_argument("token", help="token id (uuid) or 8-character prefix")
    return parser


_COMMANDS = {"mint": _cmd_mint, "list": _cmd_list, "revoke": _cmd_revoke}


async def run(db: AsyncSession, argv: list[str]) -> int:
    """Run one command against an open session (the testable entry point)."""
    args = build_parser().parse_args(argv)
    return await _COMMANDS[args.command](db, args)


async def main_async(argv: list[str]) -> int:
    from app.db.session import AsyncSessionLocal, engine

    try:
        async with AsyncSessionLocal() as db:
            return await run(db, argv)
    finally:
        await engine.dispose()


def main() -> int:
    return asyncio.run(main_async(sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())
