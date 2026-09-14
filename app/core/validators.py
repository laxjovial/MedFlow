"""Field validation and normalisation.

Validation lives here, and is called by the service layer rather than by the
widgets. The form does surface errors inline, but it does so by catching
:class:`~app.core.exceptions.ValidationError` from the service — so the rules
cannot be bypassed by calling the service directly, and a future web client
inherits them for free.

Bounds come from :class:`~app.config.settings.ValidationSettings`, not from
literals, so a deployment can widen or tighten what MedFlow accepts.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Mapping

from app.config.settings import ValidationSettings
from app.core.exceptions import ValidationError

#: Human-readable labels, used to build error messages.
PATIENT_FIELD_LABELS: dict[str, str] = {
    "first_name": "First name",
    "last_name": "Last name",
    "age_years": "Age",
    "sex": "Sex",
    "phone": "Phone",
    "email": "Email",
    "address": "Address",
    "blood_pressure": "Blood pressure",
    "heart_rate": "Heart rate",
    "weight": "Weight",
    "height": "Height",
    "medical_history": "Medical history",
    "notes": "Notes",
    "diagnosis": "Diagnosis",
}

#: Inputs that mean "not recorded". The pre-refactor application wrote ``--``
#: into empty numeric fields, so those values must round-trip as empty.
_PLACEHOLDER_VALUES = frozenset(
    {"", "-", "--", "---", "n/a", "na", "none", "none stated", "not recorded", "unknown"}
)

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"
PHONE_PATTERN = r"^[0-9+()\-.\s]{5,25}$"


def label_for(field_name: str) -> str:
    """Display name for a field, falling back to a tidied version of the key."""
    return PATIENT_FIELD_LABELS.get(field_name, field_name.replace("_", " ").capitalize())


def is_blank(value: Any) -> bool:
    """Whether a value means "not recorded"."""
    if value is None:
        return True
    return str(value).strip().lower() in _PLACEHOLDER_VALUES


def clean_text(value: Any) -> str:
    """Normalise a text value: strip, collapse internal whitespace, blank out placeholders."""
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    if text.lower() in _PLACEHOLDER_VALUES:
        return ""
    # Collapse runs of spaces and tabs, but preserve deliberate line breaks.
    lines = [re.sub(r"[ \t]{2,}", " ", line).strip() for line in text.split("\n")]
    return "\n".join(lines).strip()


class FieldValidator:
    """Validates individual values, accumulating errors rather than failing fast.

    Reporting every problem at once lets a form highlight all offending fields in
    a single pass instead of making the user resubmit repeatedly.
    """

    def __init__(self, settings: ValidationSettings) -> None:
        self.settings = settings
        self.errors: dict[str, str] = {}
        self._compiled_bp = re.compile(settings.blood_pressure_pattern)
        self._compiled_hr = re.compile(settings.heart_rate_pattern)
        self._compiled_email = re.compile(EMAIL_PATTERN)
        self._compiled_phone = re.compile(PHONE_PATTERN)

    # ---------- primitives ----------

    def text(
        self,
        field_name: str,
        value: Any,
        *,
        required: bool = False,
        max_length: int | None = None,
    ) -> str:
        """Clean a text value and check its length."""
        cleaned = clean_text(value)
        label = label_for(field_name)

        if not cleaned:
            if required:
                self._fail(field_name, f"{label} is required.")
            return ""

        limit = max_length if max_length is not None else self.settings.max_short_field_length
        if len(cleaned) > limit:
            self._fail(field_name, f"{label} must be {limit} characters or fewer.")
        return cleaned

    def free_text(
        self,
        field_name: str,
        value: Any,
        *,
        max_length: int | None = None,
    ) -> str:
        """Clean a long-form value (medical history, notes)."""
        limit = max_length if max_length is not None else self.settings.max_free_text_length
        cleaned = clean_text(value)
        if cleaned and len(cleaned) > limit:
            self._fail(
                field_name,
                f"{label_for(field_name)} must be {limit} characters or fewer.",
            )
        return cleaned

    def whole_number(
        self,
        field_name: str,
        value: Any,
        *,
        minimum: int,
        maximum: int,
        required: bool = False,
        suffix: str = "",
    ) -> str:
        """Validate an integer value, returning it as a normalised string."""
        cleaned = clean_text(value)
        label = label_for(field_name)

        if not cleaned:
            if required:
                self._fail(field_name, f"{label} is required.")
            return ""

        try:
            number = int(float(cleaned))
        except (TypeError, ValueError):
            self._fail(field_name, f"{label} must be a whole number.")
            return cleaned

        if not minimum <= number <= maximum:
            self._fail(
                field_name,
                f"{label} must be between {minimum} and {maximum}{suffix}.",
            )
        return str(number)

    def matches(
        self,
        field_name: str,
        value: Any,
        pattern: re.Pattern[str],
        *,
        expectation: str,
        required: bool = False,
    ) -> str:
        """Validate against a compiled pattern."""
        cleaned = clean_text(value)
        label = label_for(field_name)

        if not cleaned:
            if required:
                self._fail(field_name, f"{label} is required.")
            return ""

        if not pattern.match(cleaned):
            self._fail(field_name, f"{label} must be {expectation}.")
        return cleaned

    def email(self, field_name: str, value: Any) -> str:
        return self.matches(
            field_name,
            value,
            self._compiled_email,
            expectation="a valid email address",
        )

    def phone(self, field_name: str, value: Any) -> str:
        return self.matches(
            field_name,
            value,
            self._compiled_phone,
            expectation="a valid phone number",
        )

    def blood_pressure(self, field_name: str, value: Any) -> str:
        return self.matches(
            field_name,
            value,
            self._compiled_bp,
            expectation="in the form 120/80",
        )

    def heart_rate(self, field_name: str, value: Any) -> str:
        return self.matches(
            field_name,
            value,
            self._compiled_hr,
            expectation="a number of beats per minute",
        )

    def date_value(self, field_name: str, value: Any, *, not_after: str) -> str:
        """Validate an ISO ``YYYY-MM-DD`` date.

        A date of birth in the future is almost always a typo, and one that would
        make the patient implausibly old is worth catching before it reaches a
        clinical record. Both bounds come from the caller, not from this module.
        """
        cleaned = clean_text(value)
        label = label_for(field_name)

        if not cleaned:
            return ""

        try:
            parsed = date.fromisoformat(cleaned)
        except ValueError:
            self._fail(field_name, f"{label} must be a date in the form YYYY-MM-DD.")
            return cleaned

        try:
            ceiling = date.fromisoformat(not_after)
        except ValueError:  # pragma: no cover - guarded by configuration validation
            return cleaned

        if parsed > ceiling:
            self._fail(field_name, f"{label} cannot be in the future.")

        return parsed.isoformat()

    # ---------- error handling ----------

    def _fail(self, field_name: str, message: str) -> None:
        # Keep the first complaint per field; later ones are usually consequences.
        self.errors.setdefault(field_name, message)

    def raise_if_invalid(self) -> None:
        if self.errors:
            raise ValidationError(self.errors)


class PatientValidator:
    """Validates a whole patient submission against the configured rules."""

    def __init__(self, settings: ValidationSettings) -> None:
        self.settings = settings

    def validate(
        self,
        data: Mapping[str, Any],
        *,
        require_name: bool = True,
        today: str | None = None,
    ) -> dict[str, str]:
        """Validate a patient payload and return the cleaned values.

        ``require_name=False`` is used by partial updates, where a field being
        absent means "leave it alone" rather than "clear it".

        ``today`` bounds the date of birth. It defaults to the real current date so
        that a caller who does not care cannot get it wrong, and can be supplied
        explicitly to make the result reproducible in a test.
        """
        validator = FieldValidator(self.settings)
        ceiling = today or date.today().isoformat()

        cleaned = {
            "first_name": validator.text(
                "first_name", data.get("first_name"), required=require_name
            ),
            "last_name": validator.text("last_name", data.get("last_name")),
            "date_of_birth": validator.date_value(
                "date_of_birth", data.get("date_of_birth"), not_after=ceiling
            ),
            "age_years": validator.whole_number(
                "age_years",
                data.get("age_years"),
                minimum=self.settings.min_age,
                maximum=self.settings.max_age,
            ),
            "sex": validator.text("sex", data.get("sex")),
            "phone": validator.phone("phone", data.get("phone")),
            "email": validator.email("email", data.get("email")),
            "address": validator.free_text("address", data.get("address")),
            "blood_pressure": validator.blood_pressure(
                "blood_pressure", data.get("blood_pressure")
            ),
            "heart_rate": validator.heart_rate(
                "heart_rate", data.get("heart_rate")
            ),
            "weight": validator.text("weight", data.get("weight")),
            "height": validator.text("height", data.get("height")),
            "medical_history": validator.free_text(
                "medical_history", data.get("medical_history")
            ),
            "notes": validator.free_text("notes", data.get("notes")),
            "diagnosis": validator.free_text("diagnosis", data.get("diagnosis")),
        }

        validator.raise_if_invalid()
        return cleaned
