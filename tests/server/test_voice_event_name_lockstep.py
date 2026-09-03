"""The two voice event names must survive the language boundary.

`voice.rs` and `listen.rs` each declare the Tauri event their reader emits on;
`useConversationMode.ts` and `PushToTalk.tsx` each subscribe with a string
literal. Nothing in Rust or TypeScript connects those two halves — a rename on
one side compiles, passes every unit test, and ships a microphone that is armed
and silent, because the webview is listening to a channel nobody writes to.
This project has now been bitten four times by "an identifier here must match a
key there, with no guard"; the fix is always the same shape: derive one side
from the other in a test.

Rust is the source here (its `const` is what `emit` actually uses) and the TS
literals are asserted against it. The two names must also differ: one event for
both readers would deliver push-to-talk's finals into conversation mode.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TAURI_SRC = ROOT / "desktop" / "src-tauri" / "src"
WEB_SRC = ROOT / "web" / "src"

# `pub const EVENT: &str = "voice://conv";` / `const EVENT: &str = "voice://line";`
_EVENT = re.compile(r'const EVENT: &str = "(voice://[a-z]+)"')

# (rust module, the TS file that must listen on its event)
PAIRS = [
    ("voice.rs", "hooks/useConversationMode.ts"),
    ("listen.rs", "components/PushToTalk.tsx"),
]


def event_name(rust_file: str) -> str:
    src = (TAURI_SRC / rust_file).read_text()
    found = _EVENT.findall(src)
    assert len(found) == 1, f"expected exactly one EVENT const in {rust_file}, got {found}"
    return found[0]


def test_each_rust_event_is_the_one_its_webview_half_listens_on():
    for rust_file, ts_file in PAIRS:
        name = event_name(rust_file)
        ts = (WEB_SRC / ts_file).read_text()
        assert f"event.listen('{name}'" in ts, (
            f"{rust_file} emits on {name!r} but {ts_file} does not subscribe to it — "
            "the helper would run with nothing on the other end of the pipe")


def test_the_two_events_are_not_the_same_channel():
    names = [event_name(rust_file) for rust_file, _ in PAIRS]
    assert len(set(names)) == len(names), (
        f"both readers emit on {names} — push-to-talk's lines would arrive in "
        "conversation mode and vice versa")
