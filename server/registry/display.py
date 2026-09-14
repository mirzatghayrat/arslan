"""UI-only translation hints; never replace stored or model-facing text."""
from server.registry.seed_catalog import TOOLSETS

_TOOLSETS = {row["key"]: row for row in TOOLSETS}


def toolset_display_keys(key: str, name: str, description: str) -> dict[str, str | None]:
    seed = _TOOLSETS.get(key)
    # A familiar key alone does not make edited text product-owned.
    return {
        "name_key": f"catalogUI.{key}.name" if seed and name == seed["name"] else None,
        "description_key": f"catalogUI.{key}.description"
        if seed and description == seed["description"] else None,
    }
