"""DIFF1 (v0.1.64, card README §3.10b): `GET /conversations/{id}/changes/{run_id}/diff`, one changed path of
one turn as a line diff, the S3 saved copy against the file now, for the reader opened from Overview's
Changes. Read only; only paths `changes` lists, inside a folder the reader may read, never a dot-path or a
secret-shaped name, never through a link."""
import json
from pathlib import Path

import pytest

from server import config
from server.db.models import Run
from server.services import checkpoints, file_reader

BEFORE = "# Plan\n\nOptions\n1. one\n2. two\n3. three\n\nDecision\nnot yet\n"
AFTER = "# Plan\n\nOptions\n1. one\n2. two, better\n3. three\n\nDecision\nTime Machine\nstarted 09:31\n"


@pytest.fixture(autouse=True)
def _plenty_of_disk(monkeypatch):
    monkeypatch.setattr(checkpoints, "_free_bytes", lambda path: 2 * checkpoints.MIN_FREE)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(config, "data_dir", lambda: data)
    work = (tmp_path / "work")
    work.mkdir()
    (work / "plan.md").write_text(BEFORE)
    (work / "old.txt").write_text("a\nb\n")
    (work / "pic.bin").write_bytes(b"\x89PNG\x00\x01")
    (work / "nul.dat").write_bytes(b"a\x00b\n")                 # valid UTF-8, but a NUL: not text
    (work / ".notes").mkdir()
    (work / ".notes" / "a.md").write_text("x\n")
    work = work.resolve()

    async def roots():
        return [work]
    monkeypatch.setattr(file_reader, "roots", roots)
    checkpoints._reset_for_tests()
    yield work
    checkpoints._reset_for_tests()


async def _turn(client, ws, change, conversation_id="c1") -> int:
    async with client.db_maker() as db:
        run = Run(conversation_id=conversation_id, spawn_name="Arslan", user_message="x", status="done")
        db.add(run)
        await db.commit()
        await db.refresh(run)
    await checkpoints.ensure(run.id, [ws])
    change()
    await checkpoints.finish(run.id)
    return run.id


def _edit_all():
    def change(ws):
        (ws / "plan.md").write_text(AFTER)
        (ws / "new.txt").write_text("hello\nworld\n")
        (ws / "old.txt").unlink()
        (ws / "pic.bin").write_bytes(b"\x89PNG\x00\x02")
        (ws / "nul.dat").write_bytes(b"a\x00c\n")
        (ws / ".notes" / "a.md").write_text("y\n")
    return change


async def _diff(client, ws, run_id, path, conversation_id="c1", folder=None):
    return await client.get(f"/api/v1/conversations/{conversation_id}/changes/{run_id}/diff",
                            params={"folder": folder or str(ws), "path": path})


async def test_an_edited_file_is_every_line_with_its_op_and_both_numbers(client, ws):
    run_id = await _turn(client, ws, lambda: _edit_all()(ws))
    body = (await _diff(client, ws, run_id, "plan.md")).json()
    assert body["reason"] is None and body["kind"] == "edited" and body["since"] is False
    assert (body["added"], body["removed"]) == (3, 2)
    ops = [(op, old, new, text) for op, old, new, text in body["lines"]]
    assert ops[:4] == [(" ", 1, 1, "# Plan"), (" ", 2, 2, ""), (" ", 3, 3, "Options"), (" ", 4, 4, "1. one")]
    assert ("-", 5, None, "2. two") in ops and ("+", None, 5, "2. two, better") in ops
    assert ("-", 9, None, "not yet") in ops and ("+", None, 10, "started 09:31") in ops
    # The two sides rebuild exactly: the old file from " " and "-", the new one from " " and "+".
    assert [t for op, _, _, t in ops if op != "+"] == BEFORE.splitlines()
    assert [t for op, _, _, t in ops if op != "-"] == AFTER.splitlines()


async def test_a_made_file_is_all_added_and_a_deleted_one_all_removed(client, ws):
    run_id = await _turn(client, ws, lambda: _edit_all()(ws))
    made = (await _diff(client, ws, run_id, "new.txt")).json()
    assert made["kind"] == "made" and made["lines"] == [["+", None, 1, "hello"], ["+", None, 2, "world"]]
    gone = (await _diff(client, ws, run_id, "old.txt")).json()
    assert gone["kind"] == "deleted" and gone["lines"] == [["-", 1, None, "a"], ["-", 2, None, "b"]]


async def test_it_says_so_when_the_file_changed_after_the_turn(client, ws):
    run_id = await _turn(client, ws, lambda: _edit_all()(ws))
    (ws / "plan.md").write_text(AFTER + "later\n")
    body = (await _diff(client, ws, run_id, "plan.md")).json()
    assert body["since"] is True and ["+", None, 11, "later"] in body["lines"]


async def test_only_a_listed_path_of_this_conversations_kept_turn(client, ws):
    run_id = await _turn(client, ws, lambda: _edit_all()(ws))
    assert (await _diff(client, ws, run_id, "plan.md")).status_code == 200            # positive control
    assert (await _diff(client, ws, run_id, "plan.md", conversation_id="c2")).status_code == 404
    assert (await _diff(client, ws, run_id + 99, "plan.md")).status_code == 404
    assert (await _diff(client, ws, run_id, "untouched.md")).status_code == 404
    assert (await _diff(client, ws, run_id, "../work/plan.md")).status_code == 404
    assert (await _diff(client, ws, run_id, "plan.md", folder=str(ws.parent))).status_code == 404
    path = checkpoints.root_dir() / str(run_id) / "manifest.json"
    data = json.loads(path.read_text())
    # Listed by a manifest written outside the sandbox: a path out of the folder, and .git (it goes back whole).
    (ws.parent / "escape.txt").write_text("PRIVATE\n")
    data["roots"][0]["finished"]["../escape.txt"] = {"now": None, "saved": None}
    data["roots"][0]["finished"][".git/HEAD"] = {"now": None, "saved": None}
    path.write_text(json.dumps(data))
    escape = await _diff(client, ws, run_id, "../escape.txt")
    assert escape.status_code == 404 and "PRIVATE" not in escape.text
    assert (await _diff(client, ws, run_id, ".git/HEAD")).json()["detail"]["code"] == "not_listed"
    data["created_at"] -= 10 ** 9                                                     # an earlier run's copy
    path.write_text(json.dumps(data))
    assert (await _diff(client, ws, run_id, "plan.md")).json()["detail"]["code"] == "not_listed"


async def test_a_folder_the_reader_cannot_read_is_refused(client, ws, monkeypatch):
    run_id = await _turn(client, ws, lambda: _edit_all()(ws))

    async def elsewhere():
        return [ws.parent / "data"]
    monkeypatch.setattr(file_reader, "roots", elsewhere)
    assert (await _diff(client, ws, run_id, "plan.md")).status_code == 404


async def test_a_dot_path_or_a_secret_shaped_name_is_never_shown(client, ws):
    run_id = await _turn(client, ws, lambda: _edit_all()(ws))
    hidden = await _diff(client, ws, run_id, ".notes/a.md")
    assert hidden.status_code == 403 and hidden.json()["detail"]["code"] == "hidden"
    path = checkpoints.root_dir() / str(run_id) / "manifest.json"
    data = json.loads(path.read_text())                       # listed as if the run had changed a key file
    data["roots"][0]["finished"]["keys/app.pem"] = {"now": None, "saved": None}
    path.write_text(json.dumps(data))
    assert (await _diff(client, ws, run_id, "keys/app.pem")).status_code == 403


async def test_binary_or_too_big_has_a_reason_and_no_lines(client, ws, monkeypatch):
    run_id = await _turn(client, ws, lambda: _edit_all()(ws))
    body = (await _diff(client, ws, run_id, "pic.bin")).json()
    assert (body["reason"], body["lines"]) == ("not_text", [])
    assert (await _diff(client, ws, run_id, "nul.dat")).json()["reason"] == "not_text"
    monkeypatch.setattr(checkpoints, "DIFF_MAX_BYTES", 16)
    body = (await _diff(client, ws, run_id, "plan.md")).json()
    assert (body["reason"], body["lines"]) == ("too_big", [])


async def test_a_tampered_copy_or_clone_name_is_not_shown(client, ws, tmp_path):
    run_id = await _turn(client, ws, lambda: _edit_all()(ws))
    path = checkpoints.root_dir() / str(run_id) / "manifest.json"
    data = json.loads(path.read_text())
    clone = checkpoints.root_dir() / str(run_id) / data["roots"][0]["clone"]
    (clone / "plan.md").write_text("swapped\n")
    assert (await _diff(client, ws, run_id, "plan.md")).json()["reason"] == "copy_changed"
    (tmp_path / "plan.md").write_text(BEFORE)                # what "../../.." would reach, with the saved hash
    data["roots"][0]["clone"] = "../../.."                    # the manifest can be written outside the sandbox
    path.write_text(json.dumps(data))
    assert (await _diff(client, ws, run_id, "plan.md")).json()["reason"] == "copy_changed"


async def test_a_link_put_where_the_file_was_is_not_followed(client, ws, tmp_path):
    run_id = await _turn(client, ws, lambda: _edit_all()(ws))
    secret = tmp_path / "outside.txt"
    secret.write_text("PRIVATE\n")
    (ws / "plan.md").unlink()
    (ws / "plan.md").symlink_to(secret)
    body = (await _diff(client, ws, run_id, "plan.md")).json()
    assert body["reason"] == "not_text" and "PRIVATE" not in json.dumps(body)


# -- ②Main's review of #553: the boundary is the reader's roots, walked from there with no link followed --

@pytest.fixture
def nested(tmp_path, monkeypatch):
    """A reader root with the kept folder two levels down (`a/proj`), and an outside folder shaped like it."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(config, "data_dir", lambda: data)
    reader = (tmp_path / "reader")
    (reader / "a" / "proj" / "sub").mkdir(parents=True)
    (reader / "a" / "proj" / "notes.txt").write_text("mine\n")
    (reader / "a" / "proj" / "sub" / "deep.txt").write_text("deep\n")
    outside = tmp_path / "outside"
    (outside / "proj").mkdir(parents=True)
    (outside / "proj" / "notes.txt").write_text("PROBE-LINKED\n")
    (outside / "credentials").write_text("aws_secret=PROBE-DOTDOT\n")
    reader = reader.resolve()

    async def roots():
        return [reader]
    monkeypatch.setattr(file_reader, "roots", roots)
    checkpoints._reset_for_tests()
    yield reader, outside.resolve()
    checkpoints._reset_for_tests()


def _write(path, text):
    path.write_text(text)


async def test_a_link_put_above_the_kept_folder_reads_nothing_outside(client, nested):
    reader, outside = nested
    kept = reader / "a" / "proj"
    run_id = await _turn(client, kept, lambda: _write(kept / "notes.txt", "mine, edited\n"))
    assert (await _diff(client, kept, run_id, "notes.txt")).status_code == 200      # positive control
    (reader / "a").rename(reader / "a-moved")
    (reader / "a").symlink_to(outside, target_is_directory=True)                 # no manifest change
    probe = await _diff(client, kept, run_id, "notes.txt")
    assert probe.status_code == 404 and "PROBE-LINKED" not in probe.text


async def test_a_dotdot_root_in_a_rewritten_manifest_reads_nothing_outside(client, nested):
    reader, outside = nested
    kept = reader / "a" / "proj"
    run_id = await _turn(client, kept, lambda: _write(kept / "notes.txt", "mine, edited\n"))
    path = checkpoints.root_dir() / str(run_id) / "manifest.json"
    data = json.loads(path.read_text())
    data["roots"][0]["path"] = f"{reader}/../outside"
    data["roots"][0]["finished"] = {"credentials": {"now": {"sha256": "x"}, "saved": None}}
    path.write_text(json.dumps(data))
    probe = await _diff(client, kept, run_id, "credentials", folder=f"{reader}/../outside")
    assert probe.status_code == 404 and "PROBE-DOTDOT" not in probe.text


async def test_a_folder_that_cannot_be_walked_is_a_refusal_not_a_server_error(client, nested):
    reader, _ = nested
    kept = reader / "a" / "proj"
    run_id = await _turn(client, kept, lambda: _write(kept / "sub" / "deep.txt", "deep, edited\n"))
    assert (await _diff(client, kept, run_id, "sub/deep.txt")).status_code == 200   # positive control
    (kept / "sub").chmod(0)                                                       # unreadable now
    try:
        refused = await _diff(client, kept, run_id, "sub/deep.txt")
    finally:
        (kept / "sub").chmod(0o755)
    assert refused.status_code == 404 and refused.json()["detail"]["code"] == "not_listed"


async def test_a_dot_folder_between_the_reader_root_and_the_kept_folder_is_hidden(client, tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(config, "data_dir", lambda: data)
    reader = tmp_path / "reader"
    kept = reader / ".config" / "app"
    kept.mkdir(parents=True)
    (kept / "settings.txt").write_text("a\n")
    reader, kept = reader.resolve(), kept.resolve()

    async def roots():
        return [reader]
    monkeypatch.setattr(file_reader, "roots", roots)
    checkpoints._reset_for_tests()
    try:
        run_id = await _turn(client, kept, lambda: _write(kept / "settings.txt", "b\n"))
        hidden = await _diff(client, kept, run_id, "settings.txt")
    finally:
        checkpoints._reset_for_tests()
    assert hidden.status_code == 403 and hidden.json()["detail"]["code"] == "hidden"


def test_the_walk_itself_follows_no_link_below_its_base(nested):
    """The resolve check and the walk each stop the link above; this pins the walk alone (a link made between
    the check and the open)."""
    reader, outside = nested
    assert checkpoints._read_side(reader, ("a", "proj", "notes.txt")) == b"mine\n"   # positive control
    (reader / "a").rename(reader / "a-moved")
    (reader / "a").symlink_to(outside, target_is_directory=True)
    with pytest.raises(checkpoints.NoDiff) as refused:
        checkpoints._read_side(reader, ("a", "proj", "notes.txt"))
    assert refused.value.code == "not_listed"


async def test_a_link_made_between_the_check_and_the_open_reads_nothing_outside(client, nested, monkeypatch):
    """The race the walk from the reader root closes: `a` becomes a link after the folder was checked and
    before the file is opened."""
    reader, outside = nested
    kept = reader / "a" / "proj"
    run_id = await _turn(client, kept, lambda: _write(kept / "notes.txt", "mine, edited\n"))
    real = checkpoints._read_side

    def swap_then_read(base, parts):
        if not Path(base).is_relative_to(checkpoints.root_dir()) and not (reader / "a").is_symlink():
            (reader / "a").rename(reader / "a-moved")
            (reader / "a").symlink_to(outside, target_is_directory=True)
        return real(base, parts)
    monkeypatch.setattr(checkpoints, "_read_side", swap_then_read)
    probe = await _diff(client, kept, run_id, "notes.txt")
    assert (reader / "a").is_symlink()                                          # the swap did happen
    assert probe.status_code == 404 and "PROBE-LINKED" not in probe.text
