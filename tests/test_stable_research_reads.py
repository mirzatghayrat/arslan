"""No network: admission policy permits real rereads but never failed retries."""
import hashlib
from unittest.mock import AsyncMock

import httpx
import pytest

from evals.companion.stable_research import VerifiedPublicReads

URL = "https://example.com/fixed-public-source"
BODY = b"Synthetic source"
DIGEST = hashlib.sha256(BODY).hexdigest()


async def test_successful_source_is_really_refetched():
    get = AsyncMock(side_effect=[httpx.Response(200, content=BODY, request=httpx.Request("GET", URL)) for _ in range(2)])
    reader = VerifiedPublicReads({URL: DIGEST}, get, lambda _: False)
    assert (await reader(URL)).content == BODY
    assert (await reader(URL)).content == BODY
    assert get.await_count == 2 and len(reader.transport) == 2
    assert not reader.failed


@pytest.mark.parametrize("failure", ["network", "status", "body"])
async def test_failed_source_cannot_be_retried(failure):
    get = AsyncMock()
    if failure == "network":
        get.side_effect = httpx.ConnectError("synthetic transport failure")
    else:
        get.return_value = httpx.Response(503 if failure == "status" else 200,
            content=BODY if failure == "status" else b"Changed source", request=httpx.Request("GET", URL))
    reader = VerifiedPublicReads({URL: DIGEST}, get, lambda _: True)
    with pytest.raises((httpx.HTTPError, RuntimeError)):
        await reader(URL)
    with pytest.raises(RuntimeError, match="failed_public_read"):
        await reader(URL)
    assert get.await_count == 1


async def test_unlisted_url_is_refused_without_network():
    get = AsyncMock()
    reader = VerifiedPublicReads({URL: DIGEST}, get, lambda _: False)
    with pytest.raises(RuntimeError, match="unapproved"):
        await reader("https://example.com/other")
    get.assert_not_awaited()
