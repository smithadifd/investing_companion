# Issue 001: Claude Max OAuth Token Support

**Status:** Open
**Created:** 2026-02-01
**Priority:** Medium
**Affects:** AI Analysis feature (Phase 3)

## Summary

The AI Analysis feature currently requires a standard Anthropic API key (`sk-ant-api03-...`), but the project owner uses a Claude Max subscription with OAuth tokens (`sk-ant-oat01-...`). These OAuth tokens are not supported by Anthropic's public API.

## Current Behavior

- OAuth tokens return: `"OAuth authentication is currently not supported."`
- AI Analysis tab shows "Failed to perform analysis"
- All other Phase 3 features (Market Overview, Ratios) work correctly

## Root Cause

Anthropic's API does not accept OAuth access tokens directly. These tokens are designed for Claude Code CLI usage, not third-party API integrations.

## Workarounds

1. **Use a proxy service** (e.g., OpenClawd, CLIProxyAPI)
   - Runs locally, wraps Claude CLI, exposes OpenAI-compatible endpoint
   - Would require adding `CLAUDE_API_BASE_URL` config option

2. **Use standard API billing**
   - Get API key from console.anthropic.com
   - Pay per-token (separate from Max subscription)

3. **Wait for Anthropic**
   - Feature request: https://github.com/anthropics/claude-code/issues/18340
   - Requests Max subscription auth for third-party integrations

## Resolution Plan

When ready to address:

1. Add `CLAUDE_API_BASE_URL` to config (default: `https://api.anthropic.com`)
2. Modify `AIService` to use configurable base URL
3. Set up preferred proxy (OpenClawd or CLIProxyAPI)
4. Point app at proxy endpoint

## Impact on Other Phases

- **Phase 4 (Alerts):** No impact - doesn't require AI
- **Phase 5 (Auth/Settings):** No impact
- **Phase 6 (Trade Tracker):** Minor - AI trade analysis would be affected

## References

- [Claude Agent SDK OAuth Demo](https://github.com/weidwonder/claude_agent_sdk_oauth_demo)
- [CLIProxyAPI - Max to API](https://antran.app/2025/claude_code_max_api/)
- [OAuth Token Guide](https://www.alif.web.id/posts/claude-oauth-api-key)
