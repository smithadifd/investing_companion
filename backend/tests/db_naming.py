"""Test-database name/URL derivation — worktree-safe, fail-closed.

Each checkout of this repo (a git worktree or a separate clone) needs its own
test database, otherwise two concurrent suites collide: ``backend/tests/
conftest.py`` runs ``Base.metadata.create_all``/``drop_all`` against a shared
database, so one run's ``drop_all()`` can rip tables out from under another
run mid-test.

This module is pure (no DB connection, no pytest fixtures) so it's testable
on its own — see ``tests/test_db_naming.py``. ``tests/conftest.py`` is the
only consumer and owns the actual create/drop lifecycle.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.engine.url import URL

# Every test database name (derived OR supplied via TEST_DATABASE_URL) must
# contain this marker. This is the fail-closed guard against drop_all()/
# create_all() ever landing on a real, non-test database — validation runs
# before any connection or DDL (see resolve_test_database_url).
REQUIRED_NAME_MARKER = "_test"

# Overrides the derived default entirely. Its database is caller-managed
# (e.g. CI's pre-provisioned service container): this suite creates/drops
# TABLES in it but never the database itself. Follows this repo's existing
# *_DATABASE_URL / *_URL env-var naming (see app/core/config.py).
ENV_OVERRIDE = "TEST_DATABASE_URL"

_DERIVED_PREFIX = "investing_companion_test_"
_HASH_LEN = 10  # 26-char prefix + 10 hex chars stays well under the 63-byte Postgres identifier limit


class UnsafeTestDatabaseName(RuntimeError):
    """Raised when a candidate test database name fails the fail-closed check."""


def validate_test_db_name(name: str) -> None:
    """Refuse any name that doesn't look unambiguously like a test database.

    Applies to BOTH derived names and TEST_DATABASE_URL overrides, and must
    run before any connection or DDL — this is the guard against
    drop_all()/create_all() (or our own CREATE DATABASE/DROP DATABASE)
    ever pointing at a real database.
    """
    if not name or REQUIRED_NAME_MARKER not in name:
        raise UnsafeTestDatabaseName(
            f"Refusing to use {name!r} as a test database: the name must "
            f"contain {REQUIRED_NAME_MARKER!r}. This guards drop_all()/"
            "create_all() against ever pointing at a real database. If you "
            f"set {ENV_OVERRIDE}, make sure its database name contains "
            f"{REQUIRED_NAME_MARKER!r}."
        )
    if len(name) > 63:
        raise UnsafeTestDatabaseName(
            f"Refusing to use {name!r} as a test database: Postgres "
            "identifiers are limited to 63 bytes."
        )
    if not all(ch.isascii() and (ch.isalnum() or ch == "_") for ch in name):
        raise UnsafeTestDatabaseName(
            f"Refusing to use {name!r} as a test database: only ASCII "
            "letters, digits, and underscores are allowed (it is used as an "
            "unquoted-safe identifier in CREATE/DROP DATABASE)."
        )


def checkout_root(conftest_file: str) -> Path:
    """The repo checkout root a given tests/conftest.py lives in.

    Deliberately derived from the file's OWN resolved path — never the
    process CWD. CI (and some local flows) ``cd backend`` before invoking
    pytest (see .github/workflows/ci.yml), so CWD is not a stable
    per-checkout identifier; every checkout would collapse to the same
    hash and defeat the point of this derivation.
    tests/conftest.py -> tests/ -> backend/ -> <checkout root>.
    """
    return Path(conftest_file).resolve().parents[2]


def derive_db_name(conftest_file: str) -> str:
    """A short, stable, per-checkout test database name.

    Stable: the same checkout hashes to the same name across runs, so a
    plain single dev checkout needs zero setup — the derived default just
    works, every time.
    Unique: two different checkouts (e.g. two git worktrees, or two
    clones) hash to different names, so concurrent suites never collide.

    xdist worker ids are deliberately NOT folded in here: this repo's DB
    fixture is session-scoped and pytest-xdist is not a dependency. If
    xdist is adopted later, fold ``os.environ.get("PYTEST_XDIST_WORKER")``
    into the hash input alongside the checkout root.
    """
    digest = hashlib.sha256(str(checkout_root(conftest_file)).encode("utf-8")).hexdigest()
    name = f"{_DERIVED_PREFIX}{digest[:_HASH_LEN]}"
    validate_test_db_name(name)
    return name


def resolve_test_database_url(conftest_file: str, base_database_url: str) -> tuple[URL, bool]:
    """Resolve the URL + database this suite's engine should use.

    Returns ``(url, is_override)``:
      - ``TEST_DATABASE_URL`` set: parsed with SQLAlchemy's ``make_url`` and
        used verbatim (name-validated). ``is_override=True`` — the database
        it names is caller-managed (e.g. CI's service container), so the
        caller must create/drop only TABLES in it, never the database.
      - unset: a per-checkout name is derived and spliced onto
        ``base_database_url`` via ``make_url(...).set(database=...)``, which
        preserves the base URL's scheme/user/password/host/port/query
        string untouched — only the database path segment changes.
        ``is_override=False`` — the caller owns the database's full
        lifecycle (create if missing, drop at session end).
    """
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        url = make_url(override)
        validate_test_db_name(url.database or "")
        return url, True

    name = derive_db_name(conftest_file)
    url = make_url(base_database_url).set(database=name)
    return url, False
