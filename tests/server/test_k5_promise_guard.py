"""K5: the promise guard without the expert era (card K5 with #284's addition, U13 ①; ⓪Plan's Q6/Q8).

The guard catches a final answer that claims work was handed off or is in progress when nothing was:
"正在生成，稍等" on a turn that called no tool and has no background job.
- **The spawn tier is gone.** It caught "交给/让 <spawn name>" on the doer-first branch, and nothing in
  production sets its name any more. C7 deletes spawns.
- **The correction no longer says what is no longer true.** That was 「系统没有后台执行」 (there is
  background work) and 「直接点名（@分身名）」 (there are no spawns). It now says the answer is Arslan's
  own and nothing runs in the background for it. That holds whenever the guard fires: only on a turn
  with no tool call and no running job.
- `correct_zero_tool` is C7's to delete. K5 only drops the spawn name from its one `find_promise` call.
"""
import inspect

import pytest

from server.orchestrator import arslan, promise_guard
from server.services import runtime_messages

LOCALES = ("en", "zh", "ja", "es", "de", "fr")
STALE = ("后台执行", "分身", "@")


def _resynthesis_prompt() -> str:
    return promise_guard._CORRECTION_SYS + promise_guard._correction_user("正在生成，稍等")


def test_the_correction_texts_say_nothing_that_is_no_longer_true():
    texts = [_resynthesis_prompt()] + [runtime_messages.render("correction", loc) for loc in LOCALES]
    for text in texts:
        for word in STALE:
            assert word not in text, (word, text)


@pytest.mark.parametrize("locale", LOCALES)
def test_no_template_correction_trips_the_guard_itself(locale):
    assert promise_guard.find_promise(runtime_messages.render("correction", locale)) is None


def test_the_resynthesis_still_states_the_turns_real_state():
    prompt = _resynthesis_prompt()
    assert "这一轮没有调用任何工具" in prompt and "没有为它在后台运行任何任务" in prompt


def test_the_spawn_tier_is_gone():
    assert not hasattr(promise_guard, "spawn_promise_re")
    assert "spawn_name" not in inspect.signature(promise_guard.find_promise).parameters
    assert "spawn_name" not in inspect.signature(promise_guard.correct).parameters
    params = inspect.signature(arslan._handle_answer).parameters
    assert "intercept_spawn_name" not in params and "turn_delegated" not in params
    assert all("named_correction" not in runtime_messages.MESSAGES[loc] for loc in LOCALES)
