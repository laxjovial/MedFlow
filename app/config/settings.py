"""JSON-backed application settings.

MedFlow hardcodes nothing that a deployment might reasonably want to change:
where the database lives, how patient numbers are formatted, the appearance mode,
validation bounds, log level and storage mode all resolve from here.

The configuration file is optional. Every field has a default, so a freshly
downloaded copy of MedFlow runs with no configuration at all — which is what
makes the packaged executable double-click-and-go.

Resolution order:

1. an explicit path passed to :meth:`AppSettings.load`
2. the path in the ``MEDFLOW_CONFIG`` environment variable
3. ``config.json`` beside the application
4. built-in defaults
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, get_type_hints

from app.config.constants import (
    APPEARANCE_MODES,
    BACKUP_DIRNAME,
    CONFIG_ENV_VAR,
    CONFIG_FILENAME,
    DATA_DIRNAME,
    DATABASE_FILENAME,
    EXPORT_DIRNAME,
    LOG_DIRNAME,
    STORAGE_MODE_LOCAL,
    STORAGE_MODE_NETWORK,
)
from app.core.exceptions import ConfigurationError

_VALID_STORAGE_MODES = (STORAGE_MODE_LOCAL, STORAGE_MODE_NETWORK)


def default_base_directory() -> Path:
    """The directory MedFlow treats as its working root.

    Currently the repository root (the parent of ``app/``). Packaging will pass
    an explicit base directory instead, since an installed executable cannot
    write beside its own directory on every platform.
    """
    return Path(__file__).resolve().parents[2]


@dataclass
class DatabaseSettings:
    """Where the local database lives and whether to seed demo content."""

    directory: str = DATA_DIRNAME
    filename: str = DATABASE_FILENAME
    seed_demo_data: bool = True


@dataclass
class DirectorySettings:
    """Where generated files are written. All resolved against the base directory."""

    backups: str = BACKUP_DIRNAME
    exports: str = EXPORT_DIRNAME
    logs: str = LOG_DIRNAME


@dataclass
class PatientIdSettings:
    """Patient number format, e.g. prefix ``MF`` with padding ``6`` gives ``MF-000001``."""

    prefix: str = "MF"
    padding: int = 6


@dataclass
class AppearanceSettings:
    """Window and theme preferences, persisted between runs."""

    mode: str = "System"
    color_theme: str = "blue"
    window_width: int = 1240
    window_height: int = 780
    min_window_width: int = 1000
    min_window_height: int = 660


@dataclass
class ValidationSettings:
    """Bounds used by the validators. Changing these changes what the app accepts."""

    min_age: int = 0
    max_age: int = 130
    max_name_length: int = 80
    max_short_field_length: int = 40
    max_free_text_length: int = 5000
    blood_pressure_pattern: str = r"^\d{2,3}\s*/\s*\d{2,3}$"
    heart_rate_pattern: str = r"^\d{1,3}$"


@dataclass
class LoggingSettings:
    """Application log configuration. Distinct from the database audit trail."""

    level: str = "INFO"
    to_console: bool = True
    max_bytes: int = 1_000_000
    backup_count: int = 5


@dataclass
class StorageSettings:
    """Storage mode.

    ``network`` is reserved for the API phase and is not yet implemented; the
    setting exists so a configuration file can express intent before the code
    that honours it lands.
    """

    mode: str = STORAGE_MODE_LOCAL
    api_base_url: str = ""
    api_timeout_seconds: int = 15


@dataclass
class AppSettings:
    """The complete configuration for one MedFlow installation."""

    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    directories: DirectorySettings = field(default_factory=DirectorySettings)
    patient_ids: PatientIdSettings = field(default_factory=PatientIdSettings)
    appearance: AppearanceSettings = field(default_factory=AppearanceSettings)
    validation: ValidationSettings = field(default_factory=ValidationSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    storage: StorageSettings = field(default_factory=StorageSettings)

    #: Runtime context, never written to disk.
    base_directory: Path = field(default_factory=default_base_directory, repr=False)
    config_path: Path | None = field(default=None, repr=False)

    # ---------- path resolution ----------

    def resolve(self, value: str | Path) -> Path:
        """Resolve a configured path. Absolute paths are honoured as written."""
        candidate = Path(value).expanduser()
        if candidate.is_absolute():
            return candidate
        return (self.base_directory / candidate).resolve()

    @property
    def database_path(self) -> Path:
        return self.resolve(self.database.directory) / self.database.filename

    @property
    def backup_directory(self) -> Path:
        return self.resolve(self.directories.backups)

    @property
    def export_directory(self) -> Path:
        return self.resolve(self.directories.exports)

    @property
    def log_directory(self) -> Path:
        return self.resolve(self.directories.logs)

    def ensure_directories(self) -> None:
        """Create the directories MedFlow writes to. Safe to call repeatedly."""
        for directory in (
            self.database_path.parent,
            self.backup_directory,
            self.export_directory,
            self.log_directory,
        ):
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise ConfigurationError(
                    f"Could not create directory '{directory}': {exc}"
                ) from exc

    # ---------- validation ----------

    def validate(self) -> None:
        """Check loaded values. Raises :class:`ConfigurationError` on the first problem."""
        if self.appearance.mode not in APPEARANCE_MODES:
            raise ConfigurationError(
                f"appearance.mode must be one of {', '.join(APPEARANCE_MODES)}; "
                f"got {self.appearance.mode!r}"
            )
        if self.patient_ids.padding < 1:
            raise ConfigurationError("patient_ids.padding must be at least 1")
        if not self.patient_ids.prefix:
            raise ConfigurationError("patient_ids.prefix must not be empty")
        if self.storage.mode not in _VALID_STORAGE_MODES:
            raise ConfigurationError(
                f"storage.mode must be one of {', '.join(_VALID_STORAGE_MODES)}; "
                f"got {self.storage.mode!r}"
            )
        if self.storage.mode == STORAGE_MODE_NETWORK and not self.storage.api_base_url:
            raise ConfigurationError(
                "storage.api_base_url is required when storage.mode is 'network'"
            )
        if self.validation.min_age > self.validation.max_age:
            raise ConfigurationError("validation.min_age must not exceed max_age")
        for label, pattern in (
            ("blood_pressure_pattern", self.validation.blood_pressure_pattern),
            ("heart_rate_pattern", self.validation.heart_rate_pattern),
        ):
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ConfigurationError(
                    f"validation.{label} is not a valid regular expression: {exc}"
                ) from exc

    # ---------- serialisation ----------

    def _section_names(self) -> list[str]:
        return [
            spec.name
            for spec in fields(self)
            if spec.name not in {"base_directory", "config_path"}
        ]

    def to_dict(self) -> dict[str, Any]:
        """The persistable form, ready for JSON."""
        return {name: asdict(getattr(self, name)) for name in self._section_names()}

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        base_directory: Path | None = None,
        config_path: Path | None = None,
    ) -> AppSettings:
        """Build settings from parsed JSON, rejecting unknown keys.

        Unknown keys are an error rather than silently ignored: a mistyped
        setting that quietly does nothing is worse than a startup message naming
        it.
        """
        if not isinstance(data, dict):
            raise ConfigurationError("Configuration root must be a JSON object")

        known = {spec.name for spec in fields(cls) if spec.name not in {"base_directory", "config_path"}}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ConfigurationError(
                f"Unknown configuration section(s): {', '.join(unknown)}. "
                f"Valid sections are: {', '.join(sorted(known))}"
            )

        kwargs: dict[str, Any] = {}
        for name in known:
            section_class = _resolve_section_class(name)
            kwargs[name] = _build_section(section_class, data.get(name, {}), section_name=name)

        settings = cls(**kwargs)
        if base_directory is not None:
            settings.base_directory = Path(base_directory).expanduser().resolve()
        settings.config_path = config_path
        settings.validate()
        return settings

    @classmethod
    def default(cls, *, base_directory: Path | None = None) -> AppSettings:
        """Built-in defaults, with no file involved."""
        settings = cls()
        if base_directory is not None:
            settings.base_directory = Path(base_directory).expanduser().resolve()
        settings.validate()
        return settings

    @classmethod
    def load(
        cls,
        path: str | Path | None = None,
        *,
        base_directory: Path | None = None,
    ) -> AppSettings:
        """Load settings, falling back to defaults when no file exists."""
        base = Path(base_directory).expanduser().resolve() if base_directory else default_base_directory()

        if path is not None:
            config_path: Path | None = Path(path).expanduser()
        else:
            env_path = os.environ.get(CONFIG_ENV_VAR)
            config_path = Path(env_path).expanduser() if env_path else base / CONFIG_FILENAME

        if config_path is None or not config_path.exists():
            return cls.default(base_directory=base)

        try:
            raw = config_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigurationError(f"Could not read configuration file '{config_path}': {exc}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(
                f"Configuration file '{config_path}' is not valid JSON "
                f"(line {exc.lineno}, column {exc.colno}): {exc.msg}"
            ) from exc

        return cls.from_dict(data, base_directory=base, config_path=config_path)

    def save(self, path: str | Path | None = None) -> Path:
        """Write the settings to disk and return the path written."""
        target = Path(path) if path is not None else self.config_path
        if target is None:
            target = self.base_directory / CONFIG_FILENAME

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(self.to_dict(), indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise ConfigurationError(f"Could not write configuration file '{target}': {exc}") from exc

        self.config_path = target
        return target


# Section classes are looked up by name so from_dict stays readable and does not
# need updating when a section is added.
_SECTION_CLASSES: dict[str, type] = {
    "database": DatabaseSettings,
    "directories": DirectorySettings,
    "patient_ids": PatientIdSettings,
    "appearance": AppearanceSettings,
    "validation": ValidationSettings,
    "logging": LoggingSettings,
    "storage": StorageSettings,
}

# Annotations are strings because of `from __future__ import annotations`; resolve
# them once so section classes can be read directly off the dataclass fields.
# (Kept separate from _SECTION_CLASSES so introspection still works if a section
# is renamed before this map is updated.)
def _resolve_section_class(name: str) -> type:
    try:
        return _SECTION_CLASSES[name]
    except KeyError as exc:  # pragma: no cover - guarded by the unknown-key check
        raise ConfigurationError(f"No settings section registered for '{name}'") from exc


def _build_section(section_class: type, data: Any, *, section_name: str) -> Any:
    """Build one settings section from a JSON object, coercing and checking types."""
    if not isinstance(data, dict):
        raise ConfigurationError(f"Configuration section '{section_name}' must be a JSON object")

    specs = {spec.name: spec for spec in fields(section_class)}
    unknown = sorted(set(data) - set(specs))
    if unknown:
        raise ConfigurationError(
            f"Unknown key(s) in '{section_name}': {', '.join(unknown)}. "
            f"Valid keys are: {', '.join(sorted(specs))}"
        )

    hints = get_type_hints(section_class)
    values: dict[str, Any] = {}
    for name, value in data.items():
        values[name] = _coerce(value, hints.get(name, str), section_name, name)

    return section_class(**values)


def _coerce(value: Any, annotation: Any, section: str, key: str) -> Any:
    """Coerce a JSON value to the annotated type, or explain why it cannot be.

    JSON gives strings, numbers, booleans and nulls. A user hand-editing
    ``config.json`` may write ``"6"`` where ``6`` is meant, so numeric strings are
    accepted for int fields rather than crashing at startup.
    """
    if annotation is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
            return value.strip().lower() == "true"
        raise ConfigurationError(f"{section}.{key} must be true or false; got {value!r}")

    if annotation is int:
        if isinstance(value, bool):
            raise ConfigurationError(f"{section}.{key} must be a whole number; got {value!r}")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value.strip())
        raise ConfigurationError(f"{section}.{key} must be a whole number; got {value!r}")

    if annotation is str:
        if isinstance(value, str):
            return value
        raise ConfigurationError(f"{section}.{key} must be text; got {value!r}")

    return value
