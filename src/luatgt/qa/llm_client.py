"""Giao diện LLM đổi được provider (spec 3.1). Không có khoá thì `make_llm_client` trả None: dùng template."""

from __future__ import annotations

from typing import Protocol

from luatgt.common.config import Settings
from luatgt.common.logging import get_logger

log = get_logger(__name__)

DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"


class LLMError(RuntimeError):
    """LLM không trả được nội dung dùng được; bên gọi chuyển sang template."""


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class AnthropicClient:
    def __init__(self, api_key: str, model: str | None) -> None:
        import anthropic

        self._errors = (anthropic.APIConnectionError, anthropic.APIStatusError)
        self.client = anthropic.Anthropic(api_key=api_key, timeout=60.0)
        self.model = model or DEFAULT_ANTHROPIC_MODEL

    def complete(self, system: str, user: str) -> str:
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": "low"},  # chỉ viết lại các số đã có
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except self._errors as e:
            raise LLMError(str(e)) from e
        if response.stop_reason in ("refusal", "max_tokens"):
            raise LLMError(f"stop_reason={response.stop_reason}")
        return "".join(b.text for b in response.content if b.type == "text")


def make_llm_client(settings: Settings) -> LLMClient | None:
    key = settings.llm.api_key.get_secret_value() if settings.llm.api_key else ""
    if not key:
        return None
    if settings.llm.provider != "anthropic":
        log.warning("llm_provider_not_implemented provider=%s, dùng template", settings.llm.provider)
        return None
    return AnthropicClient(key, settings.llm.model)
