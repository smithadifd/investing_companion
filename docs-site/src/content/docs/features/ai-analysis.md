---
title: AI analysis
description: Ask questions about an equity using Claude, with live market data injected into the prompt automatically.
---

The AI analysis panel lets you have a back-and-forth conversation about an equity using Claude as the model. Before sending your question, the backend fetches live price, valuation, and risk data for the ticker and injects it into the prompt — so you're asking Claude about current numbers, not its training data.

Responses stream back token by token rather than arriving all at once. The panel keeps the conversation history for the session, so you can ask follow-up questions without repeating context.

For the rationale behind these design choices — user-provided keys, SSE transport, why there's no response caching — see the [AI integration design decisions](/design-decisions/ai-integration/) page. The SSE sequence is also mapped in [data flow, Flow 3](/architecture/data-flow/).

## Analysis types

The backend defines four `AnalysisType` values: `equity`, `ratio`, `watchlist`, and `general`. Only `equity` is wired to the UI panel today — the panel appears on the equity detail page under the AI tab. The `ratio`, `watchlist`, and `general` types exist in the API but are not currently surfaced in the frontend.

For `equity` analysis, the backend pulls current price, day change, 52-week range, market cap, P/E, forward P/E, EPS (TTM), beta, dividend yield, sector, and industry, then builds them into the prompt before calling Claude. If context fetch fails, Claude still receives your raw question.

## Setting up your API key

The feature is off by default. You need a Claude API key from [console.anthropic.com](https://console.anthropic.com/settings/keys).

There are two ways to configure it:

**Per-user via settings (recommended).** Open any equity detail page, navigate to the AI tab, and click the settings gear in the panel header. The `AISettingsModal` lets you paste an API key, pick a default model, and optionally write custom instructions. The key is stored encrypted in `user_settings` under the `claude_api_key` key and is never returned to the frontend — the settings response only includes a `has_api_key` boolean.

**Global environment variable.** Set `CLAUDE_API_KEY` in your environment. The service checks user settings first and falls back to the env var. This is convenient for single-user self-hosted installs where you don't want to re-enter the key after a data reset. See [configuration](/running/configuration/) for the full env var reference.

### Models

Two models are available:

- `claude-3-5-sonnet-20241022` — the default. Better reasoning, slower.
- `claude-3-5-haiku-20241022` — faster and cheaper, useful if you're running many queries.

You can change the default in the AI settings modal. The setting is stored as `ai_default_model` in `user_settings`.

### Custom instructions

The settings modal has an optional custom instructions field (stored as `ai_custom_instructions`). Whatever you write there gets appended to the system prompt on every request. Useful for things like "focus on dividend safety" or "I have a 10-year time horizon."

## Using the panel

Go to any equity detail page — for example `/equity/AAPL` — and select the AI tab. If no key is configured, the panel shows a "Configure API Key" button that opens the settings modal directly.

Once a key is set, the panel shows suggested prompts based on the analysis type: things like "What's the bull and bear case?" or "Analyze the valuation metrics." Click one to send it, or type your own question in the input field. Press Enter or click the send button.

The response streams in as Claude generates it. A blinking cursor shows while text is arriving. After the response completes, you can ask a follow-up — the conversation history stays in component state for the session.

The panel is implemented in `AIAnalysisPanel.tsx`, which uses the `useAIAnalysisStream` hook. The hook calls `POST /api/v1/ai/analyze/stream` and reads the SSE response chunk by chunk. A non-streaming endpoint (`POST /api/v1/ai/analyze`) also exists and is accessible via `useAIAnalysis`, but the panel always uses the streaming path.

## Cost

Requests go directly from the backend to Anthropic using your API key. Usage appears on your Anthropic billing dashboard — the app does not proxy or log token counts.
