"""The Hands engine harness's judges (spec 2026-10-08-0157 §8.3): pure, so tested anywhere.
Each test pins one way an engine can disturb the user or lie, and that it is caught."""
from scripts.hands_harness import oracles
from scripts.hands_harness.cases import Result
from scripts.hands_harness.oracles import Sample


def s(t, front=1, pointer=(10.0, 10.0), order=(1, 2, 3)):
    return Sample(t=t, front_pid=front, pointer=pointer, order=order)


def test_nothing_moved_is_clean():
    assert oracles.disturbance(s(0), [s(0.02), s(0.04)], s(0.06)).ok


def test_a_front_change_even_briefly_is_caught():
    v = oracles.disturbance(s(0), [s(0.02), s(0.04, front=2), s(0.06)], s(0.08))
    assert any(x.startswith("O1") for x in v.violations)


def test_a_moved_pointer_and_a_raised_window_are_caught():
    v = oracles.disturbance(s(0), [s(0.02, pointer=(50.0, 10.0))], s(0.06, order=(3, 1, 2)))
    assert {x[:2] for x in v.violations} == {"O3", "O4"}


def test_a_micro_borrow_within_the_allowance_is_not_a_violation():
    events = [(1.0, False), (1.08, True)]
    assert oracles.key_window(events, 0, 10, borrow_ms=150).ok
    assert not oracles.key_window(events, 0, 10, borrow_ms=50).ok
    assert not oracles.key_window([(1.0, False)], 0, 10, borrow_ms=150).ok      # never given back


def test_typing_must_arrive_whole_and_nowhere_else():
    assert oracles.typed_exactly("hello world", "hello world", ["Weekend plan"]).ok
    lost = oracles.typed_exactly("hello world", "hello wrld", [""])
    assert lost.violations and lost.violations[0].startswith("O5")
    typed = "the quick brown fox jumps "
    leaked = oracles.typed_exactly(typed, typed, ["Weekend plan the quick brown"])
    assert any("reached the target" in v for v in leaked.violations)
    # A field that happens to share a short word with the typing is not a leak.
    assert oracles.typed_exactly(typed, typed, ["hello there"]).ok


def test_once_means_once():
    assert oracles.once(3, 4).ok
    assert not oracles.once(3, 5).ok          # ran twice
    assert not oracles.once(3, 3).ok          # never ran


def test_done_and_refused_must_be_true():
    assert not oracles.honest("done", happened=False).ok
    assert not oracles.honest("refused", happened=True).ok
    for word in ("sent_unconfirmed", "no_effect", "partly_done", None):
        assert oracles.honest(word, happened=True).ok and oracles.honest(word, happened=False).ok


def test_the_summary_counts_passes_per_case_and_engine():
    from scripts.hands_harness.run import summarize
    rows = [Result("click_save_once", "cua", "pass", "done", ms=80), Result("click_save_once", "cua", "fail", "done", ms=120,
            violations=["O6 happened 2 times, expected 1"]), Result("click_save_once", "agent-desktop", "pass", ms=900)]
    table = summarize(rows)
    assert "| click_save_once | cua | 1/2 | 100.0 |" in table
    assert "O6 happened 2 times" in table
    assert "| click_save_once | agent-desktop | 1/1 | 900 |" in table
