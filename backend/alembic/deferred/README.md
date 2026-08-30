# `alembic/deferred/` — migrations written but deliberately NOT in the chain

Files in this directory are **not** migrations as far as Alembic is concerned.
`script_location = alembic` + the default `version_locations` means Alembic only
reads `alembic/versions/`; this is a sibling directory, so nothing here is ever
picked up by `alembic upgrade head`, `alembic heads`, or autogenerate. That is
the entire point: a migration lives here when the DDL is written and reviewed
but applying it needs a decision that a PR cannot make on its own (typically:
"does prod data actually satisfy this?").

Keeping it as a file rather than a paragraph in a PR body means the DDL is
reviewed once, in context, and the promotion step is a `git mv` rather than a
rewrite from memory.

## Promoting a deferred migration

1. Run whatever pre-check the file's docstring names, against the target DB, and
   confirm it comes back clean. If it does not, the decision is a data fix
   first — not a promotion.
2. `git mv backend/alembic/deferred/<file>.py backend/alembic/versions/<file>.py`
3. Re-point `down_revision` at the **current** head (`alembic heads`); the value
   in the file is the head at authoring time and is almost certainly stale.
   Re-date the revision id / filename to the promotion date if the house
   `YYYYMMDD_NNN` scheme would otherwise sort it wrong.
4. Add the matching constraint/column to the SQLAlchemy model in
   `backend/app/db/models/` **in the same PR** — the model is the schema source
   of truth (AGENTS.md § Database) and the test suite builds its schema from it,
   so a promoted migration with no model change silently diverges.
5. Add the regression test that proves the new DB-level behavior, then confirm
   a single head: `alembic heads` returns exactly one revision.

## Current contents

| File | Blocked on |
|------|------------|
| `20260729_002_add_trade_price_check.py` | A prod-data answer: does any `trades` row legitimately carry `price = 0` (vested RSU / gift / spin-off) before `price > 0` can be enforced? Run `backend/scripts/check_trade_constraint_violations.py` against prod; its PRICE section is the input to that call. |
| `20260830_006_add_trade_type_shape_checks.py` | A prod-data answer: are there `split` rows with a price/account/fees, `dividend` rows with no account, or `deposit`/`withdrawal` rows in `trades`? The docstring carries the exact counting query. Note it makes the strict `price > 0` variant of `20260729_002` permanently wrong — a split's price is a designed 0. |
