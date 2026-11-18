"""Contract check of the real anthropic SDK surface this app calls.

The AI tests patch ``anthropic.Anthropic`` with MagicMocks, which accept any
call shape, so they cannot notice an SDK major that renames or drops an
argument. This test inspects the installed SDK offline (no network, no key
use) for exactly what app/services/ai.py and app/services/agents/* rely on.
"""

import inspect

import anthropic
from anthropic.types import Message, Usage

# Keyword arguments passed to messages.create() / messages.stream() by every
# call site (ai.py analyze/analyze_stream and the agents).
CALL_KWARGS = {"model", "max_tokens", "system", "messages"}


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key="sk-test-placeholder")


def test_sync_client_exposes_create_and_stream():
    client = _client()
    assert hasattr(client.messages, "create")
    assert hasattr(client.messages, "stream")


def test_messages_create_accepts_the_call_site_kwargs():
    params = inspect.signature(_client().messages.create).parameters
    assert CALL_KWARGS <= set(params)


def test_messages_stream_accepts_the_call_site_kwargs():
    params = inspect.signature(_client().messages.stream).parameters
    assert CALL_KWARGS <= set(params)


def test_message_exposes_content_and_usage_tokens():
    assert {"content", "usage"} <= set(Message.model_fields)
    assert {"input_tokens", "output_tokens"} <= set(Usage.model_fields)
