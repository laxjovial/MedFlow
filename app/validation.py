"""Reusable validators.

Validation is defense in depth: the UI calls :class:`PatientValidator` for
inline feedback, the service layer re-validates before persisting, and the
FastAPI backend validates again via Pydantic. Nothing trusts the layer above.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Callable

from app.errors import ValidationError

NAME_RE = re.compile(r"^[\w\u00C0-\u024F'.\- ]+$", re.UNICODE)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?[\d\s().\-]{7,20}$")
BP_RE = re.compile(r"^\d{2,3}\s*/\s*\d{2,3}$")
ID_FORMAT = "MF-{digits:06d}"


def required(value: Any, field: str, errors: dict, label: str) -> str:
    text = (value or "").strip() if isinstance(value, str) else value
    if not text:
        errors.setdefault(field, []).append(f"{label} is required.")
        return ""
    return str(text)


def matches(value: str, pattern: re.Pattern, field: str, errors: dict,
            label: str, hint: str) -> str:
    if value and not pattern.match(value):
        errors.setdefault(field, []).append(f"{label} {hint}")
    return value


def optional_number(value: Any, field: str, errors: dict, label: str,
                    low: float, high: float) -> float | None:
    text = (value or "").strip() if isinstance(value, str) else value
    if text in ("", None, "--"):
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        errors.setdefault(field, []).append(f"{label} must be a number.")
        return None
    if not low <= number <= high:
        errors.setdefault(field, []).append(
            f"{label} must be between {low:g} and {high:g}."
        )
        return None
    return number


def optional_date(value: Any, field: str, errors: dict, label: str) -> date | None:
    text = (value or "").strip() if isinstance(value, str) else value
    if text in ("", None, "--"):
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    errors.setdefault(field, []).append(
        f"{label} must be a date (e.g. 2001-12-31)."
    )
    return None


class PatientValidator:
    """Validates patient demographics and optional clinical baseline fields.

    Age, blood pressure, heart rate, and weight are optional but validated
    when present. Name is required and must not contain digits.
    """

    MAX_AGE = 130
    BP_SYSTOLIC = (50, 260)
    BP_DIASTOLIC = (20, 200)
    HEART_RATE = (20, 260)

    def validate(self, data: dict) -> dict:
        errors: dict[str, list[str]] = {}
        clean: dict[str, Any] = {}

        clean["name"] = required(data.get("name"), "name", errors, "Full name")
        matches(clean["name"], NAME_RE, "name", errors, "Full name",
                "contains invalid characters (letters, spaces, apostrophes, "
                "hyphens only).")

        age = optional_number(data.get("age"), "age", errors, "Age", 0, self.MAX_AGE)
        clean["age"] = None if age is None else int(age)

        bp = (data.get("blood_pressure") or "").strip()
        if bp:
            matches(bp, BP_RE, "blood_pressure", errors, "Blood pressure",
                    "must look like 120/80.")
            if "/" in bp and BP_RE.match(bp):
                systolic, diastolic = (int(p) for p in bp.replace(" ", "").split("/"))
                lo_s, hi_s = self.BP_SYSTOLIC
                lo_d, hi_d = self.BP_DIASTOLIC
                if not lo_s <= systolic <= hi_s:
                    errors.setdefault("blood_pressure", []).append(
                        f"Systolic must be {lo_s}-{hi_s}."
                    )
                if not lo_d <= diastolic <= hi_d:
                    errors.setdefault("blood_pressure", []).append(
                        f"Diastolic must be {lo_d}-{hi_d}."
                    )
        clean["blood_pressure"] = bp or None

        hr = optional_number(data.get("heart_rate"), "heart_rate", errors,
                             "Heart rate", *self.HEART_RATE)
        clean["heart_rate"] = None if hr is None else int(hr)

        weight = optional_number(data.get("weight"), "weight", errors,
                                 "Weight (kg)", 0.2, 700)
        clean["weight"] = weight

        email = (data.get("email") or "").strip()
        matches(email, EMAIL_RE, "email", errors, "Email",
                "is not a valid address.")
        clean["email"] = email or None

        phone = (data.get("phone") or "").strip()
        matches(phone, PHONE_RE, "phone", errors, "Phone",
                "is not a valid phone number.")
        clean["phone"] = phone or None

        clean["date_of_birth"] = optional_date(
            data.get("date_of_birth"), "date_of_birth", errors, "Date of birth"
        )

        clean["sex"] = (data.get("sex") or "").strip() or None
        clean["address"] = (data.get("address") or "").strip() or None
        clean["medical_history"] = (data.get("medical_history") or "").strip() or None
        clean["diagnosis"] = (data.get("diagnosis") or "").strip() or None
        clean["notes"] = (data.get("notes") or "").strip() or None

        if clean["date_of_birth"] and clean["age"] is not None:
            derived = self.age_from_dob(clean["date_of_birth"])
            if derived is not None and abs(derived - clean["age"]) > 1:
                errors.setdefault("age", []).append(
                    f"Age disagrees with date of birth (DOB implies ~{derived})."
                )

        if errors:
            raise ValidationError(errors)
        return clean

    @staticmethod
    def age_from_dob(dob: date, today: date | None = None) -> int | None:
        today = today or date.today()
        years = today.year - dob.year
        if (today.month, today.day) < (dob.month, dob.day):
            years -= 1
        return years


def validate_with(checks: list[tuple[str, Callable[[], Any]]]) -> dict:
    """Run named validation callables, collecting every field error."""
    errors: dict[str, list[str]] = {}
    results: dict[str, Any] = {}
    for name, check in checks:
        try:
            results[name] = check()
        except ValidationError as exc:
            errors.update(exc.errors)
    if errors:
        raise ValidationError(errors)
    return results
