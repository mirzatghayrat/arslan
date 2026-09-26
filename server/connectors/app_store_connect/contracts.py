"""Read subset checked against Apple's OpenAPI 4.4.1 on 2026-09-15.

Unknown platform/state strings are preserved, not guessed into older enums.
Presence is distinct from null/empty for sparse and evolving API responses.
"""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

RemoteID = Annotated[str, Field(pattern=r"^[A-Za-z0-9-]{1,100}$")]
Text = Annotated[str, Field(max_length=20000)]
SCHEMA_VERSION = "4.4.1"
SCHEMA_SOURCE = "https://developer.apple.com/sample-code/app-store-connect/app-store-connect-openapi-specification.zip"
SCHEMA_SHA256 = "9386762084aa7156a9d5aab20526daf8d4ca423ddaebb0b3fffd2ef6fd836370"


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AppTarget(Record):
    app_id: Annotated[str, Field(pattern=r"^[0-9]{1,30}$")]
    version_id: RemoteID
    platform: Literal["IOS", "MAC_OS", "TV_OS", "VISION_OS"]
    bundle_id: Annotated[str, Field(min_length=1, max_length=200)]


class App(Record):
    id: RemoteID
    name: Text | None = None
    bundle_id: Text | None = None
    primary_locale: Text | None = None


class Version(Record):
    id: RemoteID
    version: Text | None = None
    platform: Text | None = None
    state: Text | None = None


class Screenshot(Record):
    id: RemoteID
    filename: Text | None = None
    size: Annotated[int, Field(ge=0, strict=True)] | None = None
    checksum: Text | None = None
    delivery_state: Text | None = None


class ScreenshotSet(Record):
    id: RemoteID
    display_type: Text | None = None
    screenshots: tuple[Screenshot, ...] = ()


class Localization(Record):
    id: RemoteID
    locale: Text | None = None
    fields: dict[str, Text | None]
    screenshot_sets: tuple[ScreenshotSet, ...] = ()


class Snapshot(Record):
    target: AppTarget
    app: App
    version: Version
    localizations: tuple[Localization, ...]
    fetched_at: datetime
    source_schema: Literal["4.4.1"] = SCHEMA_VERSION
    evidence_kind: Literal["fixture", "broker_read"]


LOCALIZATION_FIELDS = frozenset({"description", "keywords", "marketingUrl", "promotionalText", "supportUrl", "whatsNew"})


def capabilities() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "platform_api": {"read_metadata": True, "update_draft": True, "upload_screenshots": True},
        "local": {"prepare_materials": True, "read_account": False, "write_draft": False,
                  "upload_screenshots": False, "submit_review": False, "publish": False},
        "blocked_reason": "isolated_credential_broker_review_required",
        "key_scope": "unknown_until_broker_attestation",
        "scope_note": "project_target_is_a_local_restriction_not_a_single_app_key_claim",
    }
