from copy import deepcopy

import pytest

from server.connectors.app_store_connect.client import ASCError, ReadClient, production_client
from server.connectors.app_store_connect.contracts import AppTarget, capabilities
from server.connectors.app_store_connect.preparation import (
    plan_draft, prepare_materials, reconcile_fields, require_fresh,
)

TARGET = AppTarget(app_id="123", version_id="version-1", platform="IOS", bundle_id="com.example.app")


def resource(kind, identity, **attrs):
    return {"type": kind, "id": identity, "attributes": attrs}


class FixtureTransport:
    def __init__(self):
        self.calls = []
        self.pages = {
            "/v1/apps/123": {"data": resource("apps", "123", name="Same name", bundleId="com.example.app", primaryLocale="en-US")},
            "/v1/apps/123/appStoreVersions": {"data": [resource("appStoreVersions", "version-1", versionString="1.2",
                                                              platform="IOS", appVersionState="PREPARE_FOR_SUBMISSION")]},
            "/v1/appStoreVersions/version-1/appStoreVersionLocalizations": {"data": [resource(
                "appStoreVersionLocalizations", "locale-1", locale="en-US", description="Before", supportUrl="https://example.com/help")]},
            "/v1/appStoreVersionLocalizations/locale-1/appScreenshotSets": {"data": [resource(
                "appScreenshotSets", "set-1", screenshotDisplayType="APP_IPHONE_67")]},
            "/v1/appScreenshotSets/set-1/appScreenshots": {"data": [resource("appScreenshots", "shot-1",
                fileName="screenshot.png", fileSize=100, sourceFileChecksum="checksum", assetDeliveryState={"state": "COMPLETE"},
                assetToken="DO_NOT_FORWARD", uploadOperations=[{"requestHeaders": [{"value": "DO_NOT_FORWARD"}]}])]},
        }

    async def get(self, path, query):
        self.calls.append(("GET", path, query))
        value = self.pages[path]
        return value if isinstance(value, tuple) else (200, deepcopy(value), {})


async def snapshot(transport=None, **kwargs):
    return await ReadClient(transport or FixtureTransport(), evidence_kind="fixture", **kwargs).snapshot(TARGET)


async def test_readonly_exact_target_snapshot_and_no_upload_secrets():
    transport = FixtureTransport()
    value = await snapshot(transport)
    assert len(transport.calls) == 5 and {call[0] for call in transport.calls} == {"GET"}
    assert value.app.id == "123" and value.version.id == "version-1" and value.evidence_kind == "fixture"
    assert "DO_NOT_FORWARD" not in value.model_dump_json()
    report = prepare_materials(value, desired_locales=("en-US", "zh-Hans"))
    assert report["issues"] == [{"code": "locale_missing", "locale": "zh-Hans"}]
    assert "privacy_declarations" in report["facts_requiring_user_confirmation"]
    assert report["status"] == "preparation_only"


@pytest.mark.parametrize("status,code", [(401, "asc_connection_expired"), (403, "asc_permission_denied"),
    (404, "asc_target_missing"), (302, "asc_redirect_denied"), (500, "asc_read_failed")])
async def test_error_body_not_echoed(status, code):
    transport = FixtureTransport()
    transport.pages["/v1/apps/123"] = (status, {"error": "secret_remote_body"}, {"location": "https://evil.test"})
    with pytest.raises(ASCError, match=code) as raised:
        await snapshot(transport)
    assert "secret_remote_body" not in str(raised.value)
    assert len(transport.calls) == 1


async def test_rate_limit_is_reported_not_silently_retried():
    transport = FixtureTransport()
    transport.pages["/v1/apps/123"] = (429, {}, {"retry-after": "20"})
    with pytest.raises(ASCError, match="asc_rate_limited") as raised:
        await snapshot(transport)
    assert raised.value.retry_after == 20 and len(transport.calls) == 1


@pytest.mark.parametrize("url", [
    "https://evil.test/v1/apps/123/appStoreVersions?cursor=2",
    "https://api.appstoreconnect.apple.com.evil.test/v1/apps/123/appStoreVersions?cursor=2",
    "https://api.appstoreconnect.apple.com/v1/apps/456/appStoreVersions?cursor=2",
    "http://api.appstoreconnect.apple.com/v1/apps/123/appStoreVersions?cursor=2",
    "https://api.appstoreconnect.apple.com/v1/apps/123/appStoreVersions?authorization=secret",
    "https://api.appstoreconnect.apple.com/v1/apps/123/appStoreVersions?cursor=2&cursor=3",
    "https://api.appstoreconnect.apple.com:443/v1/apps/123/appStoreVersions?cursor=2",
])
async def test_untrusted_pagination_never_changes_target(url):
    transport = FixtureTransport()
    transport.pages["/v1/apps/123/appStoreVersions"]["links"] = {"next": url}
    with pytest.raises(ASCError, match="asc_pagination_target_denied"):
        await snapshot(transport)
    assert len(transport.calls) == 2


async def test_pagination_collects_exact_version_without_guessing():
    class Pages(FixtureTransport):
        async def get(self, path, query):
            if path == "/v1/apps/123/appStoreVersions" and not dict(query).get("cursor"):
                self.calls.append(("GET", path, query))
                return 200, {"data": [], "links": {
                    "next": "https://api.appstoreconnect.apple.com/v1/apps/123/appStoreVersions?cursor=second&limit=200"}}, {}
            return await super().get(path, query)
    transport = Pages()
    assert (await snapshot(transport)).version.id == "version-1"
    assert len(transport.calls) == 6


@pytest.mark.parametrize("change,code", [
    ("wrong_app", "asc_app_binding_mismatch"), ("wrong_bundle", "asc_app_binding_mismatch"),
    ("wrong_platform", "asc_platform_mismatch"), ("missing_version", "asc_version_missing"),
    ("duplicate_locale", "asc_locale_ambiguous"), ("bad_id", "asc_schema_changed"),
])
async def test_missing_ambiguous_or_changed_targets_refused(change, code):
    transport = FixtureTransport()
    app = transport.pages["/v1/apps/123"]["data"]
    version = transport.pages["/v1/apps/123/appStoreVersions"]["data"][0]
    locales = transport.pages["/v1/appStoreVersions/version-1/appStoreVersionLocalizations"]["data"]
    if change == "wrong_app":
        app["id"] = "456"
    elif change == "wrong_bundle":
        app["attributes"]["bundleId"] = "com.other.app"
    elif change == "wrong_platform":
        version["attributes"]["platform"] = "MAC_OS"
    elif change == "missing_version":
        version["id"] = "other-version"
    elif change == "duplicate_locale":
        locales.append(resource("appStoreVersionLocalizations", "locale-2", locale="en-US"))
    elif change == "bad_id":
        locales[0]["id"] = "../../other-app"
    with pytest.raises(ASCError, match=code):
        await snapshot(transport)


async def test_read_budget_is_finite():
    with pytest.raises(ASCError, match="asc_request_budget_exceeded"):
        await snapshot(max_requests=2)
    with pytest.raises(ASCError, match="asc_resource_budget_exceeded"):
        await snapshot(max_resources=1)


async def test_dynamic_state_preserved_and_missing_fields_not_guessed():
    transport = FixtureTransport()
    transport.pages["/v1/apps/123/appStoreVersions"]["data"][0]["attributes"]["appVersionState"] = "NEW_APPLE_STATE"
    attrs = transport.pages["/v1/appStoreVersions/version-1/appStoreVersionLocalizations"]["data"][0]["attributes"]
    del attrs["description"]
    attrs["supportUrl"] = None
    value = await snapshot(transport)
    assert value.version.state == "NEW_APPLE_STATE"
    report = prepare_materials(value, desired_locales=("en-US",))
    assert {item["code"] for item in report["issues"]} == {"field_not_returned", "field_empty"}
    with pytest.raises(ASCError, match="asc_before_value_unknown"):
        plan_draft(value, {"en-US": {"description": "New"}})


async def test_local_diff_staleness_and_per_field_readback():
    before = await snapshot()
    plan = plan_draft(before, {"en-US": {"description": "After", "supportUrl": "https://example.com/new"}})
    require_fresh(plan, before)
    assert len(plan.changes) == 2 and plan.status == "local_draft_not_authorized"
    assert len(plan.diff_hash()) == 64
    transport = FixtureTransport()
    attrs = transport.pages["/v1/appStoreVersions/version-1/appStoreVersionLocalizations"]["data"][0]["attributes"]
    attrs["description"] = "After"  # Timeout may still have applied this field.
    latest = await snapshot(transport)
    with pytest.raises(ASCError, match="asc_draft_stale_reapproval_required"):
        require_fresh(plan, latest)
    result = reconcile_fields(plan, latest)
    assert [item["status"] for item in result] == ["verified", "not_applied"]
    assert all(not item["automatic_retry"] for item in result)
    attrs["description"] = "Concurrent change"
    del attrs["supportUrl"]
    assert [item["status"] for item in reconcile_fields(plan, await snapshot(transport))] == ["conflict", "unknown"]


@pytest.mark.parametrize("desired,code", [
    ({"zh-Hans": {"description": "New"}}, "asc_locale_missing"),
    ({"en-US": {"privacy": "No tracking"}}, "asc_field_not_supported"),
    ({"en-US": {"description": "Before"}}, "asc_no_changes"),
])
async def test_local_draft_does_not_guess_or_expand(desired, code):
    with pytest.raises(ASCError, match=code):
        plan_draft(await snapshot(), desired)


def test_production_credentials_and_writes_remain_disabled():
    with pytest.raises(ASCError, match="isolated_credential_broker_review_required"):
        production_client()
    flags = capabilities()
    assert flags["platform_api"]["update_draft"]
    assert not any(value for key, value in flags["local"].items() if key != "prepare_materials")
