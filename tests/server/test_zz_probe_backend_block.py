"""THROWAWAY PROBE — never merged. Plain unit test that fails on every platform.

Data point 1 of 2: does a red `backend` check block a merge on its own?

Deliberately NOT marked @pytest.mark.macos, so `-m macos` does not select it and
the macos job stays green. No platform gate either, so the drift guard has
nothing to say about it — the point is to leave backend as the only red check.
"""


def test_probe_fails_everywhere():
    assert False, "deliberate failure: proving a red backend check blocks the merge"
