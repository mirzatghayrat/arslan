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

PRESETS: dict[str, dict[str, str]] = {
    "openai": {
        "label": "OpenAI",
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
    },
    "deepseek": {
        "label": "DeepSeek",
        "provider": "openai",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
    },
    "qwen": {
        "label": "通义千问 Qwen (阿里云)",
        "provider": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
    },
    "kimi": {
        "label": "Kimi (Moonshot)",
        "provider": "openai",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
    },
    "zhipu": {
        "label": "智谱 GLM",
        "provider": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4",
    },
    "minimax": {
        "label": "MiniMax",
        "provider": "openai",
        "base_url": "https://api.minimax.chat/v1",
        "default_model": "abab6.5s-chat",
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
        "default_model": "mistral-large-latest",
    },
    "openrouter": {
        "label": "OpenRouter (聚合，含 Claude/Gemini)",
        "provider": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "openai/gpt-4o",
    },
    "ollama": {
        "label": "Ollama (本地)",
        "provider": "openai",
        "base_url": "http://localhost:11434/v1",
        "default_model": "llama3",
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
