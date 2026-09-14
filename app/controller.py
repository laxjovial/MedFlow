"""AppController: the desktop session's service wiring and callbacks.

The UI never touches repositories directly — it asks the controller, which
owns the services bound to the signed-in user, and exposes the small set of
cross-cutting helpers views need (toasts, confirms, exports, printing).
"""

from __future__ import annotations

import webbrowser
from pathlib import Path

from app.runtime_config import Config, STORAGE_LOCAL, STORAGE_NETWORK
from app.models.org import User
from app.services.automation import AutomationEngine
from app.services.backup import BackupService
from app.services.export import ExportService
from app.services.org import OrgService
from app.services.patients import PatientService
from app.services.records import RecordsService
from app.services.reports import ReportsService
from app.services.security import SecurityService, permissions_for
from app.storage.engine import Database
from app.storage.repositories import build_repositories
from app.ui.theme import apply_theme
from app.utils.dates import utcnow
from app.utils.logging_utils import get_logger, setup_logging

log = get_logger("controller")


class LoginCancelled(Exception):
    """The user closed the login dialog."""


class AppController:
    """One signed-in desktop session."""

    def __init__(self, data_dir: Path, db_path: Path | None = None):
        self.config = Config.load(data_dir)
        self.data_dir = Path(data_dir)
        self.db = Database(db_path or self.config.resolve_database_path(
            data_dir.parent))
        self.repos = build_repositories(self.db)
        self.repos["units"].ensure_root(self.config.facility_name)
        setup_logging(self.config.resolve_log_dir(data_dir.parent))

        self.backups = BackupService(
            self.db.db_path, self.config.resolve_backup_dir(data_dir.parent))
        self.security = SecurityService(self.repos["users"])

        self.user: User | None = None
        self._services: dict[str, object] = {}
        self._main_window = None
        self._sync_timer = None

    # ------------------------------------------------------------------ #
    # session

    @property
    def actor(self) -> str:
        return self.user.username if self.user else "system"

    @property
    def device_id(self) -> str:
        return self.config.device_id

    @property
    def permissions(self) -> set[str]:
        return permissions_for(self.user.role) if self.user else set()

    def _build_services(self) -> None:
        self.patients = PatientService(self.repos, actor=self.actor,
                                       device_id=self.device_id)
        self.records = RecordsService(self.repos, actor=self.actor,
                                      device_id=self.device_id)
        self.reports = ReportsService(self.repos)
        self.report_service = self.reports
        self.org = OrgService(self.repos, self.security, actor=self.actor,
                              device_id=self.device_id)
        self.audit = self.repos["audit"]
        self.automation = AutomationEngine(
            self.repos, backup_service=self.backups,
            log_sink=lambda msg: log.info(msg))
        self.exporter = ExportService(self.reports)

    # ------------------------------------------------------------------ #
    # login

    def login(self) -> None:
        """Run the login window loop until valid credentials or cancellation."""
        from app.ui.login import LoginDialog
        while self.user is None:
            dialog = LoginDialog(self)
            dialog.mainloop()
            try:
                dialog.destroy()
            except Exception:
                pass
            if self.user is None:
                raise LoginCancelled()

    def authenticate(self, username: str, password: str) -> User:
        user = self.security.authenticate(username, password)
        self.user = user
        self._build_services()
        self.repos["audit"].record(_audit_event(
            action="login", entity_type="session", entity_id=user.username,
            actor=user.username, device_id=self.device_id))
        self.repos["devices"].register(_device(
            self.device_id, unit_id=user.unit_id))
        return user

    # ------------------------------------------------------------------ #
    # main window plumbing

    def run(self) -> None:
        apply_theme(self.config.theme)
        from app.ui.main_window import MainWindow
        self._main_window = MainWindow(self)
        self._schedule_automation()
        self._main_window.mainloop()

    @property
    def view_registry(self) -> dict:
        from app.ui.views import (
            ActivityView, AppointmentsView, DashboardView, PatientsView,
            ReportsView, SettingsView,
        )
        return {
            "dashboard": DashboardView,
            "patients": PatientsView,
            "appointments": AppointmentsView,
            "reports": ReportsView,
            "activity": ActivityView,
            "settings": SettingsView,
        }

    def show_view(self, key: str, **kwargs) -> None:
        if self._main_window:
            if kwargs:
                view_cls = self.view_registry[key]
                self._main_window.show(key)
                self._main_window.current_view.destroy()
                self._main_window.current_view = view_cls(
                    self._main_window.container, self, **kwargs)
                self._main_window.current_view.pack(fill="both", expand=True)
            else:
                self._main_window.show(key)

    def today_label(self) -> str:
        return utcnow().strftime("%A, %d %B %Y")

    # ------------------------------------------------------------------ #
    # helpers used by views

    def toast(self, message: str, kind: str = "info") -> None:
        from app.ui.components import toast
        if self._main_window:
            toast(self._main_window, message, kind)

    def confirm(self, title: str, message: str) -> bool:
        from tkinter import messagebox
        return bool(messagebox.askyesno(title, message, parent=self._main_window))

    def pick_open_file(self, filetypes=None) -> str | None:
        from tkinter import filedialog
        return filedialog.askopenfilename(filetypes=filetypes or [],
                                          parent=self._main_window) or None

    def pick_save_file(self, default_name: str, filetypes=None) -> str | None:
        from tkinter import filedialog
        return filedialog.asksaveasfilename(
            initialfile=default_name, filetypes=filetypes or [],
            parent=self._main_window) or None

    def age_display(self, patient) -> str:
        return self.patients.age_display(patient)

    # ------------------------------------------------------------------ #
    # settings actions

    def set_theme(self, mode: str) -> None:
        self.config.theme = mode
        self.config.save(self.data_dir)
        from app.ui.theme import apply_theme
        apply_theme(mode)
        self.toast(f"Theme set to {mode}")

    def set_storage_mode(self, local: bool, api_base_url: str | None = None) -> None:
        if local:
            self.config.storage_mode = STORAGE_LOCAL
            self.config.api_base_url = None
        else:
            self.config.storage_mode = STORAGE_NETWORK
            self.config.api_base_url = api_base_url
        self.config.save(self.data_dir)
        self.toast("Storage mode updated", "ok")

    def create_backup(self) -> Path:
        return self.backups.create_backup(label="manual")

    def restore_backup(self, path: str) -> None:
        self.backups.restore_backup(path)
        self.db.close()

    # ------------------------------------------------------------------ #
    # export & print

    def export_dataset(self, name: str, fmt: str = "csv") -> None:
        path = self.pick_save_file(
            f"medflow_{name}.{fmt}",
            [("CSV", "*.csv") if fmt == "csv" else ("JSON", "*.json"),
             ("All files", "*.*")])
        if not path:
            return
        content = (self.exporter.dataset_csv(name) if fmt == "csv"
                   else self.exporter.dataset_json(name))
        saved = self.exporter.save(content, Path(path).parent, Path(path).name)
        self.toast(f"Exported: {saved}", "ok")

    def print_chart(self, patient_id: int) -> None:
        chart = self.patients.chart(patient_id)
        html = self.exporter.patient_chart_html(chart)
        out = self.config.resolve_export_dir(self.data_dir.parent)
        path = self.exporter.save(
            html, out, f"chart_{chart['patient'].patient_number}.html")
        webbrowser.open(path.as_uri())
        self.toast("Chart opened for printing", "ok")

    # ------------------------------------------------------------------ #
    # background automation

    def _schedule_automation(self) -> None:
        if not self.config.automation.enabled:
            return
        interval_ms = max(5, self.config.automation.interval_minutes) * 60_000

        def tick():
            try:
                self.automation.run_once()
            except Exception as exc:
                log.warning("automation tick failed: %s", exc)
            self._sync_timer = self._main_window.after(interval_ms, tick)

        if self.config.automation.run_on_startup:
            self._main_window.after(3_000, tick)
        else:
            self._sync_timer = self._main_window.after(interval_ms, tick)

    # ------------------------------------------------------------------ #
    # teardown

    def logout(self) -> None:
        if self._main_window:
            self._main_window.destroy()
        self.user = None
        self.db.close()

    def shutdown(self) -> None:
        if self._sync_timer and self._main_window:
            try:
                self._main_window.after_cancel(self._sync_timer)
            except Exception:
                pass
        self.db.close()


# ---------------------------------------------------------------------------
# small model factories kept out of the controller body


def _audit_event(action, entity_type, entity_id, actor, device_id):
    from app.models import AuditEvent
    return AuditEvent(action=action, entity_type=entity_type,
                      entity_id=entity_id, actor=actor, device_id=device_id)


def _device(device_id, unit_id=None):
    from app.models import Device
    from app.utils.dates import utcnow as _now
    return Device(device_id=device_id, unit_id=unit_id,
                  registered_at=_now(), last_seen_at=_now())
