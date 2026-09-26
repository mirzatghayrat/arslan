"""UI-only translation hints; never replace stored or model-facing text."""
from server.registry.seed_catalog import SKILLS, TOOLSETS

_TOOLSETS = {row["key"]: row for row in TOOLSETS}
_SKILLS = {row[0]: row for row in SKILLS}


def toolset_display_keys(key: str, name: str, description: str) -> dict[str, str | None]:
    seed = _TOOLSETS.get(key)
    # A familiar key alone does not make edited text product-owned.
    return {
        "name_key": f"catalogUI.{key}.name" if seed and name == seed["name"] else None,
        "description_key": f"catalogUI.{key}.description"
        if seed and description == seed["description"] else None,
    }


def skill_display_keys(key: str, name: str, description: str) -> dict[str, str | None]:
    seed = _SKILLS.get(key)
    return {
        "name_key": f"catalogUI.skills.{key}.name" if seed and name == seed[1] else None,
        "description_key": f"catalogUI.skills.{key}.description"
        if seed and description == seed[3] else None,
    }
