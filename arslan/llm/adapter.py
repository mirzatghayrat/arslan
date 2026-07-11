"""Unified LLMAdapter — thin facade over any provider with profile loading."""
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import yaml

from arslan.llm import usage_sink
from arslan.llm.providers.anthropic_provider import AnthropicProvider
from arslan.llm.providers.base import BaseLLMProvider
from arslan.llm.providers.gemini_provider import GeminiProvider
from arslan.llm.providers.openai_provider import OpenAIProvider
from arslan.models import CapabilityProfile, LLMResponse

# Directory that holds the bundled YAML capability profiles
_PROFILES_DIR = Path(__file__).parent / "profiles"

# Default profile values used when no YAML is found for the requested model
_DEFAULT_PROFILE_VALUES: dict[str, Any] = {
    "reasoning": 3,
    "tool_use": 3,
    "chinese": 3,
    "creative": 3,
    "instruction": 3,
    "max_context": 8000,
    "cost_per_1k_tokens": 0.0,
}

# Registry mapping provider_name -> provider class
_PROVIDER_REGISTRY: dict[str, type[BaseLLMProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    # OpenAI-compatible endpoints (DeepSeek, Qwen, Ollama, …) use "openai" + base_url;
    # see arslan/llm/presets.py.
}


class LLMAdapter:
    """Single entry-point for all LLM interactions.

    Usage::

        adapter = LLMAdapter("openai", "gpt-4o", api_key="sk-...")
        response = await adapter.chat("You are helpful.", "Hello!")
        profile = adapter.load_profile("gpt-4o")
    """

    def __init__(
        self,
        provider_name: str,
        model: str,
        api_key: str = "",
        base_url: str = "",
    ) -> None:
        self.provider_name = provider_name
        self.model = model
        self.api_key = api_key
        self._provider = self._create_provider(provider_name, model, api_key, base_url)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_profile(self, model: str) -> CapabilityProfile:
        """Return the CapabilityProfile for *model*, falling back to defaults."""
        yaml_path = _PROFILES_DIR / f"{model}.yaml"
        if yaml_path.exists():
            with yaml_path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            return CapabilityProfile(**data)

        # Fallback: unknown model → conservative defaults
        return CapabilityProfile(
            name=model,
            provider=self.provider_name,
            **_DEFAULT_PROFILE_VALUES,
        )

    async def chat(
        self,
        system: str,
        user: str,
        history: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Build messages and delegate to the underlying provider."""
        messages = self._provider.build_messages(system, user, history)
        resp = await self._provider.chat(messages, tools=tools, temperature=temperature)
        total = (resp.usage or {}).get("total_tokens")
        if total is None:
            total = usage_sink.estimate_tokens(system, user, resp.content)
        usage_sink.report(total)
        u = resp.usage or {}
        tin = u.get("prompt_tokens") or u.get("input_tokens") or u.get("promptTokenCount")
        tout = u.get("completion_tokens") or u.get("output_tokens") or u.get("candidatesTokenCount")
        usage_sink.report_detail(
            tokens_in=tin,
            tokens_out=tout,
            model=self.model,
            provider=self.provider_name,
        )
        return resp

    async def chat_stream(
        self,
        system: str,
        user: str,
        history: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Build messages and stream content deltas from the provider."""
        messages = self._provider.build_messages(system, user, history)
        chunks: list[str] = []
        try:
            async for piece in self._provider.chat_stream(
                messages, tools=tools, temperature=temperature
            ):
                chunks.append(piece)
                yield piece
        finally:
            # S3-M3: providers stash the stream's real usage frame on themselves
            # (see BaseLLMProvider._last_stream_usage); the adapter stays the ONE
            # reporting point — real when captured, estimate only as fallback, so
            # real + estimate can never double-report. Providers publish the stash
            # only once the backend confirmed the message completed (anthropic:
            # at message_delta, never from message_start alone — review I2), so an
            # aborted stream leaves it None/partial and lands here on the estimate
            # branch: real and guessed fields must never mix.
            real = getattr(self._provider, "_last_stream_usage", None) or {}
            tokens_in = real.get("tokens_in")
            tokens_out = real.get("tokens_out")
            if tokens_in is not None and tokens_out is not None:
                usage_sink.report(int(tokens_in) + int(tokens_out))
                usage_sink.report_detail(
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    model=self.model,
                    provider=self.provider_name,
                )
            else:
                usage_sink.report(usage_sink.estimate_tokens(system, user, "".join(chunks)))
                usage_sink.report_detail(
                    tokens_in=None,
                    tokens_out=None,
                    model=self.model,
                    provider=self.provider_name,
                )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _create_provider(
        provider_name: str,
        model: str,
        api_key: str,
        base_url: str,
    ) -> BaseLLMProvider:
        provider_cls = _PROVIDER_REGISTRY.get(provider_name)
        if provider_cls is None:
            # Graceful fallback: use OpenAI-compatible interface with supplied base_url
            return OpenAIProvider(model=model, api_key=api_key, base_url=base_url)
        return provider_cls(model=model, api_key=api_key, base_url=base_url)
