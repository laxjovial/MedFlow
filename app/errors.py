"""Structured exception hierarchy.

The UI never inspects raw traceback strings. Services raise these typed
errors and every view renders them consistently.
"""


class MedFlowError(Exception):
    """Base class for every application-level error."""

    title = "MedFlow error"

    def __init__(self, message: str = ""):
        self.message = message or self.__doc__ or "Unexpected error."
        super().__init__(self.message)


class ValidationError(MedFlowError):
    """One or more fields failed validation.

    Carries a ``errors`` mapping of ``field -> [messages]`` so forms can
    highlight the exact widgets that need attention.
    """

    title = "Validation failed"

    def __init__(self, errors):
        if isinstance(errors, str):
            errors = {"_form": [errors]}
        self.errors = dict(errors)
        summary = "; ".join(
            f"{field}: {', '.join(msgs)}" for field, msgs in self.errors.items()
        )
        super().__init__(summary)


class NotFoundError(MedFlowError):
    """The requested entity does not exist."""

    title = "Not found"


class DuplicatePatientError(MedFlowError):
    """A patient with the same unique identity already exists."""

    title = "Duplicate patient"


class RepositoryError(MedFlowError):
    """A storage-layer failure (database or remote API)."""

    title = "Storage error"


class NetworkError(MedFlowError):
    """The remote MedFlow server could not be reached."""

    title = "Network error"


class AuthenticationError(MedFlowError):
    """Credentials were rejected by the remote server."""

    title = "Authentication error"


class AuthorizationError(MedFlowError):
    """The authenticated user lacks permission for this operation."""

    title = "Permission denied"


class SyncConflictError(MedFlowError):
    """A synchronization conflict requires human resolution."""

    title = "Sync conflict"


class AutomationError(MedFlowError):
    """An automation rule failed to compile or execute."""

    title = "Automation error"


class ExchangeError(MedFlowError):
    """An inter-facility record transfer failed validation or transfer."""

    title = "Record exchange error"
