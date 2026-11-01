"""The home folder in free text the phone is shown, as `~` (IPB: the #651 and #650 reviews). Only a whole path:
never inside another path or another user's name, next to any script, in any letter case or Unicode form."""
import unicodedata

import pytest

from server.services.home_text import fold_home

HOME = "/Users/alice"


@pytest.mark.parametrize("text, shown", [
    ("Read /Users/alice/Documents/a.md", "Read ~/Documents/a.md"),
    ("Read /Users/alice", "Read ~"),
    ("Read /Users/alice, then stop", "Read ~, then stop"),
    ("See /Users/alice.", "See ~."),                                       # a sentence's full stop
    ("把/Users/alice/Downloads里的文件整理好", "把~/Downloads里的文件整理好"),   # next to Chinese text
    ("打开/Users/alice里", "打开~里"),
    ("Open file:///Users/alice/x.md", "Open file://~/x.md"),
    ("Read /USERS/ALICE/a.md", "Read ~/a.md"),                              # the same folder, another case
    ("Read /Users/alicex/a.md", "Read /Users/alicex/a.md"),                 # another user, same start
    ("Read /Users/alice.old/a.md", "Read /Users/alice.old/a.md"),
    ("Read /Users/alice-2/a", "Read /Users/alice-2/a"),
    ("Read /Users/alice~/a", "Read /Users/alice~/a"),
    ("Read /Volumes/Disk/Users/alice/a.md", "Read /Volumes/Disk/Users/alice/a.md"),   # inside another path
    ("Read x/Users/alice/a", "Read x/Users/alice/a"),
])
def test_the_home_becomes_a_tilde_only_as_a_whole_path(text, shown):
    assert fold_home(text, HOME) == shown


def test_a_dot_in_the_home_is_a_dot():
    assert fold_home("/Users/john.doe/a and /Users/johnXdoe/b", "/Users/john.doe") == "~/a and /Users/johnXdoe/b"


def test_another_unicode_form_of_the_home_is_the_home():
    nfc = "/Users/jos" + chr(0xE9)
    assert fold_home(unicodedata.normalize("NFD", nfc) + "/x", nfc) == "~/x"
    assert fold_home(nfc + "/x", unicodedata.normalize("NFD", nfc)) == "~/x"


@pytest.mark.parametrize("home", ["/", ""])
def test_a_root_or_empty_home_is_never_replaced(home):
    assert fold_home("Copy /etc/hosts to /tmp/a", home) == "Copy /etc/hosts to /tmp/a"
