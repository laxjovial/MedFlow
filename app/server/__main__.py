"""``python -m app.server`` — run the MedFlow web/API server.

Reads the same config.json as the desktop app, reuses the same SQLite
database, and mounts the built-in web client. No environment variables,
no external services: a clinic starts its web face with one command.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

from app.config import Config
from app.storage.engine import Database
from app.storage.repositories import build_repositories
from app.utils.logging_utils import get_logger, setup_logging

log = get_logger("server")


def resolve_data_dir(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    base = Path(__file__).resolve().parent.parent
    return base / "data"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.server",
        description="Run the MedFlow web + API server.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", default=None,
                        help="Directory holding medflow.db and config.json")
    parser.add_argument("--db", default=None,
                        help="Direct path to the SQLite database file")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)

    data_dir = resolve_data_dir(args.data_dir)
    config = Config.load(data_dir)

    db_path = Path(args.db) if args.db else config.resolve_database_path(
        data_dir.parent
    )
    setup_logging(config.resolve_log_dir(data_dir.parent))

    db = Database(db_path)
    repos = build_repositories(db)
    repos["units"].ensure_root(config.facility_name)

    from app.server.app import create_app
    from app.server.tokens import load_or_create_secret

    app = create_app(config=config, db=db, repos=repos)
    app.state.token_secret = load_or_create_secret(
        Path(config.resolve_data_dir(data_dir.parent)) / ".token_secret"
    )

    log.info("MedFlow server on http://%s:%d (db: %s)",
             args.host, args.port, db_path)
    uvicorn.run(app, host=args.host, port=args.port,
                log_level=args.log_level)
    return 0


if __name__ == "__main__":
    sys.exit(main())
