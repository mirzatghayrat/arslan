"""Portable contract for measured SBX-5 features on already-built adapters."""
from itertools import product

from tests.server.sbx import harness
from tests.server.sbx import test_sbx5_paths as gates


def test_features_use_only_their_own_key(monkeypatch):
    assert isinstance(getattr(harness, "BUILT_FEATURES", None), frozenset)
    queried = []

    class Features(frozenset):
        def __contains__(self, key):
            queried.append(key)
            return super().__contains__(key)

    for base, options, key in (
        ("outside-floor", {"cap6b": True}, "cap6b"),
        ("commands", {"feature": "cap6b"}, "cap6b"),
        ("commands", {"feature": "shared-cache-exclusions"}, "shared-cache-exclusions"),
    ):
        for features in ((), ("unrelated",), ("cap6b",), ("shared-cache-exclusions",),
                         ("cap6b", "shared-cache-exclusions")):
            queried.clear()
            monkeypatch.setattr(harness, "BUILT_FEATURES", Features(features))
            mark, = gates.pending(base, **options).marks
            assert mark.args == (key not in features,)
            assert queried == [key]
            assert mark.kwargs["strict"] is True
            matcher = mark.kwargs["raises"]
            assert matcher.matches(AssertionError(f"SBX-5a {key} protection is not built"))
            assert not matcher.matches(AssertionError("real gate failure"))
            other = "shared-cache-exclusions" if key == "cap6b" else "cap6b"
            assert not matcher.matches(AssertionError(f"SBX-5a {other} protection is not built"))
        queried.clear()
        for base in gates.BASES:
            # Passing cases stay real; other unbuilt surfaces still key on bases.
            mark, = gates.pending(base).marks
            assert mark.args == (base not in harness.BUILT_BASES,)
        assert queried == []


def test_only_measured_future_cases_use_feature_gates():
    selected, real_commands = set(), set()
    total = 0
    for name, test in vars(gates).items():
        if not name.startswith("test_"):
            continue
        parameters = [m for m in test.pytestmark if m.name == "parametrize"]
        for rows in product(*(m.args[1] for m in parameters)):
            total += 1
            arguments, marks = {}, []
            for parameter, row in zip(parameters, rows):
                values = row.values if hasattr(row, "values") else (row,)
                arguments.update(zip(parameter.args[0].split(","), values))
                row_marks = getattr(row, "marks", ())
                marks.extend(row_marks if isinstance(row_marks, (tuple, list)) else (row_marks,))
            row = (name, arguments.get("name"), arguments.get("kind"), arguments.get("through_alias"))
            features = [key for key, message in gates.FEATURE_MESSAGES.items()
                        if any(m.name == "xfail" and m.kwargs.get("reason") == message for m in marks)]
            if features:
                assert len(features) == 1
                selected.add((features[0], arguments["cap_sbx"], *row))
            elif arguments["cap_sbx"] == "commands":
                real_commands.add(row)
    assert total == 78
    outside = {
        (name, target, None, None)
        for name in ("test_cap6b_write_denied", "test_cap6b_read_denied")
        for target in ("skills", "plugin")
    } | {
        ("test_cap6b_symlink_root", None, None, alias) for alias in (False, True)
    } | {
        ("test_links_do_not_open_write_paths", target, kind, None)
        for target in ("skills", "plugin") for kind in ("symlink", "hardlink")
    }
    cap6b_commands = {
        ("test_cap6b_read_denied", target, None, None) for target in ("skills", "plugin")
    } | {
        ("test_cap6b_symlink_root", None, None, alias) for alias in (False, True)
    } | {("test_commands_exclusions_override_a_writable_ancestor", "plugin", None, None)} | {
        ("test_commands_workspace_inside_cap6b_stays_read_only", target, None, None)
        for target in ("skills", "plugin")
    }
    cache_commands = {
        (name, target, None, None)
        for name in ("test_shared_cache_is_not_writable", "test_commands_exclusions_override_a_writable_ancestor")
        for target in ("npm", "cache", "Library-Caches")
    } | {("test_links_do_not_open_write_paths", "npm", kind, None) for kind in ("symlink", "hardlink")} | {
        ("test_peer_cache_inside_a_grant_stays_closed", None, None, None)
    }
    # SBX-4a builds mcp and run-python, so what they wait for from 5a moved from base gates to feature gates.
    cap6b_built_bases = {
        ("cap6b", base, "test_cap6b_symlink_root", None, None, alias)
        for base in ("mcp", "run-python") for alias in (False, True)
    }
    cap6b_built_bases |= {
        ("cap6b", "mcp", "test_cap6b_write_denied", target, None, None)
        for target in ("skills", "plugin")
    } | {
        ("cap6b", "mcp", "test_links_do_not_open_write_paths", target, kind, None)
        for target in ("skills", "plugin") for kind in ("symlink", "hardlink")
    }
    cache_mcp = {
        ("test_shared_cache_is_not_writable", target, None, None) for target in ("npm", "cache", "Library-Caches")
    } | {
        (name, None, None, None)
        for name in ("test_commands_cache_is_not_visible_to_mcp", "test_peer_cache_inside_a_grant_stays_closed")
    }
    cache_mcp |= {
        ("test_links_do_not_open_write_paths", "npm", kind, None) for kind in ("symlink", "hardlink")
    }
    assert selected == ({("cap6b", "outside-floor", *row) for row in outside}
                        | {("cap6b", "commands", *row) for row in cap6b_commands}
                        | cap6b_built_bases
                        | {("shared-cache-exclusions", "mcp", *row) for row in cache_mcp}
                        | {("shared-cache-exclusions", "commands", *row) for row in cache_commands})
    assert real_commands == {
        ("test_cap6b_write_denied", target, None, None) for target in ("skills", "plugin", "data")
    } | {("test_cap6b_read_denied", "data", None, None)} | {
        ("test_links_do_not_open_write_paths", target, kind, None)
        for target in ("skills", "plugin", "data") for kind in ("symlink", "hardlink")
    }
