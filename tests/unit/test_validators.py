"""Tests for field validation and normalisation."""

from __future__ import annotations

import pytest

from app.config.settings import ValidationSettings
from app.core.exceptions import ValidationError
from app.core.validators import PatientValidator, clean_text, is_blank


class TestCleanText:
    def test_strips_surrounding_whitespace(self):
        assert clean_text("  Victor  ") == "Victor"

    def test_collapses_accidental_spacing(self):
        assert clean_text("Victor    Kamau") == "Victor Kamau"

    def test_preserves_deliberate_line_breaks(self):
        # Medical history is multi-line; collapsing newlines would destroy meaning.
        assert clean_text("Line one\nLine two") == "Line one\nLine two"

    def test_normalises_windows_line_endings(self):
        assert clean_text("Line one\r\nLine two") == "Line one\nLine two"

    def test_none_becomes_empty(self):
        assert clean_text(None) == ""


class TestPlaceholders:
    @pytest.mark.parametrize("value", ["", "  ", "-", "--", "none", "N/A", "unknown"])
    def test_placeholder_values_are_blank(self, value):
        assert is_blank(value) is True

    def test_real_value_is_not_blank(self):
        assert is_blank("Penicillin allergy") is False

    def test_dashes_from_the_previous_version_normalise_to_empty(self):
        # The pre-refactor app wrote "--" into unrecorded numeric fields.
        assert clean_text("--") == ""


class TestPatientValidator:
    def test_accepts_a_valid_payload(self, validation_settings, sample_patient_data):
        cleaned = PatientValidator(validation_settings).validate(sample_patient_data)

        assert cleaned["first_name"] == "Victor"
        assert cleaned["age_years"] == "29"
        assert cleaned["blood_pressure"] == "118/75"
        assert cleaned["diagnosis"] == "Acute Appendicitis"

    def test_requires_a_first_name(self, validation_settings):
        with pytest.raises(ValidationError) as excinfo:
            PatientValidator(validation_settings).validate({"first_name": ""})

        assert "first_name" in excinfo.value.errors
        assert "required" in excinfo.value.errors["first_name"].lower()

    def test_missing_name_is_tolerated_for_partial_updates(self, validation_settings):
        cleaned = PatientValidator(validation_settings).validate(
            {"age_years": "30"}, require_name=False
        )

        assert cleaned["first_name"] == ""
        assert cleaned["age_years"] == "30"

    @pytest.mark.parametrize("age", ["abc", "twelve", "29.5.3"])
    def test_rejects_non_numeric_age(self, validation_settings, age):
        with pytest.raises(ValidationError) as excinfo:
            PatientValidator(validation_settings).validate({"first_name": "A", "age_years": age})

        assert "age_years" in excinfo.value.errors

    def test_rejects_age_beyond_the_configured_maximum(self, validation_settings):
        with pytest.raises(ValidationError) as excinfo:
            PatientValidator(validation_settings).validate(
                {"first_name": "A", "age_years": "131"}
            )

        assert "between 0 and 130" in excinfo.value.errors["age_years"]

    def test_honours_a_widened_age_bound(self, sample_patient_data):
        # Bounds are configuration, not literals: widening them must work.
        settings = ValidationSettings(min_age=0, max_age=200)
        sample_patient_data["age_years"] = "180"

        cleaned = PatientValidator(settings).validate(sample_patient_data)

        assert cleaned["age_years"] == "180"

    @pytest.mark.parametrize("value", ["118/75", "120/80", "90/60"])
    def test_accepts_valid_blood_pressure(self, validation_settings, value):
        cleaned = PatientValidator(validation_settings).validate(
            {"first_name": "A", "blood_pressure": value}
        )

        assert cleaned["blood_pressure"] == value

    def test_tolerates_spacing_around_the_blood_pressure_slash(self, validation_settings):
        cleaned = PatientValidator(validation_settings).validate(
            {"first_name": "A", "blood_pressure": "118 / 75"}
        )

        assert cleaned["blood_pressure"] == "118 / 75"

    @pytest.mark.parametrize("value", ["high", "118", "118/", "/75"])
    def test_rejects_malformed_blood_pressure(self, validation_settings, value):
        with pytest.raises(ValidationError) as excinfo:
            PatientValidator(validation_settings).validate(
                {"first_name": "A", "blood_pressure": value}
            )

        assert "blood_pressure" in excinfo.value.errors

    @pytest.mark.parametrize("value", ["72", "90", "120"])
    def test_accepts_valid_heart_rate(self, validation_settings, value):
        cleaned = PatientValidator(validation_settings).validate(
            {"first_name": "A", "heart_rate": value}
        )

        assert cleaned["heart_rate"] == value

    def test_rejects_non_numeric_heart_rate(self, validation_settings):
        with pytest.raises(ValidationError) as excinfo:
            PatientValidator(validation_settings).validate(
                {"first_name": "A", "heart_rate": "fast"}
            )

        assert "heart_rate" in excinfo.value.errors

    def test_rejects_malformed_email(self, validation_settings):
        with pytest.raises(ValidationError) as excinfo:
            PatientValidator(validation_settings).validate(
                {"first_name": "A", "email": "not-an-email"}
            )

        assert "email" in excinfo.value.errors

    def test_rejects_malformed_phone(self, validation_settings):
        with pytest.raises(ValidationError) as excinfo:
            PatientValidator(validation_settings).validate(
                {"first_name": "A", "phone": "call me"}
            )

        assert "phone" in excinfo.value.errors

    def test_reports_every_offending_field_at_once(self, validation_settings):
        # Fail-fast would force the user to resubmit once per problem.
        with pytest.raises(ValidationError) as excinfo:
            PatientValidator(validation_settings).validate(
                {"first_name": "", "age_years": "abc", "email": "nope"}
            )

        assert set(excinfo.value.fields) >= {"first_name", "age_years", "email"}
        assert len(excinfo.value.errors) >= 3

    def test_rejects_medical_history_over_the_length_limit(self, validation_settings):
        too_long = "x" * (validation_settings.max_free_text_length + 1)

        with pytest.raises(ValidationError) as excinfo:
            PatientValidator(validation_settings).validate(
                {"first_name": "A", "medical_history": too_long}
            )

        assert "medical_history" in excinfo.value.errors

    def test_optional_fields_may_be_omitted_entirely(self, validation_settings):
        cleaned = PatientValidator(validation_settings).validate({"first_name": "Solo"})

        assert cleaned["first_name"] == "Solo"
        assert cleaned["email"] == ""
        assert cleaned["blood_pressure"] == ""

    def test_error_summary_is_human_readable(self, validation_settings):
        with pytest.raises(ValidationError) as excinfo:
            PatientValidator(validation_settings).validate({"first_name": ""})

        assert "First name is required" in excinfo.value.summary()
