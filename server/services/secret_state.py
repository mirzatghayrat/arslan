"""One vocabulary for "what is the state of this stored secret?".

Three states, and the third is the whole point:

    unset          nobody ever entered one
    set            stored, and this process can read it
    undecryptable  STORED, but this process cannot open it

Collapsing `undecryptable` into `unset` is the defect this module exists to end.
``settings_service._safe_decrypt`` returns ``""`` when Fernet raises, so a secret
encrypted under a key this process no longer derives reads as absent — and the search
executor's ``if not key`` then reports "web search is not configured (no API key set)".
The project's own author lost a month to that sentence: the key was in the database
the whole time, and the salt was what had moved. Naming the wrong cause is worse than
naming none, because it sends someone to solve a different problem.

WHY HOISTED HERE. ``provider_config_service`` implemented exactly this first, for the
BYOK provider rows, and the frontend already renders it
(``ProviderDetailPane.tsx``, ``settings.keyUndecryptableReason``). The settings-level
secrets were simply left behind. So this is that function moved out to be shared, not
a second implementation of it — two copies of a three-way classification would drift,
and the drift would be invisible because both halves would still look reasonable.
"""
from __future__ import annotations

from typing import Literal

from server import crypto

SecretState = Literal["unset", "set", "undecryptable"]


def secret_state(stored: str | None) -> SecretState:
    """Classify a stored ciphertext without revealing anything about its contents.

    ``stored`` is the raw column value: ``None``/``""`` for absent, otherwise a Fernet
    token. Ciphertext that decrypts to an empty string counts as ``unset``, because
    that is how a CLEARED key is stored and a mask over an empty value would be a
    small lie of its own.
    """
    if not stored:
        return "unset"
    try:
        plaintext = crypto.decrypt(stored)
    except Exception:  # noqa: BLE001 — any failure to open means the same thing
        # Deliberately broad. InvalidToken is the expected case, but a corrupt row or
        # a CryptoNotInitializedError must not be re-reported as "unset" either: both
        # mean "something IS stored and we cannot read it", which is what the caller
        # has to tell the user.
        return "undecryptable"
    return "set" if plaintext else "unset"
