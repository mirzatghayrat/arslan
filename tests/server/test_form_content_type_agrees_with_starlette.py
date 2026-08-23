"""The upload endpoints must decide "is this multipart?" the same way Starlette does.

WHAT WENT WRONG. Three endpoints gated their multipart branch on a SUBSTRING test:

    if "multipart/form-data" in content_type:
        form = await request.form()

Starlette does not test the header that way. ``Request._get_form`` runs the header
through ``python_multipart.parse_options_header`` and compares the parsed MEDIA TYPE
for equality, so a parameter that merely CONTAINS the string routes elsewhere:

    Content-Type: application/x-www-form-urlencoded; boundary=multipart/form-data
      our substring check -> True   (enter the multipart branch)
      Starlette's parse   -> application/x-www-form-urlencoded  (urlencoded parser)

Two consequences, and the second is why this is a security test rather than a tidiness
one:

1. ``form.get("file")`` returns a plain ``str`` instead of an ``UploadFile``, so
   ``await upload.read()`` raises ``AttributeError`` — an unhandled 500 reachable by
   choosing a header value.
2. It reaches Starlette's urlencoded ``FormParser``, which is the parser whose
   ``max_fields`` / ``max_part_size`` limits CVE-2026-54283 says are silently ignored.
   That CVE is now fixed upstream — the cap was lifted 2026-08-23 and Starlette is
   >= 1.3.1. Point 1 is untouched by that: entering the multipart branch on a
   non-multipart request is our bug on any Starlette, which is why this stayed.

WHY THESE ASSERT STATUS CODES AND NOT SOURCE TEXT. A grep for the substring check
would pass the moment someone rewrote it in a different but equally loose way, and
would fail on a correct rewrite that happens to spell things differently. What has to
hold is a property of the running endpoint: a header whose media type is not multipart
must never enter the multipart branch. So each case is driven through the real app.

The discriminating observable is 500 (today) vs 4xx (fixed) — chosen because an
earlier draft of this test asserted only "not 200", which both the broken and the
fixed code satisfy. Every case below is also two-sided: honest multipart must keep
working, or "reject everything" would pass.

🔴 COVERAGE GAP, STATED RATHER THAN IMPLIED. Two of the three fixed call sites are
exercised end-to-end here: ``/api/v1/extract`` and ``/api/v1/spawns/{id}/knowledge``.
The third, ``/api/v1/collections/{id}/ingest``, is covered only INDIRECTLY — it calls
the same ``is_multipart_form`` helper, and the helper has its own agreement tests. It
is not driven through HTTP because its ``_get_or_404`` runs before the content-type
branch, so the case needs a persisted collection this fixture does not build. A
regression that changed only that endpoint's branch back to a substring test would
therefore NOT be caught here. If that endpoint's branching is ever edited, add the
end-to-end case rather than trusting this file.
"""
from __future__ import annotations

import importlib

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.migrations.versions._0009_knowledge import upgrade_sync
from server.db.models import Base, Spawn

# Headers whose media type is NOT multipart, but which contain the literal string
# somewhere a naive check will find it. Each is a real thing a client may send.
#
# 🔴 SPLIT DELIBERATELY, because the two groups fail for DIFFERENT reasons and an
# earlier draft lumped them together — which made one case pass for a reason the
# test did not claim, the exact shape of "green for the wrong reason":
#
#   urlencoded media type -> Starlette runs its urlencoded FormParser, the form is
#     POPULATED with plain strings, and .read() on a str is the unhandled 500. This
#     is also the group that reaches the parser CVE-2026-54283 is about.
#   any other media type  -> Starlette returns an EMPTY FormData, so the endpoint's
#     own "file required" check answers 400. No crash, but still the wrong branch,
#     so it needs its own assertion rather than riding on "not 500".
CRAFTED_URLENCODED = [
    'application/x-www-form-urlencoded; boundary=multipart/form-data',
    'application/x-www-form-urlencoded;x="multipart/form-data"',
]
CRAFTED_OTHER = [
    'text/plain; note=multipart/form-data',
]
CRAFTED = CRAFTED_URLENCODED + CRAFTED_OTHER
HONEST_MULTIPART = "multipart/form-data; boundary=BOUNDARY"
# A minimal, valid multipart body carrying no "file" part, so the endpoints reach
# their own "file required" check rather than failing inside the parser.
EMPTY_MULTIPART = b"--BOUNDARY--\r\n"


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """Async client over the real app (create_app), in-memory DB with FTS5."""
    monkeypatch.setenv("ARSLAN_API_TOKEN", "")
    monkeypatch.setenv("ARSLAN_DB_PATH", str(tmp_path / "ct.db"))
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))
    monkeypatch.setenv("ARSLAN_TEST_ROUTES", "1")

    import server.config as config

    importlib.reload(config)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(upgrade_sync)

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.db_maker = maker  # type: ignore[attr-defined]
        yield c
    await engine.dispose()


async def _spawn_id(client) -> int:
    async with client.db_maker() as db:
        row = Spawn(name="ct-probe", domain_category="test", system_prompt="p")
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


def _media_type(header: str) -> str:
    """What Starlette will conclude the media type is, using ITS parser.

    Imported here rather than reimplemented: the property under test is AGREEMENT
    with Starlette, and a second hand-rolled parser could only ever approximate it.
    ``python-multipart`` is a declared direct dependency (pyproject.toml).
    """
    from python_multipart.multipart import parse_options_header

    parsed, _ = parse_options_header(header)
    return parsed.decode("latin-1")


class TestOurCheckAgreesWithStarlette:
    """The pure-function half: no HTTP, just the two yardsticks side by side."""

    @pytest.mark.parametrize("header", CRAFTED)
    def test_crafted_headers_are_not_multipart_to_starlette(self, header):
        # Establishes the premise the endpoint tests rest on. Without this, a
        # green endpoint test could mean "Starlette also thought it was multipart".
        assert _media_type(header) != "multipart/form-data"
        assert "multipart/form-data" in header  # ...yet a substring check says yes

    def test_honest_multipart_is_multipart_to_starlette(self):
        assert _media_type(HONEST_MULTIPART) == "multipart/form-data"

    def test_helper_used_by_the_endpoints_matches_starlette(self):
        from server.api.media_type import is_multipart_form

        for header in CRAFTED:
            assert is_multipart_form(header) is False, header
        for header in (HONEST_MULTIPART, "  multipart/form-data  ; boundary=x",
                       "multipart/form-data", "Multipart/Form-Data"):
            assert is_multipart_form(header) is True, header
        # Absent / empty / junk must not be multipart either.
        for header in ("", "application/json", "not a media type"):
            assert is_multipart_form(header) is False, header

    def test_helper_agrees_with_starlette_even_where_starlette_is_odd(self):
        # The expectation below looks wrong and is not. parse_options_header
        # lower-cases only when the header carries NO parameters, so with a boundary
        # present an upper-cased media type stays upper-cased and Starlette's
        # equality check against b"multipart/form-data" fails. Our helper must
        # report the same thing, because the point is agreement — not correctness
        # about RFC case-insensitivity. Normalizing here would make us claim
        # multipart on a request Starlette has already routed elsewhere.
        from server.api.media_type import is_multipart_form

        odd = "MULTIPART/FORM-DATA; boundary=x"
        assert _media_type(odd) != "multipart/form-data"       # Starlette says no
        assert is_multipart_form(odd) is False                 # so do we

    @pytest.mark.parametrize("header", CRAFTED + [
        HONEST_MULTIPART, "MULTIPART/FORM-DATA; boundary=x", "Multipart/Form-Data",
        "multipart/form-data", "application/json", "", "not a media type",
        "  multipart/form-data  ; boundary=x",
    ])
    def test_helper_and_starlette_never_disagree(self, header):
        # The general form of the property, rather than a hand-picked list of
        # examples: for EVERY header in the table, our verdict must equal the
        # verdict Starlette's own parser reaches. A future change that "improves"
        # the helper in either direction fails here.
        from server.api.media_type import is_multipart_form

        assert is_multipart_form(header) == (_media_type(header) == "multipart/form-data"), header


class TestEndpointsDoNotEnterTheMultipartBranch:
    """The behavioural half, through the real app."""

    @pytest.mark.parametrize("header", CRAFTED_URLENCODED)
    async def test_extract_does_not_500(self, client, header):
        r = await client.post(
            "/api/v1/extract",
            headers={"Content-Type": header},
            content=b"file=notafile&compress=true",
        )
        # 500 is the signature of having entered the multipart branch and then
        # calling .read() on a str. Anything in the 4xx family means the request
        # was rejected as the malformed thing it is.
        assert r.status_code != 500, r.text
        assert 400 <= r.status_code < 500, r.status_code

    @pytest.mark.parametrize("header", CRAFTED_URLENCODED)
    async def test_knowledge_ingest_does_not_500(self, client, header):
        sid = await _spawn_id(client)
        # 🔴 The prefix matters and cost this test its first green: an earlier draft
        # posted to /spawns/{id}/knowledge, got 404, and PASSED — 404 satisfies
        # "4xx and not 500" while proving nothing at all. main.py:405 mounts this
        # router under /api/v1. The guard below is what makes a routing miss loud.
        r = await client.post(
            f"/api/v1/spawns/{sid}/knowledge",
            headers={"Content-Type": header},
            content=b"file=notafile&compress=true",
        )
        assert r.status_code != 404, "route not found — this test would pass vacuously"
        assert r.status_code != 500, r.text
        assert 400 <= r.status_code < 500, r.status_code

    @pytest.mark.parametrize("header", CRAFTED_OTHER)
    async def test_non_multipart_media_type_takes_the_json_branch(self, client, header):
        # This group never crashed, so "not 500" would pass on the broken code.
        # What distinguishes the branches is WHICH 400 comes back: the multipart
        # branch answers "file required" off an empty FormData, the json branch
        # answers with a JSON parse error. Assert the branch, not the status.
        r = await client.post(
            "/api/v1/extract",
            headers={"Content-Type": header},
            content=b"file=notafile",
        )
        assert r.status_code == 400, r.text
        assert "file required" not in r.text.lower(), (
            "answered from the multipart branch on a non-multipart media type"
        )

    async def test_honest_multipart_still_reaches_the_file_check(self, client):
        # The other side. If the fix simply stopped treating anything as multipart,
        # this would 400 with a JSON-decode error instead of "file required".
        r = await client.post(
            "/api/v1/extract",
            headers={"Content-Type": HONEST_MULTIPART},
            content=EMPTY_MULTIPART,
        )
        assert r.status_code == 400
        assert "file" in r.text.lower()

    async def test_honest_json_still_works(self, client):
        r = await client.post(
            "/api/v1/extract",
            headers={"Content-Type": "application/json"},
            content=b'{"url":""}',
        )
        assert r.status_code == 400
        assert "url" in r.text.lower()
