"""The hard rules, written once (v0.1.64 HR-0): what Arslan never does, or never does without the user's own answer.

Four tables, each row naming the rule, the layer that holds it (`LAYERS`), the function that holds it there and the
test that proves it:

  DIRECT      what a command's text alone decides: the parser's forbid rules (layer ①) and this-time-only rules
              (layer ②), and what the gate refuses before any card;
  RUN_LATER   writes into files that make something run later (empty here; HR-1 fills it);
  NEVER_AUTO  what only the user answers, never a grant, a rule, a mode or a classifier (`never_auto`);
  ABSOLUTE    what holds under the least strict settings Arslan has, and the network cut after outside content, by path.

The rule keys and kinds come from the tables that decide them (terminal_policy, permissions), never copied: a row
names a key, and tests/server/test_hard_rules.py fails when a key or a kind has no row, or a row's test is not
collected. This module decides nothing yet but `never_auto`; the island reads its rule set (it doesn't call it).
"""
from __future__ import annotations

from dataclasses import dataclass

from server.services import permissions, terminal_policy

#: Where a rule is held: the command's text, the seatbelt profile, the tool loop's gate, the permission ladder.
LAYERS = ("parser", "kernel", "gate", "permissions")

#: Every key the parser's tables give a command: layer ①'s and layer ②'s (with `delete-outside` and `unreadable`).
FORBID_KEYS = frozenset(key for key, *_ in terminal_policy._FORBID)
ASK_KEYS = terminal_policy.ONCE_ONLY_RULES
#: A command whose rules overlap these is never answered by anything but the user's click (`never_auto`).
NEVER_AUTO_RULES = terminal_policy.ONCE_ONLY_RULES
#: Kinds only the user answers: the once-only kinds, the network after outside content, leaving the sandbox.
#: Full access still asks these (S5's table), so nothing automatic answers them either (CLS: never what full access
#: would still ask).
FULL_ACCESS_ASKS = frozenset({"send", "site", "shortcut"})
NEVER_AUTO_KINDS = permissions._ONCE_ONLY | permissions._ALWAYS_ASKS | {"network"} | FULL_ACCESS_ASKS
#: Kinds whose request decides (a command by its rules; HR-2 adds a write by its path). Written out, not derived: a
#: kind added to permissions.KINDS is never answered automatically until it is placed here or in NEVER_AUTO_KINDS
#: (the meta-test fails meanwhile).
MAY_AUTO_KINDS = frozenset({"command", "folder", "destructive", "screen", "app", "mcp_tool", "schedule",
                            "workspace_write"})


@dataclass(frozen=True)
class HardRule:
    id: str
    category: str
    layer: str                          # one of LAYERS
    holder: str                         # "module:function" that holds it
    test: str                           # the pytest node id that proves it (a function's id covers its cases)
    rules: frozenset[str] = frozenset()     # the parser keys this row stands for
    kinds: frozenset[str] = frozenset()     # the permission kinds this row stands for


_TP, _GATE = "server.services.terminal_policy", "server.orchestrator.command_gate"
_SANDBOX, _PERMS = "server.services.command_sandbox", "server.services.permissions"
_T = "tests/server/"
_FORBID_TEST = _T + "test_s2a2_three_layers.py::test_every_forbid_rule_refuses"
_ASK_TEST = _T + "test_s2a2_three_layers.py::test_layer_two_asks_this_time_only"
_GATE_TEST = _T + "test_command_gate_refusals.py::test_refused_before_any_card[{}]"
_LOOSEST = _T + "test_hard_rules_absolute.py::"
_S2A1 = _T + "test_s2a1_sandbox.py::"


def _forbid(key: str, test: str = _FORBID_TEST) -> HardRule:
    return HardRule(key, "forbid", "parser", f"{_TP}:_forbid", test, rules=frozenset({key}))


def _ask(key: str, test: str = _ASK_TEST, holder: str = f"{_TP}:_layer_two") -> HardRule:
    return HardRule(key, "this-time-only", "parser", holder, test, rules=frozenset({key}))


def _refused(key: str, layer: str, holder: str, test: str) -> HardRule:
    return HardRule(key, "refused-before-card", layer, holder, test)


DIRECT: tuple[HardRule, ...] = (
    *map(_forbid, ("keychain-secrets", "arslan-keys", "sudo", "wipe-root", "wipe-home", "macos-roots", "raw-disk",
                   "fork-bomb", "kill-all", "shutdown")),
    _forbid("trash", _T + "test_smart8_delete_to_trash.py::test_a_delete_from_the_trash_or_emptying_it_is_forbidden"),
    *map(_ask, ("apple-events", "shortcuts", "send-mail", "send-message", "upload", "remote-shell", "git-push",
                "publish", "force-kill", "login-items", "keychain-write", "system-settings", "open-app",
                "screen-clipboard", "delete-outside")),
    _ask(terminal_policy.OUTSIDE_REACH[0],                 # S2a-3 step 5: only when the command runs outside
         _T + "test_s2a3_outside_reach.py::test_a_gap_asks_once_outside_and_runs_inside"),
    _ask("protected-write",
         _T + "test_s2a2_three_layers.py::test_a_write_into_startup_ssh_credential_or_agent_files_asks_this_time_only"),
    _ask(terminal_policy.UNREADABLE, _T + "test_s2a2_three_layers.py::test_what_cannot_be_read_asks_this_time_only",
         f"{_TP}:assess"),
    _refused("empty", "parser", f"{_TP}:assess", _T + "test_hard_rules.py::test_an_empty_or_too_long_command_is_refused"),
    _refused("too-long", "parser", f"{_TP}:assess", _T + "test_hard_rules.py::test_an_empty_or_too_long_command_is_refused"),
    _refused("forbid-before-card", "gate", f"{_GATE}:check", _GATE_TEST.format("forbidden")),
    _refused("heredoc-in-substitution", "gate", f"{_GATE}:check", _GATE_TEST.format("here-document")),
    _refused("jxa", "gate", f"{_GATE}:check", _GATE_TEST.format("JXA")),
)

#: HR-1 fills this (run_later.py: the names, the kernel's deny in the commands and MCP profiles), HR-2 its file-tool
#: rows and HR-3 the direct forms outside the sandbox. Empty until then: nothing here is held yet.
RUN_LATER: tuple[HardRule, ...] = ()

NEVER_AUTO: tuple[HardRule, ...] = (
    HardRule("once-only-rules", "once-only", "permissions", f"{_PERMS}:_find_standing",
             _T + "test_s4a_outside_remote.py::test_a_layer_two_card_still_asks_under_the_grant_and_a_no_writes_no_grant_row",
             rules=NEVER_AUTO_RULES),
    HardRule("once-only-kinds", "once-only", "permissions", f"{_PERMS}:options_for",
             _T + "test_permissions.py::test_these_kinds_offer_only_this_once", kinds=permissions._ONCE_ONLY),
    HardRule("network-after-outside-content", "once-only", "gate", f"{_GATE}:_network_after_outside_content",
             _S2A1 + "test_outside_the_sandbox_the_network_card_is_this_time_only_and_ignores_a_grant",
             kinds=frozenset({"network"})),
    HardRule("outside", "always-asks", "permissions", f"{_PERMS}:decide",
             _T + "test_s4a_outside_remote.py::test_review_3_the_outside_card_is_shown_even_with_a_grant_and_writes_no_grant_row",
             kinds=permissions._ALWAYS_ASKS),
    HardRule("full-access-still-asks", "user-only", "permissions", "server.services.hard_rules:never_auto",
             _T + "test_hard_rules.py::test_what_full_access_still_asks_is_never_auto", kinds=FULL_ACCESS_ASKS),
    HardRule("unknown-kind", "fails-closed", "permissions", f"{_PERMS}:_check",
             _T + "test_permissions.py::test_an_unknown_kind_raises_before_anything_is_asked_stored_or_recorded"),
)


def _absolute(key: str, layer: str, holder: str, test: str) -> HardRule:
    return HardRule("absolute/" + key, "absolute", layer, holder, _LOOSEST + test)


def _cut(key: str, layer: str, holder: str, test: str) -> HardRule:
    return HardRule("network-cut/" + key, "network-cut", layer, holder, test)


ABSOLUTE: tuple[HardRule, ...] = (
    # Under the least strict settings (ask_risky, an outside grant, the sandbox off); S5a adds full access.
    _absolute("forbid-floor", "gate", f"{_GATE}:check", "test_the_floor_refuses_before_any_card"),
    _absolute("arslan-data", "kernel", f"{_SANDBOX}:minimal_profile", "test_arslans_own_data_stays_closed"),
    _absolute("skills-and-plugins", "kernel", f"{_SANDBOX}:minimal_profile", "test_the_skill_and_plugin_folders_stay_closed"),
    _absolute("apple-events", "kernel", f"{_SANDBOX}:minimal_profile", "test_apple_events_stay_refused"),
    _absolute("network-after-outside-content", "gate", f"{_GATE}:_network_after_outside_content",
              "test_after_outside_content_it_runs_offline_and_the_network_asks"),
    _absolute("money", "permissions", f"{_PERMS}:decide", "test_money_is_a_card_every_time"),
    _absolute("capability", "permissions", "server.services.approvals:window_only",
              "test_a_capability_is_answered_in_the_asking_window_only"),
    # S2a-1's network cut, one row per path it takes.
    _cut("mark", "gate", "server.orchestrator.untrusted:counts_as_external",
         _T + "test_core_memory.py::test_what_counts_as_reading_from_outside"),
    _cut("in-the-sandbox", "gate", f"{_GATE}:_network_after_outside_content",
         _S2A1 + "test_after_outside_content_a_command_in_the_sandbox_runs_offline"),
    _cut("outside-the-sandbox", "gate", f"{_GATE}:_network_after_outside_content",
         _S2A1 + "test_outside_the_sandbox_after_outside_content_a_command_runs_offline_too"),
    _cut("nobody-to-ask", "gate", f"{_GATE}:_network_after_outside_content",
         _S2A1 + "test_with_nobody_to_ask_a_network_command_in_the_sandbox_runs_offline"),
    _cut("bare-shortcut", "gate", f"{_GATE}:_network_after_outside_content",
         _S2A1 + "test_after_outside_content_a_bare_shortcut_asks_for_the_network_this_time_only"),
    _cut("no-isolation", "gate", "server.services.terminal_exec:_run",
         _T + "test_terminal_offline.py::test_offline_without_a_wrapper_refuses"),
    _cut("commands-profile", "kernel", f"{_SANDBOX}:commands_profile",
         _T + "test_command_sandbox.py::test_offline_inside_the_sandbox_blocks_network_and_still_writes"),
    _cut("outside-floor", "kernel", f"{_SANDBOX}:minimal_profile", _T + "sbx/test_sbx1_profile_texts.py::test_outside_floor"),
    _cut("island", "permissions", "server.services.approvals:island_may_answer",
         _T + "test_s2a2_three_layers.py::test_a_card_that_asks_for_the_network_too_says_so_and_the_island_leaves_it"),
)

ALL: tuple[HardRule, ...] = (*DIRECT, *RUN_LATER, *NEVER_AUTO, *ABSOLUTE)

# A row naming a key or a kind its table does not have would protect nothing (as permissions' scope sets).
_NAMED = {r.id for r in DIRECT if r.category in ("forbid", "this-time-only")}
if not _NAMED <= FORBID_KEYS | ASK_KEYS or not (NEVER_AUTO_KINDS | MAY_AUTO_KINDS) <= permissions.KINDS \
        or any(r.layer not in LAYERS for r in ALL):
    raise AssertionError("hard_rules names a key, kind or layer that does not exist")


def _writes_run_later(request) -> bool:
    """HR-1 and HR-2 fill this: a write, by a command or a file tool, into a file that makes something run later
    (RUN_LATER). Nothing is held here yet."""
    return False


def never_auto(request) -> bool:
    """Whether only the user's own answer may approve `request` (a permissions.Request): never a grant, a rule, a
    mode or a classifier (CLS and S5b call this). True for a command whose rules overlap the once-only rules or that
    is forbidden, a never-auto kind, a once-only request, a run-later write, and anything unknown or malformed."""
    kind = getattr(request, "kind", None)
    if not isinstance(kind, str) or kind not in MAY_AUTO_KINDS or getattr(request, "once_only", None) is not False:
        return True
    if kind == "command":
        detail, target = getattr(request, "detail", None), getattr(request, "target", None)
        if not isinstance(detail, str) or not isinstance(target, str):
            return True
        named = set(target.removeprefix("rules:").split("|")) if target.startswith("rules:") else set()
        # Fails closed: anything but a plain run, or any rule at all (a once-only one, or one added to the parser
        # later and not yet placed), is the user's to answer.
        # Read as if it ran outside the sandbox, the more cautious reading (S2a-3 step 5's outside-reach).
        if (terminal_policy.assess(detail, outside=True).level != "run" or named
                or terminal_policy.ask_rules(detail, outside=True)):
            return True
    return _writes_run_later(request)
