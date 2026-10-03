"""Memory input contracts and trusted caller policy; model text is never authority."""
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from arslan.companion.content_policy import contains_credential, normalized_memory
from arslan.companion.contracts import Contract, Identifier
from arslan.companion.design import StyleReference


class MemoryError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class MemoryScope(Contract):
    kind: Literal["global", "project", "domain", "expert", "task"]
    id: Identifier | None = None

    @model_validator(mode="after")
    def consistent(self):
        if (self.kind == "global") != (self.id is None):
            raise ValueError("only global memory scope has no scope ID")
        return self


class MemoryWrite(Contract):
    content: Annotated[str, Field(min_length=1, max_length=8000)]
    kind: Literal["preference", "project_fact", "style_rule", "experience"] = "preference"
    scope: MemoryScope
    sensitivity: Literal["normal", "sensitive", "unknown"] = "normal"
    use_policy: Literal["local_only", "cloud_allowed"] = "local_only"
    sensitive_acknowledged: bool = False
    topic: Annotated[str, Field(max_length=100)] | None = None
    style_reference: StyleReference | None = None
    # 0.1.52 S4: membership of the always-in-view sets. "about_you" is a global
    # preference, "notes" is Arslan's global note about this Mac and setup
    # (kind experience). Everything else is picked by relevance per turn.
    core: Literal["about_you", "notes"] | None = None
    valid_from: AwareDatetime | None = None
    review_at: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def usable_content(self):
        if not self.content.strip():
            raise ValueError("memory content must not be blank")
        if self.style_reference and (self.kind != "style_rule" or self.scope.kind != "project"):
            raise ValueError("style_reference_project_required")
        if self.core and (self.scope.kind != "global"
                          or self.kind != ("preference" if self.core == "about_you" else "experience")):
            raise ValueError("core_memory_kind_mismatch")
        if self.expires_at and self.valid_from and self.expires_at <= self.valid_from:
            raise ValueError("memory expiry must follow effective time")
        return self


@dataclass(frozen=True)
class MemoryActor:
    """Constructed only by authenticated API/TaskService, never from tool arguments."""
    origin: Literal["user", "host", "worker", "extractor"]
    owner_id: str = "local"
    task_id: str | None = None
    project_id: str | None = None
    domain_id: str | None = None
    expert_id: str | None = None
    explicit_save_ref: str | None = None
    explicit_save_digest: str | None = None
    allow_global_save: bool = False
    cloud_memory_allowed: bool = False
    # 0.1.52 (D1): a normal fact noticed after a turn takes effect at once,
    # visible and undoable. Set only by the trusted task context, for origin
    # "extractor"; the extractor reads only the user's own messages.
    auto_activate_noticed: bool = False
    # 0.1.52 S4 (D2): Arslan's own note about this Mac/setup (kind "experience")
    # takes effect at once when the turn read nothing from outside. Set only by
    # the memory_note executor from the turn's own tracking, never from arguments.
    auto_activate_own_notes: bool = False
    no_learning: bool = False
    temporary: bool = False
    source_message_id: int | None = None
    source_run_id: int | None = None
    conversation_id: str | None = None


@dataclass(frozen=True)
class WriteDecision:
    status: str
    sensitivity: str
    use_policy: str
    confirmation_kind: str | None


def decide_write(write: MemoryWrite, actor: MemoryActor) -> WriteDecision:
    if actor.origin not in {"user", "host", "worker", "extractor"}:
        raise MemoryError("invalid_memory_actor")
    if actor.no_learning or actor.temporary:
        raise MemoryError("learning_disabled")
    if contains_credential(write.content) or (write.style_reference and contains_credential(write.style_reference.model_dump_json())):
        raise MemoryError("credentials_not_memory")
    if write.scope.kind == "task":
        raise MemoryError("task_state_is_not_long_term_memory")
    if actor.origin != "user":
        allowed = {
            "project": actor.project_id, "domain": actor.domain_id, "expert": actor.expert_id,
        }
        if write.scope.kind != "global" and write.scope.id != allowed.get(write.scope.kind):
            raise MemoryError("memory_scope_denied")
    # Sensitive inference is never saved silently, even if the model labels it normal.
    import re
    sensitive = write.sensitivity
    if sensitive == "unknown" and actor.origin == "user" and write.sensitive_acknowledged:
        sensitive = "sensitive"
    if re.search(r"\b(?:birthday|diagnosis|medical|passport|salary|bank account|home address)\b"
                 r"|(?:生日|诊断|病史|身份证|护照|工资|银行账户|家庭住址|精确位置)",
                 write.content + (write.style_reference.model_dump_json() if write.style_reference else ""), re.IGNORECASE):
        sensitive = "sensitive"
    import hashlib
    content_digest = hashlib.sha256(normalized_memory(write.content).encode()).hexdigest()
    user_confirmation = actor.origin == "user" or (
        actor.origin == "host" and actor.explicit_save_ref is not None
        and actor.explicit_save_digest == content_digest
        and (write.scope.kind != "global" or actor.allow_global_save)
    )
    if sensitive != "normal" and not (actor.origin == "user" and write.sensitive_acknowledged):
        user_confirmation = False
    # Existing host explicit-save digests bind text only, not this new evidence.
    # Require a user review rather than letting an inferred reference ride along.
    if write.style_reference and (actor.origin != "user" or write.style_reference.interpretation != "confirmed"):
        user_confirmation = False
    auto_noticed = (not user_confirmation and actor.origin == "extractor" and actor.auto_activate_noticed
                    and sensitive == "normal" and not write.style_reference)
    own_note = (not user_confirmation and not auto_noticed and actor.origin == "host"
                and actor.auto_activate_own_notes and write.kind == "experience"
                and write.scope.kind == "global" and sensitive == "normal" and not write.style_reference)
    if user_confirmation:
        use_policy = write.use_policy if (actor.origin == "user" or actor.cloud_memory_allowed) else "local_only"
        kind = "user_form" if actor.origin == "user" else "explicit_user_request"
    elif auto_noticed or own_note:
        use_policy = "cloud_allowed" if actor.cloud_memory_allowed else "local_only"
        kind = "auto_noticed" if auto_noticed else "arslan_note"
    else:
        use_policy, kind = "local_only", None
    return WriteDecision(
        status="active" if (user_confirmation or auto_noticed or own_note) else "proposed",
        sensitivity=sensitive,
        use_policy=use_policy,
        confirmation_kind=kind,
    )


def naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    from datetime import UTC
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value
