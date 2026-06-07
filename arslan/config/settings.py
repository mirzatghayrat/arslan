"""Global settings and path configuration for Arslan."""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application-wide settings with sensible defaults."""

    # --- Paths ---
    arslan_home: Path = Field(default_factory=lambda: Path.home() / ".arslan")
    spawns_dir: Path = Field(default_factory=lambda: Path.cwd() / "spawns")
    templates_dir: Path = Field(
        default_factory=lambda: Path(__file__).parent.parent / "templates"
    )
    profiles_dir: Path = Field(
        default_factory=lambda: Path(__file__).parent.parent / "profiles"
    )

    # --- LLM defaults ---
    default_provider: str = "anthropic"
    default_model: str = "claude-3-5-haiku-20241022"
    max_dialogue_turns: int = 20

    # --- Evolution engine ---
    evolution_min_samples: int = 20
    evolution_confidence_threshold: float = 0.5

    # --- Logging ---
    log_level: str = "INFO"

    model_config = {"env_prefix": "ARSLAN_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
