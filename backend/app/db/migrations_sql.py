"""Raw SQL shared between an Alembic data-migration and its tests.

Alembic version-file module names are date-prefixed (e.g.
``20260723_001_regrain_gdp_recurrence_keys``) and therefore not valid Python
identifiers, so they can't be imported with a normal ``from ... import ...``
statement. Rather than dynamically loading the migration module by file path
(fragile) or duplicating the SQL between the migration and its tests (drifts
silently), migration data-transformation SQL that a test needs to exercise
directly lives here instead, in an ordinarily-importable module — the
migration's ``upgrade()``/``downgrade()`` and the test both import the exact
same string.
"""

# GDP recurrence-key grain fix (see
# alembic/versions/20260723_001_regrain_gdp_recurrence_keys.py for the full
# migration and its ordering-hazard reasoning).
#
# Re-keys every GDP row still on the old ``gdp_<year>_<month>`` format to
# append an estimate-ordinal suffix, mirroring the two application-code
# paths that compute the same ordinal so a subsequent re-seed's key always
# matches what this SQL wrote:
#   * SEED-authored rows carry a human label in ``title`` (e.g.
#     "GDP Q3 2025 Initial Estimate") -- matched by substring, most-specific
#     tokens first, matching scripts/seed_macro_events._gdp_ordinal.
#   * Anything else (e.g. a FRED-sourced row, whose title is the generic
#     "GDP Release") falls back to the month-mod-3 heuristic, matching
#     app.services.data_providers.fred.gdp_estimate_ordinal.
#
# Only rows still on the exact old format (``gdp_YYYY_MM``, no existing
# suffix) are touched, so this is idempotent -- re-running finds nothing left
# to migrate.
GDP_REKEY_UPGRADE_SQL = """
    UPDATE economic_events
    SET recurrence_key = recurrence_key || '_' || (
        CASE
            WHEN title ILIKE '%Initial Estimate%' THEN 'initial_estimate'
            WHEN title ILIKE '%Updated Estimate%' THEN 'updated_estimate'
            WHEN title ILIKE '%Advance%' THEN 'advance'
            WHEN title ILIKE '%Second%' THEN 'second'
            WHEN title ILIKE '%Third%' THEN 'third'
            ELSE (
                CASE (EXTRACT(MONTH FROM event_date)::int % 3)
                    WHEN 1 THEN 'advance'
                    WHEN 2 THEN 'second'
                    ELSE 'third'
                END
            )
        END
    )
    WHERE event_type = 'gdp'
      AND recurrence_key ~ '^gdp_[0-9]{4}_[0-9]{2}$'
"""

# Downgrade strips the ordinal suffix back off. If two now-distinct GDP rows
# in the same month would collapse back onto the same old-format key, the
# partial unique index on recurrence_key (idx_economic_events_recurrence)
# rejects the second UPDATE and the downgrade fails loudly -- intentionally:
# silently merging two real releases back into one row on downgrade would be
# a worse outcome than a failed migration.
GDP_REKEY_DOWNGRADE_SQL = """
    UPDATE economic_events
    SET recurrence_key = substring(recurrence_key from '^gdp_[0-9]{4}_[0-9]{2}')
    WHERE event_type = 'gdp'
      AND recurrence_key ~ '^gdp_[0-9]{4}_[0-9]{2}_.+$'
"""
