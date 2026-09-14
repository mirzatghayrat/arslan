"""Style evidence is scoped data, not a capability grant or a global preference."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from arslan.companion.contracts import Contract


class StyleReference(Contract):
    source_kind: Literal["file", "url", "library", "artifact"]
    source_ref: Annotated[str, Field(min_length=1, max_length=1000)]
    polarity: Literal["positive", "negative"]
    rationale: Annotated[str, Field(min_length=1, max_length=2000)]
    interpretation: Literal["tentative", "confirmed"] = "tentative"

    @model_validator(mode="after")
    def valid_reference(self):
        if not self.source_ref.strip() or not self.rationale.strip():
            raise ValueError("style_reference_required")
        return self


def reference_data(reference: StyleReference | None) -> dict | None:
    return reference.model_dump(mode="json") if reference else None
