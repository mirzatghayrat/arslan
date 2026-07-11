import inspect

from server.orchestrator import arslan, router


def test_arslan_prompt_has_capability_self_block():
    assert "_CAPABILITY_SELF" in dir(arslan)
    txt = arslan._CAPABILITY_SELF
    assert "web_search" in txt
    assert "GitHub" in txt or "github" in txt
    assert "诚实红线" in txt  # never-claim-can't guard present


def test_router_system_biases_to_answer():
    s = router._SYSTEM
    assert "web_search" in s
    # doer-first cue present
    assert ("DEFAULT" in s) or ("默认" in s) or ("itself" in s)


def test_handle_answer_assembles_capability_self():
    # The answer path builds `system` from a concatenation; assert the capability block
    # is actually spliced in (assembling live would require DB/context). S3-M3 split
    # _handle_answer into a usage-ledger wrapper + _handle_answer_body — the system
    # assembly lives in the body.
    src = inspect.getsource(arslan._handle_answer_body)
    assert "_CAPABILITY_SELF" in src
