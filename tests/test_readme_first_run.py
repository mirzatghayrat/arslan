"""Guards on the first-run docs against the known first-run blockers.

These pin the things that break a stranger following the from-source docs
verbatim. Since the desktop-first rewrite, README.md deliberately carries NO
dev-run snippets — its contract (asserted below) is the download link plus a
pointer to docs/QUICKSTART.md, which is now the single home of the source
walkthrough. The snippet guards therefore run over QUICKSTART (and
CONTRIBUTING for the command-level checks), and the secret-key snippet is
additionally executed for real (behavioral tests) so the documented command
line provably does what the docs claim.

Logical lines: the secret snippet spans backslash-continuation lines, so static
checks fold continuations first — a per-physical-line scan would miss `>> .env`
landing on a continuation line.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "docs" / "QUICKSTART.md"]
DOC_IDS = ["QUICKSTART"]
# CONTRIBUTING carries the dev variant of the same commands (uv sync, env pins) but no
# secret snippet — it joins the command-level checks only.
CMD_DOCS = DOCS + [ROOT / "CONTRIBUTING.md"]
CMD_DOC_IDS = DOC_IDS + ["CONTRIBUTING"]


# --- README: desktop-first contract ------------------------------------------


def test_readme_is_desktop_first():
    """README's install story is the desktop app (v0.1.4 rewrite, user-ordered):
    the DMG download link plus a pointer to docs/QUICKSTART.md for source/Docker.
    The dev walkthrough must NOT regrow here — localhost URLs and uvicorn
    commands in the README were exactly what sent app users down the dev path."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "releases/latest/download/Arslan-macos-arm64.dmg" in text, (
        "README.md lost the desktop download link"
    )
    assert "docs/QUICKSTART.md" in text, (
        "README.md must point source/Docker users at docs/QUICKSTART.md"
    )
    for banned in ("uv sync", "uvicorn", "localhost:5173", "127.0.0.1:8741"):
        assert banned not in text, (
            f"README.md regrew the dev walkthrough ({banned!r}) — that content "
            f"lives in docs/QUICKSTART.md since the desktop-first rewrite"
        )


def _text(doc: Path) -> str:
    return doc.read_text(encoding="utf-8")


def _logical_lines(text: str) -> list[str]:
    """Fold backslash-newline continuations into single logical lines."""
    return re.sub(r"\\\n\s*", " ", text).splitlines()


# --- static guards (both docs) ----------------------------------------------


@pytest.mark.parametrize("doc", CMD_DOCS, ids=CMD_DOC_IDS)
def test_install_command_includes_server_extra(doc):
    """#1 first-run blocker: a bare ``uv sync`` installs only the CORE deps; the
    backend imports SQLAlchemy/aiosqlite/cryptography from the optional ``server``
    extra, so a bare sync yields ImportError at uvicorn boot."""
    text = _text(doc)
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("uv sync"):
            assert "--extra server" in stripped, (
                f"{doc.name} has a `uv sync` command missing `--extra server` "
                f"(the #1 first-run blocker): {stripped!r}"
            )
    assert "uv sync --extra dev --extra server" in text, (
        f"{doc.name} must show the canonical `uv sync --extra dev --extra server`"
    )


@pytest.mark.parametrize("doc", DOCS, ids=DOC_IDS)
def test_secret_generation_uses_python3_and_persists(doc):
    """Generation lines must use python3 (stock macOS has no `python`) and persist
    to .env (a fresh key each boot makes previously-stored BYOK keys undecryptable).
    Checked on LOGICAL lines: the snippet splits generation and `>> .env` across
    backslash continuations."""
    lines = [ln for ln in _logical_lines(_text(doc)) if "secrets.token_urlsafe" in ln]
    assert lines, f"{doc.name} lost the secret-generation snippet entirely"
    for ln in lines:
        assert "python3 -c" in ln, f"{doc.name} generation must use python3: {ln.strip()!r}"
        assert ".env" in ln, f"{doc.name} generation must persist to .env: {ln.strip()!r}"


@pytest.mark.parametrize("doc", CMD_DOCS, ids=CMD_DOC_IDS)
def test_no_bare_python_command(doc):
    """Stock macOS ships no `python`; every documented command must say python3.
    (`python -c` is not a substring of `python3 -c`, so a raw scan suffices.)"""
    assert "python -c" not in _text(doc), (
        f"{doc.name} documents a bare `python -c` command — stock macOS has no "
        f"`python`, the $() substitutes empty and poisons .env"
    )


@pytest.mark.parametrize("doc", DOCS, ids=DOC_IDS)
def test_secret_guard_requires_nonempty_value(doc):
    """The re-entry guard must NOT match an empty `ARSLAN_SECRET_KEY=` line: a
    failed generation used to write that line, and a guard matching it blocked
    self-healing forever. `^ARSLAN_SECRET_KEY=.` requires a non-empty value."""
    guards = [
        ln
        for ln in _logical_lines(_text(doc))
        if "grep" in ln and "ARSLAN_SECRET_KEY" in ln
    ]
    assert guards, f"{doc.name} lost the secret re-entry guard"
    for ln in guards:
        assert "^ARSLAN_SECRET_KEY=." in ln, (
            f"{doc.name} guard must require a NON-EMPTY value so a poisoned empty "
            f"line self-heals: {ln.strip()!r}"
        )


@pytest.mark.parametrize("doc", DOCS, ids=DOC_IDS)
def test_source_env_line_is_guarded(doc):
    """With auto-generation the default flow has NO .env — an unguarded
    `source .env` errors exactly on the happy path. Asserts the guarded sourcing
    line EXISTS (a reworded/unguarded rewrite must fail, not vacuously pass)."""
    sourcing = [
        ln
        for ln in _logical_lines(_text(doc))
        if "source .env" in ln or ". ./.env" in ln or re.search(r"(?<![\w.])\. \.env\b", ln)
    ]
    assert sourcing, f"{doc.name} lost its env-sourcing line entirely"
    for ln in sourcing:
        assert "[ -f .env ]" in ln, (
            f"{doc.name} sources .env unguarded (errors when .env is absent, "
            f"which is now the default): {ln.strip()!r}"
        )


# --- behavioral guards: run the documented snippet for real ------------------


def _extract_secret_snippet(doc: Path) -> str:
    """The literal snippet: the grep-guard line plus its backslash continuations."""
    lines = _text(doc).splitlines()
    start = next(
        i for i, ln in enumerate(lines) if "grep -q '^ARSLAN_SECRET_KEY=" in ln
    )
    block = [lines[start]]
    while block[-1].rstrip().endswith("\\"):
        block.append(lines[start + len(block)])
    return "\n".join(block)


def _run_snippet(
    snippet: str, cwd: Path, path_env: str, home: Path
) -> subprocess.CompletedProcess:
    # /bin/sh by absolute path: with a restricted PATH the shell itself must not
    # need a PATH lookup (subprocess resolves argv[0] via the CHILD env's PATH).
    # HOME is always an isolated tmp dir: the snippet seeds from
    # $HOME/.arslan/secret_key, and tests must never read the developer's real one.
    return subprocess.run(
        ["/bin/sh", "-c", snippet],
        cwd=cwd,
        env={"PATH": path_env, "HOME": str(home)},
        capture_output=True,
        text=True,
        timeout=30,
    )


def _env_value_after_source(cwd: Path) -> str:
    """What the documented `source .env` flow actually exports."""
    out = subprocess.run(
        ["/bin/sh", "-c", 'set -a; . ./.env; set +a; printf %s "$ARSLAN_SECRET_KEY"'],
        cwd=cwd,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    return out.stdout


@pytest.mark.parametrize("doc", DOCS, ids=DOC_IDS)
def test_snippet_without_python3_writes_nothing(doc, tmp_path):
    """No python3 on PATH -> the snippet must write NOTHING (the old version
    appended an empty `ARSLAN_SECRET_KEY=` line that permanently blocked
    regeneration and exported an empty secret)."""
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    real_grep = shutil.which("grep")
    assert real_grep, "grep required for this test"
    (fakebin / "grep").symlink_to(real_grep)
    cwd = tmp_path / "work"
    cwd.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    _run_snippet(_extract_secret_snippet(doc), cwd, str(fakebin), home)
    env_file = cwd / ".env"
    assert not env_file.exists() or "ARSLAN_SECRET_KEY" not in env_file.read_text(
        encoding="utf-8"
    ), f"{doc.name} snippet poisoned .env despite python3 being unavailable"


@pytest.mark.parametrize("doc", DOCS, ids=DOC_IDS)
def test_snippet_is_idempotent_and_writes_owner_only(doc, tmp_path):
    """Two runs -> ONE non-empty line, same value both times, .env owner-only."""
    snippet = _extract_secret_snippet(doc)
    path_env = os.environ.get("PATH", "/usr/bin:/bin")
    home = tmp_path / "home"
    home.mkdir()
    _run_snippet(snippet, tmp_path, path_env, home)
    first = (tmp_path / ".env").read_text(encoding="utf-8")
    _run_snippet(snippet, tmp_path, path_env, home)
    second = (tmp_path / ".env").read_text(encoding="utf-8")
    assert second == first, f"{doc.name} snippet is not idempotent"
    values = re.findall(r"^ARSLAN_SECRET_KEY=(.+)$", second, flags=re.M)
    assert len(values) == 1 and len(values[0]) >= 32, (
        f"{doc.name} snippet must persist exactly one strong secret: {second!r}"
    )
    assert (tmp_path / ".env").stat().st_mode & 0o077 == 0, (
        f"{doc.name} snippet leaves .env readable by group/other"
    )


@pytest.mark.parametrize("doc", DOCS, ids=DOC_IDS)
def test_snippet_heals_poisoned_env(doc, tmp_path):
    """A pre-poisoned empty `ARSLAN_SECRET_KEY=` line (from the old broken
    snippet) must not block regeneration; the sourced result is non-empty."""
    (tmp_path / ".env").write_text("ARSLAN_SECRET_KEY=\n", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    _run_snippet(_extract_secret_snippet(doc), tmp_path, os.environ.get("PATH", ""), home)
    assert _env_value_after_source(tmp_path).strip(), (
        f"{doc.name} snippet fails to heal a poisoned empty ARSLAN_SECRET_KEY line"
    )


@pytest.mark.parametrize("doc", DOCS, ids=DOC_IDS)
def test_snippet_seeds_from_persisted_secret_not_a_fresh_mint(doc, tmp_path):
    """A user who booted the default flow first (secret auto-generated + provider
    keys stored under it) and later adopts the .env pin must get the SAME secret —
    minting a fresh one would make every stored BYOK key undecryptable."""
    home = tmp_path / "home"
    (home / ".arslan").mkdir(parents=True)
    persisted = "persisted-secret-0123456789-0123456789"
    (home / ".arslan" / "secret_key").write_text(persisted, encoding="utf-8")
    _run_snippet(
        _extract_secret_snippet(doc), tmp_path, os.environ.get("PATH", ""), home
    )
    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert f"ARSLAN_SECRET_KEY={persisted}" in content, (
        f"{doc.name} snippet minted a fresh secret instead of seeding the "
        f"persisted one: {content!r}"
    )


@pytest.mark.parametrize("doc", DOCS, ids=DOC_IDS)
def test_snippet_tightens_preexisting_lax_env(doc, tmp_path):
    """Old-snippet users hold the BYOK-decrypting secret in a 644 .env with no
    chmod ever having run — a re-run of the documented snippet must tighten it
    without touching the existing value."""
    env_file = tmp_path / ".env"
    env_file.write_text("ARSLAN_SECRET_KEY=existing-value-0123456789012345\n", encoding="utf-8")
    os.chmod(env_file, 0o644)
    home = tmp_path / "home"
    home.mkdir()
    _run_snippet(_extract_secret_snippet(doc), tmp_path, os.environ.get("PATH", ""), home)
    assert env_file.read_text(encoding="utf-8") == (
        "ARSLAN_SECRET_KEY=existing-value-0123456789012345\n"
    ), f"{doc.name} snippet must never rewrite an existing pinned secret"
    assert env_file.stat().st_mode & 0o077 == 0, (
        f"{doc.name} snippet left a pre-existing .env readable by group/other"
    )
