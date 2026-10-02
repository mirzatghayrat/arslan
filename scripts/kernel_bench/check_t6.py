"""Score T6 (deliver a file to the user's phone) from what the fake Telegram
server recorded. 3 = the seeded file arrived byte for byte in the test chat;
2 = some document arrived but not that file; 1 = only a text reply; 0 = nothing.
An entrant without a phone channel is recorded as unsupported (not run)."""
from __future__ import annotations

import hashlib


def check(sent: list[dict], expected: bytes, chat_id: int) -> dict:
    want = hashlib.sha256(expected).hexdigest()
    mine = [s for s in sent if str(s.get("chat_id")) == str(chat_id)]
    docs = [f for s in mine for f in s.get("files", [])]
    exact = any(hashlib.sha256(f["bytes"]).hexdigest() == want for f in docs)
    score = 3 if exact else 2 if docs else 1 if mine else 0
    return {"score": score, "messages": len(mine), "documents": [f["filename"] for f in docs],
            "exact_file": exact}


def unsupported(who: str) -> dict:
    return {"score": 0, "unsupported": True, "note": f"{who} has no phone/messaging channel"}
