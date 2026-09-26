"""Host-owned effect classifications, never supplied by model arguments."""
from types import MappingProxyType

ACCOUNT_ACTION_EFFECTS = MappingProxyType({
    "asc.read": "read",
    "asc.draft.update": "external_write",
    "asc.screenshot.upload": "external_write",
})
