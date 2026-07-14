"""Guards on the README Quickstart against the two known first-run blockers.

These are the top two things that break a stranger following README.md verbatim.
Both are pure text assertions on README.md so a future edit can't silently
reintroduce them. See docs/superpowers/plans (S4.0-B) for context.
"""
from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"


def _readme_text() -> str:
    return README.read_text(encoding="utf-8")


def test_quickstart_install_command_includes_server_extra():
    """#1 first-run blocker: a bare ``uv sync`` installs only the CORE deps, but
    the backend imports SQLAlchemy/aiosqlite/cryptography which live in the
    OPTIONAL ``server`` extra (pyproject ``[project.optional-dependencies]``).
    Following a bare ``uv sync`` yields an ImportError at ``uvicorn server.main:app``
    boot. Pin the canonical command so the README can't regress to bare ``uv sync``.
    """
    text = _readme_text()
    for line in text.splitlines():
        stripped = line.strip()
        # ignore prose mentions like "plain `uv sync`"; only guard command lines
        if stripped.startswith("uv sync"):
            assert "--extra server" in stripped, (
                f"README has a `uv sync` command missing `--extra server` "
                f"(the #1 first-run blocker): {stripped!r}"
            )
    assert "uv sync --extra dev --extra server" in text, (
        "README Quickstart must use the canonical `uv sync --extra dev --extra server`"
    )


def test_quickstart_secret_key_is_generated_once_and_reused():
    """Regenerating ARSLAN_SECRET_KEY on every boot makes previously-stored BYOK
    secrets undecryptable (the key is derived from ARSLAN_SECRET_KEY + a per-install
    salt). The Quickstart must generate the secret ONCE and reuse it. Concretely:
    any line that generates a random secret must PERSIST it to ``.env`` — never
    inline a fresh ``$(python -c 'secrets...')`` straight into the run command.
    """
    text = _readme_text()
    for line in text.splitlines():
        if "secrets.token_urlsafe" in line:
            assert ".env" in line, (
                "README generates a random ARSLAN_SECRET_KEY without persisting it to "
                ".env — a fresh key each boot makes previously-stored BYOK keys "
                f"undecryptable. Generate once and reuse: {line.strip()!r}"
            )
    assert ".env" in text, (
        "README should persist ARSLAN_SECRET_KEY to .env and reuse it across restarts"
    )
