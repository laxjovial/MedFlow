"""Tests for configuration loading, validation and path resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config.constants import CONFIG_ENV_VAR
from app.config.settings import AppSettings
from app.core.exceptions import ConfigurationError


def write_config(directory: Path, payload: dict, name: str = "config.json") -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestDefaults:
    def test_runs_with_no_configuration_file_at_all(self, tmp_path):
        # The packaged executable must start with nothing but its own defaults.
        settings = AppSettings.load(base_directory=tmp_path)

        assert settings.config_path is None
        assert settings.storage.mode == "local"
        assert settings.patient_ids.prefix == "MF"
        assert settings.patient_ids.padding == 6

    def test_default_patient_number_format(self, tmp_path):
        settings = AppSettings.default(base_directory=tmp_path)

        assert f"{settings.patient_ids.prefix}-{1:0{settings.patient_ids.padding}d}" == "MF-000001"


class TestPathResolution:
    def test_relative_paths_resolve_against_the_base_directory(self, tmp_path):
        settings = AppSettings.default(base_directory=tmp_path)

        assert settings.database_path == tmp_path / "data" / "medflow.db"
        assert settings.backup_directory == tmp_path / "backups"

    def test_absolute_paths_are_honoured_as_written(self, tmp_path):
        target = tmp_path / "elsewhere"
        payload = {"database": {"directory": str(target), "filename": "custom.db"}}

        settings = AppSettings.from_dict(payload, base_directory=tmp_path)

        assert settings.database_path == target / "custom.db"

    def test_ensure_directories_creates_every_working_directory(self, tmp_path):
        settings = AppSettings.default(base_directory=tmp_path)

        settings.ensure_directories()

        assert settings.database_path.parent.is_dir()
        assert settings.backup_directory.is_dir()
        assert settings.export_directory.is_dir()
        assert settings.log_directory.is_dir()

    def test_ensure_directories_is_idempotent(self, tmp_path):
        settings = AppSettings.default(base_directory=tmp_path)

        settings.ensure_directories()
        settings.ensure_directories()

        assert settings.backup_directory.is_dir()


class TestLoading:
    def test_reads_values_from_the_file(self, tmp_path):
        write_config(
            tmp_path,
            {
                "patient_ids": {"prefix": "HOSP", "padding": 4},
                "appearance": {"mode": "Dark"},
            },
        )

        settings = AppSettings.load(base_directory=tmp_path)

        assert settings.patient_ids.prefix == "HOSP"
        assert settings.patient_ids.padding == 4
        assert settings.appearance.mode == "Dark"

    def test_records_where_it_was_loaded_from(self, tmp_path):
        path = write_config(tmp_path, {})

        settings = AppSettings.load(base_directory=tmp_path)

        assert settings.config_path == path

    def test_an_explicit_path_wins_over_the_default_location(self, tmp_path):
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        path = write_config(elsewhere, {"patient_ids": {"prefix": "EXP"}}, name="other.json")

        settings = AppSettings.load(path, base_directory=tmp_path)

        assert settings.patient_ids.prefix == "EXP"
        assert settings.config_path == path

    def test_environment_variable_selects_the_configuration_file(self, tmp_path, monkeypatch):
        elsewhere = tmp_path / "envpath"
        elsewhere.mkdir()
        path = write_config(elsewhere, {"patient_ids": {"prefix": "ENV"}}, name="env.json")
        monkeypatch.setenv(CONFIG_ENV_VAR, str(path))

        settings = AppSettings.load(base_directory=tmp_path)

        assert settings.patient_ids.prefix == "ENV"

    def test_malformed_json_names_the_problem(self, tmp_path):
        (tmp_path / "config.json").write_text("{ not json", encoding="utf-8")

        with pytest.raises(ConfigurationError) as excinfo:
            AppSettings.load(base_directory=tmp_path)

        assert "not valid JSON" in str(excinfo.value)


class TestRejection:
    def test_unknown_section_is_rejected(self, tmp_path):
        write_config(tmp_path, {"databse": {"filename": "typo.db"}})

        with pytest.raises(ConfigurationError) as excinfo:
            AppSettings.load(base_directory=tmp_path)

        assert "databse" in str(excinfo.value)

    def test_unknown_key_names_the_valid_ones(self, tmp_path):
        write_config(tmp_path, {"patient_ids": {"prefix": "MF", "pad": 6}})

        with pytest.raises(ConfigurationError) as excinfo:
            AppSettings.load(base_directory=tmp_path)

        message = str(excinfo.value)
        assert "pad" in message
        assert "prefix" in message  # the helpful part: what was actually valid

    def test_wrong_type_is_rejected(self, tmp_path):
        write_config(tmp_path, {"patient_ids": {"padding": "six"}})

        with pytest.raises(ConfigurationError) as excinfo:
            AppSettings.load(base_directory=tmp_path)

        assert "whole number" in str(excinfo.value)

    def test_invalid_appearance_mode_is_rejected(self, tmp_path):
        write_config(tmp_path, {"appearance": {"mode": "Neon"}})

        with pytest.raises(ConfigurationError) as excinfo:
            AppSettings.load(base_directory=tmp_path)

        assert "appearance.mode" in str(excinfo.value)

    def test_invalid_storage_mode_is_rejected(self, tmp_path):
        write_config(tmp_path, {"storage": {"mode": "sneakernet"}})

        with pytest.raises(ConfigurationError):
            AppSettings.load(base_directory=tmp_path)

    def test_network_mode_requires_a_server_url(self, tmp_path):
        write_config(tmp_path, {"storage": {"mode": "network"}})

        with pytest.raises(ConfigurationError) as excinfo:
            AppSettings.load(base_directory=tmp_path)

        assert "api_base_url" in str(excinfo.value)

    def test_network_mode_with_a_url_is_accepted(self, tmp_path):
        write_config(
            tmp_path,
            {"storage": {"mode": "network", "api_base_url": "https://api.example.com"}},
        )

        settings = AppSettings.load(base_directory=tmp_path)

        assert settings.storage.api_base_url == "https://api.example.com"

    def test_invalid_regex_pattern_is_rejected(self, tmp_path):
        write_config(tmp_path, {"validation": {"heart_rate_pattern": "["}})

        with pytest.raises(ConfigurationError) as excinfo:
            AppSettings.load(base_directory=tmp_path)

        assert "regular expression" in str(excinfo.value)

    def test_inverted_age_bounds_are_rejected(self, tmp_path):
        write_config(tmp_path, {"validation": {"min_age": 50, "max_age": 10}})

        with pytest.raises(ConfigurationError) as excinfo:
            AppSettings.load(base_directory=tmp_path)

        assert "min_age" in str(excinfo.value)

    def test_empty_patient_prefix_is_rejected(self, tmp_path):
        write_config(tmp_path, {"patient_ids": {"prefix": ""}})

        with pytest.raises(ConfigurationError) as excinfo:
            AppSettings.load(base_directory=tmp_path)

        assert "prefix" in str(excinfo.value)

    def test_zero_padding_is_rejected(self, tmp_path):
        write_config(tmp_path, {"patient_ids": {"padding": 0}})

        with pytest.raises(ConfigurationError) as excinfo:
            AppSettings.load(base_directory=tmp_path)

        assert "padding" in str(excinfo.value)


class TestCoercion:
    def test_numeric_strings_are_accepted_for_integer_fields(self, tmp_path):
        # The file is meant to be hand-edited, so "6" should not be fatal.
        write_config(tmp_path, {"patient_ids": {"padding": "6"}})

        settings = AppSettings.load(base_directory=tmp_path)

        assert settings.patient_ids.padding == 6

    def test_string_booleans_are_accepted(self, tmp_path):
        write_config(tmp_path, {"database": {"seed_demo_data": "false"}})

        settings = AppSettings.load(base_directory=tmp_path)

        assert settings.database.seed_demo_data is False

    def test_partial_sections_keep_their_defaults(self, tmp_path):
        write_config(tmp_path, {"appearance": {"mode": "Light"}})

        settings = AppSettings.load(base_directory=tmp_path)

        assert settings.appearance.mode == "Light"
        assert settings.appearance.color_theme == "blue"


class TestRoundTrip:
    def test_save_then_load_preserves_values(self, tmp_path):
        original = AppSettings.default(base_directory=tmp_path)
        original.appearance.mode = "Dark"
        original.patient_ids.prefix = "CLINIC"
        original.logging.level = "DEBUG"

        path = original.save()

        reloaded = AppSettings.load(path, base_directory=tmp_path)
        assert reloaded.appearance.mode == "Dark"
        assert reloaded.patient_ids.prefix == "CLINIC"
        assert reloaded.logging.level == "DEBUG"

    def test_saved_file_omits_runtime_only_fields(self, tmp_path):
        settings = AppSettings.default(base_directory=tmp_path)

        saved = json.loads(settings.save().read_text(encoding="utf-8"))

        assert "base_directory" not in saved
        assert "config_path" not in saved
        assert "appearance" in saved

    def test_saved_file_is_valid_configuration(self, tmp_path):
        AppSettings.default(base_directory=tmp_path).save()

        # Round-tripping the file we write must not trip the strict key checking.
        reloaded = AppSettings.load(base_directory=tmp_path)

        assert reloaded.patient_ids.prefix == "MF"
