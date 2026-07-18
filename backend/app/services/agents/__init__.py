"""Shared rails for the Tier-1 advisory agents (docs/issues/014).

This package is schema + rails only (sub-PR 1 of the wave) - it contains no
agent run logic and wires no Celery beat schedules. Each Tier-1 agent (News &
Catalyst, Trade Journal & Pattern Analysis, Daily Strategy) lands as its own
follow-up sub-PR and builds on the guard (:mod:`app.services.agents.guards`)
and base class (:mod:`app.services.agents.base`) defined here.
"""
