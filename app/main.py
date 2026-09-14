"""Application entry point.

Startup runs in a fixed order, and the order matters:

1. **Configuration** — everything downstream needs to know where the database,
   logs and exports live. A configuration error stops here, with a message naming
   the file and the key at fault.
2. **Logging** — configured before anything can fail, so a failure is recorded.
3. **Composition** — the object graph is built once, in one place.
4. **Migration** — the database is brought up to the current schema before any
   service reads from it. A migration failure stops startup rather than letting the
   application run against a schema it does not understand.
5. **Seeding** — optional demo data, and only into an empty database.
6. **Interface** — the window is built last, so it never exists against a database
   that is not ready.

A failure in any step is reported to the user rather than only to the log: a
desktop application that exits silently is indistinguishable from one that was
never started.
"""

from __future__ import annotations

import sys

from app.config.constants import APP_NAME, SYSTEM_ACTOR
from app.config.settings import AppSettings
from app.container import Container
from app.core.exceptions import MedFlowError
from app.core.logging import configure_logging, get_logger
from app.repositories.sqlite.migrations import MigrationRunner
from app.services.seed import seed

logger = get_logger(__name__)


def bootstrap() -> Container:
    """Load configuration, prepare the database and assemble the services.

    Separate from :func:`main` so the whole preparation can be exercised without
    opening a window.
    """
    settings = AppSettings.load()
    settings.ensure_directories()

    configure_logging(
        level=settings.logging.level,
        log_directory=settings.log_directory,
        to_console=settings.logging.to_console,
        max_bytes=settings.logging.max_bytes,
        backup_count=settings.logging.backup_count,
    )

    logger.info("%s starting", APP_NAME)
    logger.info("Database: %s", settings.database_path)
    logger.info("Storage mode: %s", settings.storage.mode)

    container = Container.build(settings)

    runner = MigrationRunner(
        container.database,
        clock=container.clock,
        patient_ids=settings.patient_ids,
        actor=SYSTEM_ACTOR,
    )

    if not runner.is_up_to_date():
        pending = [migration.version for migration in runner.pending()]
        logger.info("Applying database migration(s): %s", pending)
        runner.migrate()

    if settings.database.seed_demo_data:
        created = seed(container.patients, actor=SYSTEM_ACTOR)
        if created:
            logger.info("Seeded %d demo patient(s)", created)

    return container


def main(argv: list[str] | None = None) -> int:
    """Start MedFlow. Returns a process exit code."""
    del argv  # no command-line arguments yet; kept so the signature can grow

    try:
        container = bootstrap()
    except MedFlowError as error:
        _report_startup_failure(error.message)
        return 1
    except Exception as error:  # noqa: BLE001 - startup must never crash silently
        logger.exception("Unexpected failure during startup")
        _report_startup_failure(f"An unexpected error occurred:\n{error}")
        return 1

    # Imported here rather than at module level: importing the interface pulls in
    # CustomTkinter, and a configuration or migration failure should be reportable
    # without a GUI toolkit loaded.
    from app.ui.app import build_application

    try:
        application = build_application(container, actor=SYSTEM_ACTOR)
        application.mainloop()
    except Exception:  # noqa: BLE001
        logger.exception("The interface stopped unexpectedly")
        return 1
    finally:
        container.close()
        logger.info("%s stopped", APP_NAME)

    return 0


def _report_startup_failure(message: str) -> None:
    """Tell the user what went wrong, by the most reliable means available."""
    logger.error("Startup failed: %s", message)

    print(f"\n{APP_NAME} could not start.\n\n{message}\n", file=sys.stderr)

    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror(f"{APP_NAME} could not start", message)
        root.destroy()
    except Exception:  # noqa: BLE001
        # No display, or no Tk at all. The message has already gone to stderr and
        # the log, which is the best that can be done in that situation.
        pass


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
