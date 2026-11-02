"""L11-1 (v0.1.64, card docs/plans/0164/K10-L11-folder-rules.md; the user's memory-plan item 15 and D5): output
language follows where the output goes. Chat follows the user's message, as before; a file follows the folder rules'
language when they name one, else the user's message, as the reply; a message to someone else follows that person's
language when it is known, else Arslan asks. The line rides in the turn's reference block, never the system prompt."""
from server.orchestrator import arslan


def test_the_line_says_where_a_files_and_a_messages_language_come_from():
    line = arslan.language_line("帮我写个总结")
    assert "Reply language for this turn: Chinese." in line
    assert "A file you write follows the folder rules' language when they name one" in line
    assert "otherwise it follows the user's message, as the reply does" in line
    assert "A message to someone else follows that person's language when you know it" in line
    assert "otherwise ask" in line


def test_the_stable_prefix_does_not_carry_it():
    system = arslan._build_answer_system()
    assert "folder rules' language" not in str(system)
