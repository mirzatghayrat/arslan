"""Bounded GET-only adapter over a future trusted broker (or synthetic fixture).

No HTTP client, auth header, private key or URL supplied by a model is accepted.
The transport must enforce its own credential boundary and reject redirects.
No production transport is provided until the W11 security gate is satisfied.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Literal, Protocol
from urllib.parse import parse_qsl, urlsplit

from pydantic import TypeAdapter, ValidationError

from .contracts import (
    LOCALIZATION_FIELDS, App, AppTarget, Localization, RemoteID, Screenshot, ScreenshotSet, Snapshot, Version,
)


class ASCError(ValueError):
    def __init__(self, code: str, *, retry_after: int | None = None):
        self.code, self.retry_after = code, retry_after
        super().__init__(code)  # Never echo a remote body or potentially signed URL.


class ReadTransport(Protocol):
    async def get(self, path: str, query: tuple[tuple[str, str], ...]) -> tuple[int, dict, dict]: ...


def production_client(*args, **kwargs):
    raise ASCError("isolated_credential_broker_review_required")


def _resource(raw, expected: str) -> tuple[str, dict]:
    if not isinstance(raw, dict) or raw.get("type") != expected:
        raise ASCError("asc_schema_changed")
    try:
        identity = TypeAdapter(RemoteID).validate_python(raw.get("id"))
    except ValidationError as exc:
        raise ASCError("asc_schema_changed") from exc
    attributes = raw.get("attributes", {})
    if not isinstance(attributes, dict):
        raise ASCError("asc_schema_changed")
    return identity, attributes


class ReadClient:
    def __init__(self, transport: ReadTransport, *, evidence_kind: Literal["fixture", "broker_read"],
                 max_requests: int = 100, max_resources: int = 5000):
        if evidence_kind not in {"fixture", "broker_read"}:
            raise ASCError("asc_invalid_evidence_kind")
        if (type(max_requests) is not int or type(max_resources) is not int
                or not 1 <= max_requests <= 1000 or not 1 <= max_resources <= 10000):
            raise ASCError("asc_invalid_budget")
        self.transport, self.evidence_kind = transport, evidence_kind
        self.remaining_requests, self.remaining_resources = max_requests, max_resources

    async def _get(self, path: str, query=()) -> dict:
        if self.remaining_requests <= 0:
            raise ASCError("asc_request_budget_exceeded")
        self.remaining_requests -= 1
        try:
            async with asyncio.timeout(15):
                status, body, headers = await self.transport.get(path, query)
        except (TimeoutError, OSError) as exc:
            raise ASCError("asc_read_unavailable") from exc
        if status == 429:
            delay = str(headers.get("retry-after", ""))
            raise ASCError("asc_rate_limited", retry_after=min(int(delay), 3600) if delay.isdecimal() else None)
        if status in {401, 403, 404}:
            raise ASCError({401: "asc_connection_expired", 403: "asc_permission_denied", 404: "asc_target_missing"}[status])
        if status != 200:
            raise ASCError("asc_redirect_denied" if 300 <= status < 400 else "asc_read_failed")
        if not isinstance(body, dict):
            raise ASCError("asc_schema_changed")
        try:
            size = len(json.dumps(body, allow_nan=False).encode())
        except (TypeError, ValueError) as exc:
            raise ASCError("asc_schema_changed") from exc
        if size > 2_000_000:
            raise ASCError("asc_response_too_large")
        return body

    async def _list(self, path: str, kind: str) -> list[tuple[str, dict]]:
        query: tuple[tuple[str, str], ...] = (("limit", "200"),)
        seen_pages, seen_ids, output = set(), set(), []
        while True:
            if query in seen_pages:
                raise ASCError("asc_pagination_loop")
            seen_pages.add(query)
            body = await self._get(path, query)
            rows = body.get("data")
            if not isinstance(rows, list):
                raise ASCError("asc_schema_changed")
            self.remaining_resources -= len(rows)
            if self.remaining_resources < 0:
                raise ASCError("asc_resource_budget_exceeded")
            for raw in rows:
                identity, attributes = _resource(raw, kind)
                if identity in seen_ids:
                    raise ASCError("asc_duplicate_resource")
                seen_ids.add(identity)
                output.append((identity, attributes))
            links = body.get("links", {})
            if not isinstance(links, dict):
                raise ASCError("asc_schema_changed")
            next_url = links.get("next")
            if next_url is None:
                return output
            if not isinstance(next_url, str) or len(next_url) > 4000:
                raise ASCError("asc_pagination_target_denied")
            parsed = urlsplit(next_url)
            if (parsed.scheme != "https" or parsed.netloc != "api.appstoreconnect.apple.com"
                    or parsed.path != path or parsed.fragment or any(ord(c) < 33 for c in next_url)):
                raise ASCError("asc_pagination_target_denied")
            pairs = parse_qsl(parsed.query, keep_blank_values=True)
            if (not pairs or len({key for key, _ in pairs}) != len(pairs)
                    or any(key not in {"cursor", "limit"} for key, _ in pairs)):
                raise ASCError("asc_pagination_target_denied")
            query = tuple(sorted(pairs))

    async def snapshot(self, target: AppTarget) -> Snapshot:
        """Select exact project-bound App/version IDs; never pick by display name."""
        try:
            body = await self._get(f"/v1/apps/{target.app_id}")
            identity, attrs = _resource(body.get("data"), "apps")
            app = App(id=identity, name=attrs.get("name"), bundle_id=attrs.get("bundleId"),
                      primary_locale=attrs.get("primaryLocale"))
            if app.id != target.app_id or app.bundle_id != target.bundle_id:
                raise ASCError("asc_app_binding_mismatch")
            versions = await self._list(f"/v1/apps/{target.app_id}/appStoreVersions", "appStoreVersions")
            selected = [(i, a) for i, a in versions if i == target.version_id]
            if len(selected) != 1:
                raise ASCError("asc_version_missing")
            identity, attrs = selected[0]
            version = Version(id=identity, version=attrs.get("versionString"), platform=attrs.get("platform"),
                              state=attrs.get("appVersionState"))
            if version.platform != target.platform:
                raise ASCError("asc_platform_mismatch")
            localizations, seen_locales = [], set()
            rows = await self._list(f"/v1/appStoreVersions/{target.version_id}/appStoreVersionLocalizations",
                                    "appStoreVersionLocalizations")
            for identity, attrs in rows:
                locale = attrs.get("locale")
                if locale is not None and (not isinstance(locale, str) or locale in seen_locales):
                    raise ASCError("asc_locale_ambiguous")
                seen_locales.add(locale)
                sets = []
                for set_id, set_attrs in await self._list(
                        f"/v1/appStoreVersionLocalizations/{identity}/appScreenshotSets", "appScreenshotSets"):
                    screenshots = []
                    for shot_id, shot_attrs in await self._list(f"/v1/appScreenshotSets/{set_id}/appScreenshots", "appScreenshots"):
                        delivery = shot_attrs.get("assetDeliveryState") or {}
                        if not isinstance(delivery, dict):
                            raise ASCError("asc_schema_changed")
                        screenshots.append(Screenshot(id=shot_id, filename=shot_attrs.get("fileName"),
                            size=shot_attrs.get("fileSize"), checksum=shot_attrs.get("sourceFileChecksum"),
                            delivery_state=delivery.get("state")))
                    sets.append(ScreenshotSet(id=set_id, display_type=set_attrs.get("screenshotDisplayType"),
                                              screenshots=tuple(screenshots)))
                localizations.append(Localization(id=identity, locale=locale,
                    fields={key: attrs[key] for key in LOCALIZATION_FIELDS if key in attrs}, screenshot_sets=tuple(sets)))
            return Snapshot(target=target, app=app, version=version, localizations=tuple(localizations),
                            fetched_at=datetime.now(timezone.utc), evidence_kind=self.evidence_kind)
        except ValidationError as exc:
            raise ASCError("asc_schema_changed") from exc
