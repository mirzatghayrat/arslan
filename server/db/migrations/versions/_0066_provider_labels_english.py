"""0066: provider configs keep their preset's English name (0.1.59).

A config stores the provider's label when it is added, and the presets used to name some
providers in Chinese ("OpenRouter (聚合，含 Claude/Gemini)", "通义千问 Qwen (阿里云)"…), so the
English interface showed Chinese. The presets are English now; this renames saved configs
whose label is EXACTLY an old preset label. A label the user typed is never touched.
Idempotent.
"""
from __future__ import annotations

RENAMES = {
    "通义千问 Qwen (阿里云)": "Qwen (Alibaba Cloud)",
    "智谱 GLM": "Zhipu GLM",
    "OpenRouter (聚合，含 Claude/Gemini)": "OpenRouter (Claude, Gemini and more)",
    "Ollama (本地)": "Ollama (local)",
    "OpenAI-compatible(自定义)": "OpenAI-compatible (custom)",
}


def upgrade_sync(connection) -> None:
    for old, new in RENAMES.items():
        connection.exec_driver_sql("UPDATE provider_configs SET label = ? WHERE label = ?", (new, old))


def downgrade_sync(connection) -> None:
    for old, new in RENAMES.items():
        connection.exec_driver_sql("UPDATE provider_configs SET label = ? WHERE label = ?", (old, new))
