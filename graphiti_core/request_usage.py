"""Request-scoped token accounting for OpenAI-compatible API calls."""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


@dataclass
class RequestUsage:
    """Aggregate token usage for one API request."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add_chat_completion(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens


CURRENT_REQUEST_USAGE: ContextVar[RequestUsage | None] = ContextVar(
    'CURRENT_REQUEST_USAGE',
    default=None,
)


def _usage_value(usage: Any, attribute: str) -> int:
    """Read a usage field from either an OpenAI object or mapping."""
    if usage is None:
        return 0
    if isinstance(usage, dict):
        return int(usage.get(attribute) or 0)
    return int(getattr(usage, attribute, 0) or 0)


def record_chat_completion_usage(usage: Any) -> None:
    """Record OpenAI chat-completion usage in the active request, if any."""
    request_usage = CURRENT_REQUEST_USAGE.get()
    if request_usage is None:
        return
    request_usage.add_chat_completion(
        _usage_value(usage, 'prompt_tokens'),
        _usage_value(usage, 'completion_tokens'),
    )
