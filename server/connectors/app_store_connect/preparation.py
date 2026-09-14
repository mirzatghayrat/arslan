"""Local materials and exact field diffs. Nothing here sends a remote write."""
import hashlib
import json
from typing import Literal

from pydantic import Field

from .client import ASCError
from .contracts import LOCALIZATION_FIELDS, AppTarget, Record, Snapshot, Text, capabilities


def snapshot_hash(snapshot: Snapshot) -> str:
    value = snapshot.model_dump(mode="json", exclude={"fetched_at", "evidence_kind"})
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class FieldChange(Record):
    localization_id: str
    locale: str
    field: str
    before: Text | None
    after: Text | None


class DraftPlan(Record):
    target: AppTarget
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    changes: tuple[FieldChange, ...]
    status: Literal["local_draft_not_authorized"] = "local_draft_not_authorized"

    def diff_hash(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


def prepare_materials(snapshot: Snapshot, *, desired_locales: tuple[str, ...]) -> dict:
    if not desired_locales or len(desired_locales) > 100 or len(set(desired_locales)) != len(desired_locales):
        raise ASCError("asc_invalid_locales")
    locales = {item.locale: item for item in snapshot.localizations if item.locale}
    issues = []
    for locale in desired_locales:
        if locale not in locales:
            issues.append({"code": "locale_missing", "locale": locale})
            continue
        entry = locales[locale]
        # A preparation checklist, not a claim of Apple's complete submission rules.
        for field in ("description", "supportUrl"):
            if field not in entry.fields:
                issues.append({"code": "field_not_returned", "locale": locale, "field": field})
            elif not entry.fields[field]:
                issues.append({"code": "field_empty", "locale": locale, "field": field})
        if not entry.screenshot_sets:
            issues.append({"code": "screenshots_not_present", "locale": locale})
        for group in entry.screenshot_sets:
            if not group.screenshots:
                issues.append({"code": "screenshot_set_empty", "locale": locale, "set_id": group.id})
            for shot in group.screenshots:
                if shot.delivery_state != "COMPLETE":
                    issues.append({"code": "screenshot_not_verified_complete", "locale": locale, "screenshot_id": shot.id})
    if any(not item.locale for item in snapshot.localizations):
        issues.append({"code": "locale_not_returned"})
    if not snapshot.version.state:
        issues.append({"code": "version_state_not_returned"})
    return {
        "kind": "asc_local_materials", "status": "preparation_only", "snapshot_hash": snapshot_hash(snapshot),
        "source": snapshot.model_dump(mode="json"), "issues": issues,
        "facts_requiring_user_confirmation": ["privacy_declarations", "content_rights", "export_compliance",
                                               "review_contact_and_credentials", "current_submission_requirements"],
        "not_checked": ["screenshot_dimensions_and_visual_quality", "build_processing", "agreements",
                        "pricing_and_availability", "full_platform_submission_validation"],
        "capabilities": capabilities(),
    }


def plan_draft(snapshot: Snapshot, desired: dict[str, dict[str, str | None]]) -> DraftPlan:
    if not desired or len(desired) > 100:
        raise ASCError("asc_invalid_draft")
    localizations = {item.locale: item for item in snapshot.localizations if item.locale}
    changes = []
    for locale, fields in sorted(desired.items()):
        if locale not in localizations:
            raise ASCError("asc_locale_missing")
        current = localizations[locale]
        if not isinstance(fields, dict) or not fields or set(fields) - LOCALIZATION_FIELDS:
            raise ASCError("asc_field_not_supported")
        for name, after in sorted(fields.items()):
            if name not in current.fields:
                raise ASCError("asc_before_value_unknown")
            if after is not None and (not isinstance(after, str) or len(after) > 20000):
                raise ASCError("asc_invalid_field_value")
            if current.fields[name] != after:
                changes.append(FieldChange(localization_id=current.id, locale=locale, field=name,
                                           before=current.fields[name], after=after))
    if not changes:
        raise ASCError("asc_no_changes")
    return DraftPlan(target=snapshot.target, snapshot_hash=snapshot_hash(snapshot), changes=tuple(changes))


def require_fresh(plan: DraftPlan, latest: Snapshot):
    if plan.target != latest.target or plan.snapshot_hash != snapshot_hash(latest):
        raise ASCError("asc_draft_stale_reapproval_required")


def reconcile_fields(plan: DraftPlan, latest: Snapshot) -> tuple[dict, ...]:
    """Per-field readback only. 'not_applied' never automatically retries a write.

    Unknown result must be read before making a decision. A matching value proves
    the current remote state, not attribution to our prior request.
    """
    if plan.target != latest.target:
        raise ASCError("asc_app_binding_mismatch")
    localizations = {item.id: item for item in latest.localizations}
    results = []
    for change in plan.changes:
        item = localizations.get(change.localization_id)
        status = "unknown"
        if item and item.locale == change.locale and change.field in item.fields:
            current = item.fields[change.field]
            status = "verified" if current == change.after else "not_applied" if current == change.before else "conflict"
        results.append({"localization_id": change.localization_id, "locale": change.locale,
                        "field": change.field, "status": status,
                        "readback_hash": snapshot_hash(latest), "automatic_retry": False})
    return tuple(results)
