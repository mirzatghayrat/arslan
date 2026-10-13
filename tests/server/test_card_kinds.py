"""0.1.61 PR 2b (R14): every permission kind the web or the Bridge names is a kind the server sends.

`permissions.decide` raises for a kind outside `permissions.KINDS`, so a word mapped for one that is
not there ("payment" for "money") would be dead code that nothing notices. The web and Swift cannot
import `KINDS`, so this reads their sources (plain regexes, nothing is executed). It proves the words
match the server's; the vitest and Swift tests prove that the mapping runs. Hands' action kinds
(`desktop_app`…) are another namespace and are not read here.

The same reading keeps three copies of one number in step: how long the Mac waits on a card.
"""
import re
from pathlib import Path

from server.services import approvals, permissions

ROOT = Path(__file__).resolve().parents[2]
FRAME_MAPPER = ROOT / "desktop/bridge/Sources/BridgeCore/FrameMapper.swift"
ASK_PARTS = ROOT / "web/src/components/kit/askParts.tsx"
COUNTDOWN = ROOT / "web/src/components/kit/Countdown.tsx"
#: A `perm_kind` written in the web (source and tests) or the Bridge: `perm_kind: "x"` (TS),
#: `"perm_kind": "x"` (Swift), `permKind="x"` (a JSX prop).
PERM_KIND = re.compile(r'(?:perm_kind"?\s*:\s*|permKind=\{?)"([a-z_]+)"')


def _read(path: Path) -> str:
    assert path.is_file(), f"{path} is missing: this guard reads the front ends' sources"
    return path.read_text(encoding="utf-8")


def _kinds(text: str, name: str) -> set[str]:
    """The strings of `export const NAME = new Set([...])` in a TS source."""
    found = re.search(rf"export const {name} = new Set\(\[([^\]]*)\]\)", text)
    assert found, f"{name} is missing from askParts.tsx"
    return set(re.findall(r'"([a-z_]+)"', found.group(1)))


def _number(expression: str) -> int:
    """`1_800_000` or `30 * 60 * 1000` (digits, `_` and `*` only): a product, never evaluated."""
    product = 1
    for factor in expression.split("*"):
        product *= int(factor.strip().replace("_", ""))
    return product


def test_the_bridge_names_only_kinds_the_server_has():
    text = _read(FRAME_MAPPER)
    risk = re.search(r"static func permRisk\(.*?\n    \}\n", text, re.S)
    assert risk, "FrameMapper.permRisk is missing"
    # Every label of every `case "a", "b":` line (a case may name several kinds).
    words = {word for labels in re.findall(r"case ((?:\"[a-z_]+\",?\s*)+):", risk.group(0))
             for word in re.findall(r'"([a-z_]+)"', labels)}
    assert words == {"money", "send", "destructive", "outside"}, words      # §A4's four, and only those
    assert words <= permissions.KINDS
    guards = set(re.findall(r'perm_kind"\] as\? String == "([a-z_]+)"', text))
    assert guards == {"capability"}, guards                                  # what keeps it off the phone
    assert guards <= permissions.KINDS


def test_the_web_names_only_kinds_the_server_has():
    text = _read(ASK_PARTS)
    red = _kinds(text, "RED_KINDS")
    assert red == {"money", "app_risky", "destructive"}, red                 # the kinds whose Allow is red
    assert red <= permissions.KINDS


def test_the_webs_once_only_kinds_are_the_servers():
    # A card of one of these offers one choice (spec §A4): the web trims its options to match what
    # `permissions.decide` would grant, so a kind in one list and not the other is a button that
    # lies (or a grant the server refuses).
    once = _kinds(_read(ASK_PARTS), "ONCE_ONLY_KINDS")
    assert once == set(permissions._ONCE_ONLY), (sorted(once ^ permissions._ONCE_ONLY), "web ^ server")


def test_no_front_end_file_or_test_writes_a_perm_kind_the_server_never_sends():
    seen: dict[str, set[str]] = {}
    files = [*(ROOT / "web/src").rglob("*.ts"), *(ROOT / "web/src").rglob("*.tsx"),
             *(ROOT / "desktop/bridge").rglob("*.swift")]
    for path in files:
        if ".build" in path.parts:
            continue
        for kind in PERM_KIND.findall(path.read_text(encoding="utf-8")):
            seen.setdefault(kind, set()).add(str(path.relative_to(ROOT)))
    # Not vacuous: the kinds this PR's own tests use are found.
    assert {"money", "send", "destructive", "outside", "capability", "app", "command"} <= set(seen), sorted(seen)
    unknown = {kind: sorted(paths) for kind, paths in seen.items() if kind not in permissions.KINDS}
    assert not unknown, f"not in permissions.KINDS: {unknown}"


def test_the_web_the_server_and_the_bridge_wait_the_same_time_on_a_card():
    # In seconds: the web counts milliseconds (CARD_MS), the server and the Bridge seconds.
    web = re.search(r"export const CARD_MS = ([0-9_]+(?:\s*\*\s*[0-9_]+)*)\s*;", _read(COUNTDOWN))
    bridge = re.search(r"static let cardWait: TimeInterval = ([0-9_]+(?:\s*\*\s*[0-9_]+)*)\b", _read(FRAME_MAPPER))
    assert web, "Countdown.CARD_MS is missing (or is no longer a plain number)"
    assert bridge, "FrameMapper.cardWait is missing (or is no longer a plain number)"
    waits = {"web CARD_MS": _number(web.group(1)) / 1000, "server approvals.TIMEOUT_S": approvals.TIMEOUT_S,
             "bridge FrameMapper.cardWait": _number(bridge.group(1))}
    assert len(set(waits.values())) == 1, waits
