"""OpenAI-compatible provider presets (Tier 0).

Every model here speaks the OpenAI ``/chat/completions`` format, so Arslan's
existing ``OpenAIProvider`` reaches them by swapping ``base_url`` + key — no new
provider code. These presets save the (non-technical) user from hunting base
URLs: pick a name, fill the key. Model names are sensible defaults and can be
overridden. Anthropic (Claude) and Google (Gemini) are NOT here — they are not
OpenAI-compatible and get native providers (Tier 1/2); they can also be reached
via the ``openrouter`` preset.
"""
from __future__ import annotations

from arslan.llm.catalog import models_for

PRESETS: dict[str, dict[str, str]] = {
    "openai": {
        "label": "OpenAI",
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-5.6-terra",
    },
    "deepseek": {
        "label": "DeepSeek",
        "provider": "openai",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-v4-flash",
    },
    "qwen": {
        "label": "通义千问 Qwen (阿里云)",
        "provider": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen3.7-plus",
    },
    "kimi": {
        "label": "Kimi (Moonshot)",
        "provider": "openai",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "kimi-k2.5",
    },
    "zhipu": {
        "label": "智谱 GLM",
        "provider": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-5-turbo",
    },
    "minimax": {
        "label": "MiniMax",
        "provider": "openai",
        "base_url": "https://api.minimax.chat/v1",
        "default_model": "MiniMax-M2.7",
    },
    "groq": {
        "label": "Groq",
        "provider": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
    },
    "together": {
        "label": "Together AI",
        "provider": "openai",
        "base_url": "https://api.together.xyz/v1",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    },
    "mistral": {
        "label": "Mistral",
        "provider": "openai",
        "base_url": "https://api.mistral.ai/v1",
        "default_model": "mistral-medium-2604",
    },
    "openrouter": {
        "label": "OpenRouter (聚合，含 Claude/Gemini)",
        "provider": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "anthropic/claude-sonnet-5",
    },
    "ollama": {
        "label": "Ollama (本地)",
        "provider": "openai",
        "base_url": "http://localhost:11434/v1",
        # B5: no static default — the dynamic list (/api/tags) is king; the UI
        # shows "not detected" when no local daemon answers. A blank model on a
        # saved ollama config intentionally raises at build_adapter (user must
        # pick a model that is actually pulled).
        "default_model": "",
    },
}


# Native providers (NOT OpenAI-compatible) — reached by dedicated provider
# classes in arslan/llm/adapter.py, so they carry no base_url (the SDK knows it).
# ``openai`` is intentionally NOT here: it already lives in PRESETS as the
# canonical OpenAI-compatible entry.
NATIVE: dict[str, dict[str, str]] = {
    "anthropic": {
        "label": "Anthropic Claude",
        "provider": "anthropic",
        "base_url": "",
        "default_model": "claude-sonnet-5",
    },
    "gemini": {
        "label": "Google Gemini",
        "provider": "gemini",
        "base_url": "",
        "default_model": "gemini-3.5-flash",
    },
}


def resolve_preset(name: str) -> dict[str, str] | None:
    """Return the preset config for ``name`` (case-insensitive), or None."""
    if not name:
        return None
    return PRESETS.get(name.strip().lower())


def list_presets() -> list[str]:
    """Return preset keys, sorted."""
    return sorted(PRESETS)


def provider_options() -> list[dict[str, object]]:
    """Unified list for the Settings provider dropdown: presets + native.

    Each option is ``{key, label, base_url, default_model, native}``. The
    frontend renders ``label``, stores ``key`` as ``llm_provider``, and can
    prefill ``llm_model``/``llm_base_url`` from the defaults. ``native`` marks
    entries handled by a dedicated provider class (no user base_url needed).
    """
    options: list[dict[str, object]] = []
    for key in list_presets():
        p = PRESETS[key]
        options.append(
            {
                "key": key,
                "label": p["label"],
                "base_url": p["base_url"],
                "default_model": p["default_model"],
                "native": False,
                "models": models_for(key),
            }
        )
    for key, p in NATIVE.items():
        options.append(
            {
                "key": key,
                "label": p["label"],
                "base_url": p["base_url"],
                "default_model": p["default_model"],
                "native": True,
                "models": models_for(key),
            }
        )
    # P3: custom OpenAI-compatible endpoint (LM Studio, vLLM, llama.cpp, …).
    # Deliberately NOT a PRESETS row: expand_preset's unknown-provider
    # passthrough + LLMAdapter's registry-miss fallback to OpenAIProvider ARE
    # the runtime chain, and a preset row would start filling defaults the
    # user must own (base_url is required, enforced server-side).
    options.append(
        {
            "key": "custom",
            "label": "OpenAI-compatible(自定义)",
            "base_url": "",  # user must fill
            "default_model": "",
            "native": False,
            "models": [],
        }
    )
    return options


def expand_preset(provider: str, model: str, base_url: str) -> tuple[str, str, str]:
    """Resolve a stored ``llm_provider`` into a concrete adapter config.

    If ``provider`` names a Tier-0 preset (e.g. ``"deepseek"``), expand it to the
    OpenAI-compatible client config, filling ``base_url`` and ``model`` from the
    preset *only* where the user left them blank (user values always win). Native
    or unknown providers pass through unchanged so the adapter registry handles
    them.
    """
    preset = resolve_preset(provider)
    if preset is None:
        return provider, model, base_url
    return (
        preset["provider"],
        model or preset["default_model"],
        base_url or preset["base_url"],
    )
