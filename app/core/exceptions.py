"""MedFlow's exception hierarchy.

The application raises these instead of bare ``Exception`` so callers can decide
how to react — a view can render a :class:`ValidationError` inline while a
:class:`PersistenceError` warrants a dialog — rather than catching everything
and showing a generic message.

Nothing here is storage-specific: the same exceptions are raised whether the
active repository is SQLite or, later, a network client.
"""

from __future__ import annotations

from typing import Mapping

#: Key used by ValidationError for errors that belong to no single field.
FORM_LEVEL = "__all__"


class MedFlowError(Exception):
    """Base class for every error MedFlow raises deliberately."""

    def __init__(self, message: str = "") -> None:
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return self.message


class ConfigurationError(MedFlowError):
    """The configuration file is missing, malformed, or holds invalid values."""


class ValidationError(MedFlowError):
    """One or more fields failed validation.

    Carries a ``field -> message`` mapping so a form can highlight the offending
    inputs rather than showing the whole message in one dialog. Field keys match
    the keys used by the UI form and by the service layer.
    """

    def __init__(
        self,
        errors: Mapping[str, str] | str,
        message: str = "The submitted data is not valid",
    ) -> None:
        if isinstance(errors, str):
            errors = {FORM_LEVEL: errors}
        self.errors: dict[str, str] = dict(errors)
        super().__init__(message)

    @property
    def fields(self) -> list[str]:
        """Names of the fields that failed, excluding form-level errors."""
        return [name for name in self.errors if name != FORM_LEVEL]

    def summary(self) -> str:
        """A single human-readable line, for use in a dialog title or log entry."""
        parts = [f"{name}: {text}" for name, text in self.errors.items() if name != FORM_LEVEL]
        form_level = self.errors.get(FORM_LEVEL)
        if form_level:
            parts.insert(0, form_level)
        return "; ".join(parts) if parts else self.message

    def __str__(self) -> str:
        return self.summary()


class NotFoundError(MedFlowError):
    """A requested record does not exist (or has been deleted)."""


class DuplicateError(MedFlowError):
    """A record would violate a uniqueness constraint."""


class PersistenceError(MedFlowError):
    """Storage failed — a query error, a locked database, a constraint violation."""


class MigrationError(MedFlowError):
    """A schema migration could not be applied, or the database is from a newer version."""


class DataTransferError(MedFlowError):
    """Base class for import, export and backup failures."""


class ExportError(DataTransferError):
    """Writing an export file failed."""


class DataImportError(DataTransferError):
    """Reading or parsing an import file failed.

    Named ``DataImportError`` rather than ``ImportError`` to avoid shadowing the
    builtin, which would break ``import`` statements inside bare ``except`` clauses.
    """


class BackupError(DataTransferError):
    """Creating or restoring a database backup failed."""
