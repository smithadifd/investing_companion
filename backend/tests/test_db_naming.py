"""Unit tests for tests/db_naming.py — pure URL/name derivation.

No live database required (unlike most of this suite's `db`-fixture tests):
these exercise parsing/hashing logic only.
"""

import pytest
from sqlalchemy.engine import make_url

from tests.db_naming import (
    ALLOW_NAME_ENV,
    ENV_OVERRIDE,
    REQUIRED_NAME_MARKER,
    UnsafeTestDatabaseName,
    derive_db_name,
    resolve_test_database_url,
    validate_test_db_name,
)

_HERE = __file__  # a stand-in "conftest.py path" for derivation tests


class TestValidateTestDbName:
    def test_accepts_bare_ci_provisioned_name(self):
        # CI's pre-provisioned service-container database (no hash suffix).
        validate_test_db_name("investing_companion_test")

    def test_accepts_derived_shaped_name(self):
        validate_test_db_name("investing_companion_test_0123456789")

    def test_rejects_name_without_marker(self):
        with pytest.raises(UnsafeTestDatabaseName):
            validate_test_db_name("investing_companion")

    def test_rejects_empty_name(self):
        with pytest.raises(UnsafeTestDatabaseName):
            validate_test_db_name("")

    def test_rejects_name_over_63_bytes(self):
        long_name = "x_test_" + ("a" * 60)
        assert len(long_name) > 63
        with pytest.raises(UnsafeTestDatabaseName):
            validate_test_db_name(long_name)

    def test_rejects_unsafe_characters(self):
        # This is the guard against a malicious/mistaken TEST_DATABASE_URL
        # smuggling something other than a bare identifier into our
        # own CREATE DATABASE/DROP DATABASE DDL.
        with pytest.raises(UnsafeTestDatabaseName):
            validate_test_db_name('bobby_test"; DROP DATABASE prod; --')

    # -- finding 1 (codex second pass): the old check was `"_test" in name`,
    # a substring test that is NOT fail-closed — names like
    # "production_test_backup" or "customer_testimonials" contain "_test" as
    # a substring but are exactly the real-looking names the guard exists to
    # keep drop_all()/DROP DATABASE away from. The anchored pattern must
    # reject both.
    def test_rejects_substring_bypass_production_test_backup(self):
        with pytest.raises(UnsafeTestDatabaseName):
            validate_test_db_name("production_test_backup")

    def test_rejects_substring_bypass_customer_testimonials(self):
        with pytest.raises(UnsafeTestDatabaseName):
            validate_test_db_name("customer_testimonials")

    def test_rejects_63_byte_marker_containing_name_that_doesnt_match_pattern(self):
        # 63 bytes (at the Postgres identifier limit), contains "_test", but
        # doesn't match the anchored derived-name pattern — must still be
        # rejected by default (this is the exact shape of the old
        # substring-only check's bypass, just also boundary-length).
        name = "a_test_" + ("b" * 56)
        assert len(name) == 63
        assert REQUIRED_NAME_MARKER in name
        with pytest.raises(UnsafeTestDatabaseName):
            validate_test_db_name(name)

    # -- ALLOW_NAME_ENV escape hatch: opts a specific, differently-shaped
    # override name back in, without loosening the check for anyone else.
    def test_allow_name_escape_hatch_accepts_exact_match(self, monkeypatch):
        name = "a_custom_test_db"
        monkeypatch.setenv(ALLOW_NAME_ENV, name)
        validate_test_db_name(name)

    def test_allow_name_escape_hatch_ignores_mismatched_name(self, monkeypatch):
        monkeypatch.setenv(ALLOW_NAME_ENV, "some_other_test_db")
        with pytest.raises(UnsafeTestDatabaseName):
            validate_test_db_name("a_custom_test_db")

    def test_allow_name_escape_hatch_still_requires_marker(self, monkeypatch):
        # Even an exact env match can't smuggle in a name missing "_test"
        # entirely (unlike "customer_testimonials", which — precisely
        # because it contains "_test" as a substring — is covered by the
        # substring-bypass tests above instead).
        name = "production_backup"
        assert REQUIRED_NAME_MARKER not in name
        monkeypatch.setenv(ALLOW_NAME_ENV, name)
        with pytest.raises(UnsafeTestDatabaseName):
            validate_test_db_name(name)

    def test_allow_name_escape_hatch_still_enforces_length_limit(self, monkeypatch):
        name = "a_test_" + ("b" * 60)
        assert len(name) > 63
        monkeypatch.setenv(ALLOW_NAME_ENV, name)
        with pytest.raises(UnsafeTestDatabaseName):
            validate_test_db_name(name)

    def test_allow_name_escape_hatch_still_enforces_character_safety(self, monkeypatch):
        name = 'a_test"; DROP DATABASE prod; --'
        monkeypatch.setenv(ALLOW_NAME_ENV, name)
        with pytest.raises(UnsafeTestDatabaseName):
            validate_test_db_name(name)

    def test_accepts_at_63_bytes_exactly_via_allow_name(self, monkeypatch):
        name = "a_test_" + ("b" * 56)
        assert len(name) == 63
        monkeypatch.setenv(ALLOW_NAME_ENV, name)
        validate_test_db_name(name)


class TestDeriveDbName:
    def test_deterministic_for_same_path(self):
        assert derive_db_name(_HERE) == derive_db_name(_HERE)

    def test_differs_for_different_checkouts(self):
        # Simulates two git worktrees of the same repo: same relative
        # layout, different absolute root — the exact scenario this fix
        # exists for (concurrent-worktree suites colliding on one DB name).
        worktree_a = "/private/tmp/v-roll/ic-v8/backend/tests/conftest.py"
        worktree_b = "/private/tmp/v-roll/ic-v8-proofb/backend/tests/conftest.py"
        assert derive_db_name(worktree_a) != derive_db_name(worktree_b)

    def test_contains_required_marker_and_is_valid_identifier(self):
        name = derive_db_name(_HERE)
        validate_test_db_name(name)  # must not raise
        assert "_test" in name

    def test_stays_under_postgres_identifier_limit(self):
        assert len(derive_db_name(_HERE)) <= 63


class TestResolveTestDatabaseUrl:
    BASE_URL = "postgresql+asyncpg://investing:investing_dev@localhost:5432/investing_companion"

    def test_no_override_derives_from_base_url(self, monkeypatch):
        monkeypatch.delenv(ENV_OVERRIDE, raising=False)
        url, is_override = resolve_test_database_url(_HERE, self.BASE_URL)
        assert is_override is False
        assert "_test" in url.database
        # Everything except the database segment survives untouched.
        assert url.drivername == "postgresql+asyncpg"
        assert url.username == "investing"
        assert url.password == "investing_dev"
        assert url.host == "localhost"
        assert url.port == 5432

    def test_no_override_preserves_credentials_and_query_params(self, monkeypatch):
        monkeypatch.delenv(ENV_OVERRIDE, raising=False)
        base = (
            "postgresql+asyncpg://user%40name:p%40ss@db.example.com:5433/"
            "investing_companion?ssl=true&application_name=ic"
        )
        url, is_override = resolve_test_database_url(_HERE, base)
        assert is_override is False
        assert url.username == "user@name"
        assert url.password == "p@ss"
        assert url.host == "db.example.com"
        assert url.port == 5433
        assert url.query.get("ssl") == "true"
        assert url.query.get("application_name") == "ic"
        assert "_test" in url.database
        assert url.database != "investing_companion"

    def test_override_wins_and_is_flagged(self, monkeypatch):
        override = "postgresql+asyncpg://ci_user:ci_pass@localhost:5432/investing_companion_test"
        monkeypatch.setenv(ENV_OVERRIDE, override)
        url, is_override = resolve_test_database_url(_HERE, self.BASE_URL)
        assert is_override is True
        assert url == make_url(override)
        assert url.database == "investing_companion_test"

    def test_override_with_credentials_and_query_params_parses_cleanly(self, monkeypatch):
        override = (
            "postgresql+asyncpg://test_user:test_pass@localhost:5432/"
            "investing_companion_test?sslmode=disable"
        )
        monkeypatch.setenv(ENV_OVERRIDE, override)
        url, is_override = resolve_test_database_url(_HERE, self.BASE_URL)
        assert is_override is True
        assert url.username == "test_user"
        assert url.password == "test_pass"
        assert url.query.get("sslmode") == "disable"
        assert url.database == "investing_companion_test"

    def test_override_without_test_marker_is_rejected(self, monkeypatch):
        # Fail-closed: an override must still name a database containing
        # "_test", or we refuse before any connection/DDL is attempted.
        monkeypatch.setenv(ENV_OVERRIDE, "postgresql+asyncpg://u:p@localhost:5432/production")
        with pytest.raises(UnsafeTestDatabaseName):
            resolve_test_database_url(_HERE, self.BASE_URL)

    def test_two_checkouts_never_collide_when_unoverridden(self, monkeypatch):
        monkeypatch.delenv(ENV_OVERRIDE, raising=False)
        url_a, _ = resolve_test_database_url(
            "/private/tmp/v-roll/ic-v8/backend/tests/conftest.py", self.BASE_URL
        )
        url_b, _ = resolve_test_database_url(
            "/private/tmp/v-roll/ic-v8-proofb/backend/tests/conftest.py", self.BASE_URL
        )
        assert url_a.database != url_b.database
