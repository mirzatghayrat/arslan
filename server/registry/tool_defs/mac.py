"""The user's Shortcuts and AppleScript, on a Mac."""
from server.registry.tool import Offer, Tool


def _on_a_mac(offer: Offer) -> bool:
    return offer.mac


def _acts(offer: Offer) -> bool:
    return offer.mac and offer.in_job


MAC = (
    Tool("mac_list_shortcuts", "List the user's macOS Shortcuts by name.",
         {"type": "object", "properties": {}, "additionalProperties": False},
         offered=_on_a_mac),
    Tool("mac_run_shortcut",
         "Run one of the user's Shortcuts by exact name "
         "(optional text input). Asks the user, for this task or this conversation.",
         {"type": "object", "properties": {"name": {"type": "string", "maxLength": 200},
          "input": {"type": "string", "maxLength": 20000}}, "required": ["name"],
          "additionalProperties": False},
         offered=_acts),
    Tool("mac_applescript",
         "Run an AppleScript to control a Mac app (Calendar, "
         "Reminders, Notes, Finder, Mail drafts…). The user sees the full script and must allow it each "
         "time; prefer a Shortcut when one exists. Never send, delete or pay without the user asking.",
         {"type": "object", "properties": {"script": {"type": "string", "maxLength": 4000}},
          "required": ["script"], "additionalProperties": False},
         offered=_acts),
)
