"""MedFlow launcher.

    python main.py              # desktop app (CustomTkinter UI + local SQLite)
    python main.py --server     # web + API server on the same database

Both faces share one service layer and one data directory; see README.md
for the full story.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent


def data_dir() -> Path:
    directory = APP_ROOT / "data"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def run_desktop(argv: list[str]) -> int:
    from app.controller import AppController, LoginCancelled
    from app.utils.logging_utils import setup_logging

    controller = AppController(data_dir(), db_path=Path(argv.db) if argv.db else None)
    setup_logging(controller.config.resolve_log_dir(APP_ROOT))
    try:
        controller.login()
    except LoginCancelled:
        return 0
    controller.run()
    return 0


def run_server(argv: list[str]) -> int:
    from app.server.__main__ import main as server_main
    server_args = ["--host", argv.host, "--port", str(argv.port),
                   "--data-dir", str(data_dir())]
    if argv.db:
        server_args += ["--db", argv.db]
    return server_main(server_args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="MedFlow",
        description="Local-first clinic management platform.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--server", action="store_true",
                      help="run the web + API server instead of the desktop UI")
    parser.add_argument("--host", default="127.0.0.1",
                        help="server bind address (with --server)")
    parser.add_argument("--port", type=int, default=8000,
                        help="server port (with --server)")
    parser.add_argument("--db", default=None,
                        help="path to a specific SQLite database file")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.server:
        return run_server(args)
    return run_desktop(args)


if __name__ == "__main__":
    sys.exit(main())
