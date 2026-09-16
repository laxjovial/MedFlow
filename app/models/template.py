"""Record template models — the facility's own chart fields.

A template field ("Blood group", "Next of kin"…) is defined once per
facility and filled in per patient. Sections group related fields on the
chart. ``record_template_values`` stores one value per (field, patient).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models._serial import serializable

VALUE_TYPES = ("text", "number", "date", "choice")


@serializable(None)
@dataclass
class TemplateField:
    """One facility-defined chart field."""

    label: str
    field_key: str = ""
    value_type: str = "text"
    choices: str | None = None
    unit: str | None = None
    section: str = "General"
    sort_order: int = 0
    active: bool = True
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    template_id: int | None = None

    def row_for_storage(self) -> dict[str, Any]:
        data = self.to_row()
        data["choices"] = self.choices or None
        data["unit"] = self.unit or None
        data["active"] = 1 if self.active else 0
        return data


@serializable(None)
@dataclass
class TemplateValue:
    """One filled-in value: a field, for one patient, by someone."""

    template_id: int
    patient_id: int
    value_text: str | None = None
    updated_by: str | None = None
    updated_at: str | None = None
    value_id: int | None = None


@dataclass
class TemplateEntry:
    """A field joined with the patient's value — what the chart displays."""

    template_id: int
    field_key: str
    label: str
    value_type: str
    choices: str | None
    unit: str | None
    section: str
    sort_order: int
    value_text: str | None
    updated_by: str | None
    updated_at: str | None

    def to_row(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "field_key": self.field_key,
            "label": self.label,
            "value_type": self.value_type,
            "choices": self.choices,
            "unit": self.unit,
            "section": self.section,
            "sort_order": self.sort_order,
            "value": self.value_text,
            "updated_by": self.updated_by,
            "updated_at": self.updated_at,
        }
