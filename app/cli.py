"""MedFlow command-line interface.

Power-user and automation entry points that skip the UI entirely:

    python -m app.cli init --admin-user admin --admin-password secret
    python -m app.cli serve --port 8000
    python -m app.cli backup
    python -m app.cli stats
    python -m app.cli export patients --out directory.csv
    python -m app.cli import-patients roster.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from app.utils.logging_utils import get_logger

log = get_logger("cli")


def _connect(data_dir: Path, db_path: str | None):
    from app.config import Config
    from app.storage.engine import Database
    from app.storage.repositories import build_repositories

    config = Config.load(data_dir)
    path = Path(db_path) if db_path else config.resolve_database_path(data_dir.parent)
    db = Database(path)
    return config, db, build_repositories(db)


def default_data_dir() -> Path:
    directory = Path(__file__).resolve().parent.parent / "data"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


# --------------------------------------------------------------------------- #
# commands


def cmd_init(args) -> int:
    from app.services.security import SecurityService

    config, db, repos = _connect(Path(args.data_dir), args.db)
    repos["units"].ensure_root(config.facility_name)
    security = SecurityService(repos["users"])
    if repos["users"].get_by_username(args.admin_user):
        print(f"User '{args.admin_user}' already exists — nothing to do.")
        return 0
    user = security.create_user(args.admin_user, args.admin_name or args.admin_user,
                                args.admin_password, "administrator")
    print(f"Created administrator '{user.username}' (user #{user.user_id}).")
    print("Database:", db.db_path)
    return 0


def cmd_serve(args) -> int:
    from app.server.__main__ import main as server_main
    return server_main(["--host", args.host, "--port", str(args.port),
                        "--data-dir", args.data_dir]
                       + (["--db", args.db] if args.db else []))


def cmd_backup(args) -> int:
    from app.services.backup import BackupService

    config, db, repos = _connect(Path(args.data_dir), args.db)
    service = BackupService(db.db_path, config.resolve_backup_dir(Path(args.data_dir).parent))
    path = service.create_backup(label=args.label or "cli")
    removed = service.prune()
    print(f"Backup written: {path}")
    if removed:
        print(f"Pruned {removed} old snapshot(s).")
    return 0


def cmd_restore(args) -> int:
    from app.services.backup import BackupService

    config, db, repos = _connect(Path(args.data_dir), args.db)
    service = BackupService(db.db_path, config.resolve_backup_dir(Path(args.data_dir).parent))
    if not service.verify(args.file):
        print("That file is not a valid SQLite backup — aborting.", file=sys.stderr)
        return 1
    db.close()
    service.restore_backup(args.file)
    print(f"Restored database from {args.file}")
    return 0


def cmd_stats(args) -> int:
    from app.services.reports import ReportsService

    config, db, repos = _connect(Path(args.data_dir), args.db)
    dashboard = ReportsService(repos).dashboard()
    for key, value in dashboard.items():
        print(f"{key:>22}: {value}")
    return 0


def cmd_export(args) -> int:
    from app.services.export import ExportService
    from app.services.reports import ReportsService

    config, db, repos = _connect(Path(args.data_dir), args.db)
    reports = ReportsService(repos)
    exporter = ExportService(reports)
    out = Path(args.out) if args.out else Path(f"medflow_{args.dataset}.{args.fmt}")
    content = (exporter.dataset_csv(args.dataset) if args.fmt == "csv"
               else exporter.dataset_json(args.dataset))
    saved = exporter.save(content, out.parent, out.name)
    print(f"Exported {args.dataset} to {saved}")
    return 0


def cmd_import_patients(args) -> int:
    from app.services.patients import PatientService

    config, db, repos = _connect(Path(args.data_dir), args.db)
    service = PatientService(repos, actor=args.actor or "import")

    created, failed = 0, []
    with open(args.file, newline="", encoding="utf-8") as handle:
        for index, row in enumerate(csv.DictReader(handle), start=2):
            payload = {k: (v or "").strip() for k, v in row.items()}
            try:
                service.register(payload)
                created += 1
            except Exception as exc:
                failed.append((index, payload.get("name", "?"), str(exc)))
    print(f"Imported {created} patient(s).")
    for line, name, error in failed:
        print(f"  row {line} ({name}): {error}", file=sys.stderr)
    return 1 if failed and not created else 0


# --------------------------------------------------------------------------- #
# parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="MedFlow command-line tools.",
    )
    parser.add_argument("--data-dir", default=None,
                        help="MedFlow data directory (default: ./data)")
    parser.add_argument("--db", default=None, help="SQLite database path override")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create the database and an administrator")
    init.add_argument("--admin-user", default="admin")
    init.add_argument("--admin-name", default=None)
    init.add_argument("--admin-password", required=True)
    init.set_defaults(func=cmd_init)

    serve = sub.add_parser("serve", help="run the web + API server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=cmd_serve)

    backup = sub.add_parser("backup", help="write a database snapshot")
    backup.add_argument("--label", default=None)
    backup.set_defaults(func=cmd_backup)

    restore = sub.add_parser("restore", help="restore a snapshot (replaces live db)")
    restore.add_argument("file")
    restore.set_defaults(func=cmd_restore)

    sub.add_parser("stats", help="print dashboard statistics").set_defaults(func=cmd_stats)

    export = sub.add_parser("export", help="export a report dataset")
    export.add_argument("dataset",
                        choices=["patients", "appointments", "diagnoses",
                                 "medications", "audit"])
    export.add_argument("--fmt", choices=["csv", "json"], default="csv")
    export.add_argument("--out", default=None)
    export.set_defaults(func=cmd_export)

    imp = sub.add_parser("import-patients",
                         help="bulk-register patients from a CSV with a header row")
    imp.add_argument("file")
    imp.add_argument("--actor", default=None,
                     help="audit actor name (default: 'import')")
    imp.set_defaults(func=cmd_import_patients)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not getattr(args, "data_dir", None):
        args.data_dir = str(default_data_dir())
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
