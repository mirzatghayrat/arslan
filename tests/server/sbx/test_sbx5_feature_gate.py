"""Portable contract for the ten deferred outside-floor CAP6b protections."""
from itertools import product

from tests.server.sbx import harness
from tests.server.sbx import test_sbx5_paths as gates


def test_cap6b_uses_only_its_feature_key(monkeypatch):
    assert isinstance(getattr(harness, "BUILT_FEATURES", None), frozenset)
    queried = []

    class Features(frozenset):
        def __contains__(self, key):
            queried.append(key)
            return super().__contains__(key)

    for features, missing in (((), True), (("unrelated",), True), (("cap6b",), False)):
        queried.clear()
        monkeypatch.setattr(harness, "BUILT_FEATURES", Features(features))
        mark, = gates.pending("outside-floor", cap6b=True).marks
        assert mark.args == (missing,)
        assert queried == ["cap6b"]
        assert mark.kwargs["strict"] is True
        matcher = mark.kwargs["raises"]
        assert matcher.matches(AssertionError("SBX-5a cap6b protection is not built"))
        assert not matcher.matches(AssertionError("real gate failure"))
        queried.clear()
        for base in gates.BASES:
            # Other cases still depend only on their product adapter.
            mark, = gates.pending(base).marks
            assert mark.args == (base not in harness.BUILT_BASES,)
        assert queried == []


def test_exactly_ten_outside_floor_cases_use_the_cap6b_gate():
    selected = set()
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
            if any(m.name == "xfail" and m.kwargs.get("reason") ==
                   "SBX-5a cap6b protection is not built" for m in marks):
                assert arguments["cap_sbx"] == "outside-floor"
                selected.add((name, arguments.get("name"), arguments.get("kind"), arguments.get("through_alias")))
    assert total == 69
    expected = {
        (name, target, None, None)
        for name in ("test_cap6b_write_denied", "test_cap6b_read_denied")
        for target in ("skills", "plugin")
    } | {
        ("test_cap6b_symlink_root", None, None, alias) for alias in (False, True)
    } | {
        ("test_links_do_not_open_write_paths", target, kind, None)
        for target in ("skills", "plugin") for kind in ("symlink", "hardlink")
    }
    assert selected == expected
