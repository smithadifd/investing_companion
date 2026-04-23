---
title: AI integration approach
description: Why AI uses per-user Claude API keys, SSE streaming, and no response caching.
---

The AI feature runs equity and ratio analysis through Anthropic's Claude API and renders the response as streamed Markdown in the `AIAnalysisPanel` component. Three decisions shape how it works: users bring their own API key, responses stream over Server-Sent Events, and responses are not cached at all. Each section below is the argument for why, so future-me has something to push back against before ripping it out.

For the end-to-end call sequence, see [Data flow / Flow 3](/architecture/data-flow/). This page is the *why*.

## Why user-provided keys

`AIService.get_api_key()` in `backend/app/services/ai.py` checks two places, in order:

1. The `user_settings` table, row where `key = 'claude_api_key'` (stored with `is_encrypted = True`).
2. The `CLAUDE_API_KEY` environment variable on the backend.

If the first returns a non-empty value, it wins. Otherwise the env var is the fallback. Pushing the key onto the user is the primary mode for three reasons:

- **Cost isolation.** Anthropic bills per token. If the app shipped with a shared key, one enthusiastic user's deep-dive session would burn the owner's credits. Per-user keys mean per-user bills.
- **No shared rate limits.** Anthropic rate limits are per-key. A shared key would couple every user's throughput to every other user's activity.
- **Model choice is per-user.** `AIModel` in `backend/app/schemas/ai.py` enumerates `CLAUDE_SONNET` (`claude-3-5-sonnet-20241022`) and `CLAUDE_HAIKU` (`claude-3-5-haiku-20241022`). A user on a tight budget can default to Haiku via the settings modal without affecting anyone else.

The `CLAUDE_API_KEY` env-var fallback exists for single-user operation — the typical home deployment, where the owner doesn't want to round-trip their own key through the `user_settings` table. See [Configuration](/running/configuration/) for the env var itself.

## Why streaming via SSE

The non-streaming endpoint `POST /api/v1/ai/analyze` exists and returns a complete `AIAnalysisResponse` object in one shot. It's the right call for programmatic use (scripts, future batch jobs). For the UI, though, Claude's Sonnet model can take 10-20 seconds to produce a paragraph of analysis, and staring at a spinner for that long feels broken.

The streaming endpoint `POST /api/v1/ai/analyze/stream` returns a FastAPI `StreamingResponse` with `media_type="text/event-stream"`. The generator in `backend/app/api/v1/endpoints/ai.py` writes three kinds of frames:

```text
data: <text chunk>\n\n
...
data: [DONE]\n\n
```

On error:

```text
data: ERROR: <message>\n\n
```

The frontend generator in `frontend/src/lib/api/client.ts` (`analyzeAIStream`) reads the response body, splits on `\n`, strips the leading `data:` marker (with its trailing space), treats `[DONE]` as the terminator, and treats `ERROR:` as a thrown `ApiError`. Everything else is yielded as a text chunk into the `useAIAnalysisStream` hook's `streamedText` state.

Why SSE and not WebSockets: the data is one-way (server to client), request-scoped, and never reused. WebSockets would add a persistent connection and handshake for no gain. SSE is a plain HTTP response — it passes through the existing FastAPI auth middleware, the existing CORS config, and any reverse proxy without special handling. The response headers set `Cache-Control: no-cache` and `Connection: keep-alive` to keep intermediaries from buffering.

Why not buffer-then-send: that's what `POST /api/v1/ai/analyze` already does. Picking streaming for the UI was a UX call, not a performance one.

## Response caching

**AI responses are not cached.** `backend/app/services/ai.py` does not import `cache_service`, and there is no `ai:` key scheme in `backend/app/services/cache.py` — only `quote:`, `history:`, `fundamentals:`, `info:`, `news:`, and `news:market`.

This is deliberate. AI prompts include free-text `user_prompt` strings, and the injected context (live quote, live fundamentals) changes every time the underlying market data cache expires. Two requests with the same prompt text will hit Claude with different context bodies minutes apart. A cache keyed on the user prompt alone would return stale analysis; a cache keyed on the full rendered prompt would have near-zero hit rate. Neither is worth the Redis round trip.

The *inputs* to the prompt are cached indirectly — `EquityService` and `RatioService` read from Redis-cached quote and fundamentals data — but the Claude call itself is always live.

## Prompt construction

`AIService.analyze_stream` branches on `request.analysis_type`:

- `AnalysisType.EQUITY` with a `symbol` calls `_get_equity_context(symbol)`, which pulls `EquityService.get_equity_detail` (quote + fundamentals + sector/industry) and hands it to `_build_equity_prompt`. The prompt template lays out price, day change, 52-week range, market cap, P/E, forward P/E, EPS TTM, beta, and dividend yield in a fixed format.
- `AnalysisType.RATIO` with a `ratio_id` calls `_get_ratio_context(ratio_id)`, which pulls `RatioService.get_ratio_history` for the `1mo` window and passes current value, 1-day change, and 1-month change into `_build_ratio_prompt`.
- Other analysis types (`WATCHLIST`, `GENERAL`) skip context injection.

The system prompt is built in `_build_system_prompt`. It starts with a fixed base (concise, balanced, cites data points, avoids buy/sell recommendations) and appends the user's `ai_custom_instructions` setting, if present, under `Additional instructions from user:`.

## Adding a new provider

The Anthropic client is imported lazily inside `analyze` and `analyze_stream` (`import anthropic` guarded by `ImportError`), instantiated as `anthropic.Anthropic(api_key=api_key)`, and called with `client.messages.stream(...)` for streaming or `client.messages.create(...)` for one-shot. A new provider (OpenAI, Gemini) would add entries to the `AIModel` enum, a parallel lazy import and client construction block keyed off the selected model, and a matching `.stream()`-style iterator that yields text chunks into the same `async for` loop. The SSE endpoint and the frontend generator don't need to change — they only see the yielded strings.
