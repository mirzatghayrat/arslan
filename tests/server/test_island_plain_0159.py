"""0.1.59: the island shows a finished job's answer as plain text, not Markdown.

Seen recording the promo on v0.1.59-beta.2: the island's result card read
`**Copied 9 invoice PDFs**` with its asterisks and backticks, and "**Day 1**".
"""
import pytest

from server.services import desktop_status


@pytest.fixture(autouse=True)
def fresh():
    desktop_status._reset_for_tests()
    yield
    desktop_status._reset_for_tests()


def test_a_job_answer_reaches_the_island_without_markdown():
    answer = ("**Copied 9 invoice PDFs** to `~/ArslanDemo/Invoices/`:\n- January\n- February\n\n"
              "## Missing\n1. **March**, *July* and __November__ — see [the list](https://example.invalid/x)\n"
              "```\nls ~/ArslanDemo/Invoices\n```")
    desktop_status.push("turn_finished", conversation_id="c", outcome="ok", title="**Copy** the invoices",
                        summary=answer, work="job")
    event = desktop_status.island_feed()["events"][-1]
    assert event["title"] == "Copy the invoices"
    assert event["summary"] == ("Copied 9 invoice PDFs to ~/ArslanDemo/Invoices/: January February Missing "
                                "March, July and November — see the list ls ~/ArslanDemo/Invoices")
    assert not any(mark in event["summary"] for mark in ("**", "`", "##", "](", "- "))


def test_file_names_and_ordinary_text_are_left_alone():
    desktop_status.push("turn_finished", conversation_id="c", outcome="ok",
                        summary="Saved report_2026_v2.md and notes_final.txt; 3 * 4 = 12", work="job")
    assert desktop_status.island_feed()["events"][-1]["summary"] == "Saved report_2026_v2.md and notes_final.txt; 3 * 4 = 12"
