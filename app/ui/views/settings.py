"""Settings view: facility, appearance, backups, sync, recycle bin, users."""

from __future__ import annotations

import customtkinter as ctk

from app.ui.components import FormDialog, FormField, Section
from app.ui.theme import DANGER, F_BODY, F_BOLD, F_SMALL, MUTED

APPEARANCES = ("system", "light", "dark")
UNIT_KINDS = ("department", "branch", "organization")
ROLE_OPTIONS = ("administrator", "physician", "nurse", "technician",
                "reception", "viewer")


class SettingsView(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app

        ctk.CTkLabel(self, text="Settings",
                     font=("Segoe UI", 22, "bold")).pack(anchor="w", padx=24,
                                                         pady=(20, 10))

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        # ------------------------------------------------ facility & storage
        storage = Section(scroll, "Facility & storage")
        storage.pack(fill="x", pady=(0, 12))
        info = ctk.CTkFrame(storage, fg_color="transparent")
        info.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 12))
        for text in (
            f"Facility:  {app.config.facility_name}",
            f"Storage mode:  {app.config.storage_mode}"
            + (f"  ({app.config.api_base_url})" if app.config.is_network_mode() else ""),
            f"Database:  {app.db.db_path}",
            f"Device:  {app.config.device_id}",
        ):
            ctk.CTkLabel(info, text=text, font=F_BODY, anchor="w").pack(
                fill="x", pady=1)

        mode_row = ctk.CTkFrame(info, fg_color="transparent")
        mode_row.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(mode_row, text="Switch to network mode (uses the API server):",
                     font=F_SMALL, text_color=MUTED).pack(side="left")
        if app.config.is_network_mode():
            ctk.CTkButton(mode_row, text="Work locally", font=F_SMALL, height=30,
                          command=self._go_local).pack(side="left", padx=8)
        else:
            ctk.CTkButton(mode_row, text="Connect to server…", font=F_SMALL,
                          height=30, command=self._go_network).pack(side="left", padx=8)

        # ---------------------------------------------------------- appearance
        look = Section(scroll, "Appearance")
        look.pack(fill="x", pady=(0, 12))
        seg = ctk.CTkSegmentedControl(look, values=list(APPEARANCES), height=32,
                                      command=self._set_theme)
        seg.set(app.config.theme)
        seg.grid(row=1, column=0, sticky="w", padx=12, pady=(2, 12))

        # ------------------------------------------------------- departments
        if "settings.manage" in app.permissions:
            depts = Section(scroll, "Departments")
            depts.pack(fill="x", pady=(0, 12))
            drow = ctk.CTkFrame(depts, fg_color="transparent")
            drow.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 6))
            ctk.CTkButton(drow, text="＋  New department", font=F_BOLD,
                          height=34, command=self._add_department).pack(side="left")
            self.dept_list = ctk.CTkFrame(depts, fg_color="transparent")
            self.dept_list.grid(row=2, column=0, sticky="ew", padx=12,
                                pady=(0, 12))

        # ---------------------------------------------------------- backups
        backups = Section(scroll, "Backups")
        backups.pack(fill="x", pady=(0, 12))
        brow = ctk.CTkFrame(backups, fg_color="transparent")
        brow.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 6))
        ctk.CTkButton(brow, text="Create backup now", font=F_BOLD, height=34,
                      command=self._backup_now).pack(side="left")
        ctk.CTkButton(brow, text="Restore from file…", font=F_SMALL, height=34,
                      fg_color="transparent", border_width=1,
                      border_color="#DFE7F0", text_color="#16283C",
                      command=self._restore).pack(side="left", padx=8)
        self.backup_list = ctk.CTkFrame(backups, fg_color="transparent")
        self.backup_list.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))

        # ------------------------------------------------- off-site cloud copy
        cloud = Section(scroll, "Off-site cloud copy (encrypted)")
        cloud.pack(fill="x", pady=(0, 12))
        crow = ctk.CTkFrame(cloud, fg_color="transparent")
        crow.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 6))
        ctk.CTkLabel(cloud, text=self.app.cloud_status(), font=F_SMALL,
                     text_color=MUTED, anchor="w").grid(
            row=2, column=0, sticky="ew", padx=12)
        ctk.CTkButton(crow, text="Configure…", font=F_SMALL, height=32,
                      command=self._configure_cloud).pack(side="left")
        ctk.CTkButton(crow, text="Upload encrypted copy now", font=F_SMALL,
                      height=32, command=self._cloud_upload).pack(side="left",
                                                                 padx=8)
        ctk.CTkLabel(cloud, text="Stored in your own bucket or cloud drive, "
                                 "unreadable without your passphrase.",
                     font=F_SMALL, text_color=MUTED,
                     anchor="w").grid(row=3, column=0, sticky="ew", padx=12,
                                      pady=(6, 10))

        # ---------------------------------------------------------- recycle bin
        bin_ = Section(scroll, "Recycle bin (soft-deleted records)")
        bin_.pack(fill="x", pady=(0, 12))
        self.bin_list = ctk.CTkFrame(bin_, fg_color="transparent")
        self.bin_list.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 12))

        # ------------------------------------------------ temporary access
        if "users.manage" in app.permissions:
            temp = Section(scroll, "Temporary access (scoped visitors)")
            temp.pack(fill="x", pady=(0, 12))
            trow = ctk.CTkFrame(temp, fg_color="transparent")
            trow.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 6))
            ctk.CTkButton(trow, text="＋  Grant temporary access", font=F_BOLD,
                          height=34, command=self._grant_temp).pack(side="left")
            self.temp_list = ctk.CTkFrame(temp, fg_color="transparent")
            self.temp_list.grid(row=2, column=0, sticky="ew", padx=12,
                                pady=(0, 12))

        # ---------------------------------------------------------- staff
        if "users.manage" in app.permissions:
            staff = Section(scroll, "Staff accounts")
            staff.pack(fill="x", pady=(0, 12))
            srow = ctk.CTkFrame(staff, fg_color="transparent")
            srow.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 6))
            ctk.CTkButton(srow, text="＋  Add staff account", font=F_BOLD,
                          height=34, command=self._add_user).pack(side="left")
            self.staff_list = ctk.CTkFrame(staff, fg_color="transparent")
            self.staff_list.grid(row=2, column=0, sticky="ew", padx=12,
                                 pady=(0, 12))

        # ---------------------------------------------------------- automation
        if "settings.manage" in app.permissions:
            auto = Section(scroll, "Automation rules")
            auto.pack(fill="x", pady=(0, 12))
            ar = ctk.CTkFrame(auto, fg_color="transparent")
            ar.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 6))
            ctk.CTkButton(ar, text="＋  New rule", font=F_BOLD, height=34,
                          command=self._add_rule).pack(side="left")
            ctk.CTkButton(ar, text="Run rules now", font=F_SMALL, height=34,
                          fg_color="transparent", border_width=1,
                          border_color="#DFE7F0", text_color="#16283C",
                          command=self._run_rules).pack(side="left", padx=8)
            self.rule_list = ctk.CTkFrame(auto, fg_color="transparent")
            self.rule_list.grid(row=2, column=0, sticky="ew", padx=12,
                                pady=(0, 12))

        # ---------------------------------------------------------- data portability
        port = Section(scroll, "Data portability")
        port.pack(fill="x", pady=(0, 12))
        prow = ctk.CTkFrame(port, fg_color="transparent")
        prow.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 12))
        ctk.CTkButton(prow, text="Export patient directory (JSON)", font=F_SMALL,
                      height=34, fg_color="transparent", border_width=1,
                      border_color="#DFE7F0", text_color="#16283C",
                      command=lambda: self.app.export_dataset("patients",
                                                              fmt="json")
                      ).pack(side="left")

        self.refresh_lists()

    # ------------------------------------------------------------------ #

    def refresh_lists(self) -> None:
        if hasattr(self, "dept_list"):
            for w in self.dept_list.winfo_children():
                w.destroy()
            try:
                units = [u for u in self.app.org.list_units()
                         if u.kind != "organization"]
            except Exception:
                units = []
            if not units:
                ctk.CTkLabel(self.dept_list, text="No departments yet",
                             font=F_SMALL, text_color=MUTED,
                             anchor="w").pack(fill="x")
            for unit in units:
                row = ctk.CTkFrame(self.dept_list, fg_color="transparent")
                row.pack(fill="x", pady=1)
                ctk.CTkLabel(row, text=unit.name, font=F_SMALL,
                             anchor="w").pack(side="left")
                ctk.CTkButton(row, text="Rename", font=F_SMALL, height=26,
                              width=76,
                              command=lambda uid=unit.unit_id, n=unit.name:
                              self._rename_department(uid, n)).pack(side="right",
                                                                    padx=(6, 0))
                ctk.CTkButton(row, text="Delete", font=F_SMALL, height=26,
                              width=76, fg_color="#FDECEA",
                              hover_color="#F8D7D4", text_color=DANGER,
                              command=lambda uid=unit.unit_id, n=unit.name:
                              self._delete_department(uid, n)).pack(side="right")

        if hasattr(self, "temp_list"):
            for w in self.temp_list.winfo_children():
                w.destroy()
            from app.utils.dates import to_iso, utcnow
            now = to_iso(utcnow())
            guests = [u for u in self.app.org.list_users()
                      if u.role == "temporary"]
            if not guests:
                ctk.CTkLabel(self.temp_list, text="No temporary accounts",
                             font=F_SMALL, text_color=MUTED,
                             anchor="w").pack(fill="x")
            for g in guests:
                row = ctk.CTkFrame(self.temp_list, fg_color="transparent")
                row.pack(fill="x", pady=1)
                state = ("expired" if g.is_expired(now)
                         else ("active" if g.active else "revoked"))
                ctk.CTkLabel(row, text=f"{g.display_name} ({g.username}) — "
                                       f"{len(g.scoped_patient_ids())} patient(s), "
                                       f"{state}, until {g.expires_at}",
                             font=F_SMALL, anchor="w").pack(side="left")
                if g.active and not g.is_expired(now):
                    ctk.CTkButton(row, text="Revoke", font=F_SMALL, height=26,
                                  width=80, fg_color="#FDECEA",
                                  hover_color="#F8D7D4", text_color=DANGER,
                                  command=lambda uid=g.user_id:
                                  self._revoke_temp(uid)).pack(side="right")

        for w in self.backup_list.winfo_children():
            w.destroy()
        for b in self.app.backups.list_backups()[:6]:
            row = ctk.CTkFrame(self.backup_list, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text=f"{b['name']}  ({b['size_display']})",
                         font=F_SMALL, anchor="w").pack(side="left")

        for w in self.bin_list.winfo_children():
            w.destroy()
        deleted = self.app.patients.deleted_patients()
        if not deleted:
            ctk.CTkLabel(self.bin_list, text="Recycle bin is empty",
                         font=F_SMALL, text_color=MUTED,
                         anchor="w").pack(fill="x")
        for s in deleted[:10]:
            row = ctk.CTkFrame(self.bin_list, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text=f"{s.patient_number} — {s.name}",
                         font=F_SMALL, anchor="w").pack(side="left")
            ctk.CTkButton(row, text="Restore", font=F_SMALL, height=26, width=80,
                          command=lambda pid=s.patient_id: self._restore_patient(pid)
                          ).pack(side="right")

        if hasattr(self, "staff_list"):
            for w in self.staff_list.winfo_children():
                w.destroy()
            for u in self.app.org.list_users():
                row = ctk.CTkFrame(self.staff_list, fg_color="transparent")
                row.pack(fill="x", pady=1)
                state = "active" if u.active else "disabled"
                ctk.CTkLabel(row, text=f"{u.username} — {u.display_name} "
                                       f"({u.role}, {state})",
                             font=F_SMALL, anchor="w").pack(side="left")
                toggle = ctk.CTkButton(
                    row, text="Disable" if u.active else "Enable",
                    font=F_SMALL, height=26, width=80,
                    command=lambda uid=u.user_id, on=u.active:
                    self._toggle_user(uid, on))
                toggle.pack(side="right")

        if hasattr(self, "rule_list"):
            for w in self.rule_list.winfo_children():
                w.destroy()
            rules = self.app.automation.list_rules()
            if not rules:
                ctk.CTkLabel(self.rule_list, text="No rules defined",
                             font=F_SMALL, text_color=MUTED,
                             anchor="w").pack(fill="x")
            for r in rules:
                row = ctk.CTkFrame(self.rule_list, fg_color="transparent")
                row.pack(fill="x", pady=1)
                ctk.CTkLabel(row, text=r.describe(), font=F_SMALL,
                             anchor="w").pack(side="left")
                ctk.CTkButton(row, text="Delete", font=F_SMALL, height=26,
                              width=70, fg_color="#FDECEA",
                              hover_color="#F8D7D4", text_color=DANGER,
                              command=lambda rid=r.rule_id:
                              self._drop_rule(rid)).pack(side="right")

    # ------------------------------------------------------------------ #

    def _grant_temp(self) -> None:
        fields = [
            FormField("label", "Who is it for?", required=True),
            FormField("hours", "Hours of access", required=True,
                      placeholder="e.g. 24"),
            FormField("patient_ids", "Patient IDs (comma-separated)",
                      required=True, placeholder="e.g. 1,3,7"),
        ]
        FormDialog(self, "Grant temporary access", fields,
                   self._submit_temp, submit_text="Create access")

    def _submit_temp(self, values: dict) -> None:
        try:
            hours = float(values["hours"])
        except (TypeError, ValueError):
            raise ValueError("Hours must be a number.")
        try:
            ids = [int(x) for x in (values["patient_ids"] or "").replace(" ", "").split(",")
                   if x]
        except ValueError:
            raise ValueError("Patient IDs must be numbers separated by commas.")
        guest, password = self.app.security.create_temporary_user(
            self.app.user, values["label"], hours, ids)
        self.app.confirm(
            "Temporary access created",
            f"Username: {guest.username}\nPassword: {password}\n"
            f"Expires: {guest.expires_at}\n\n"
            "Write these down now — the password is not shown again.")
        self.refresh_lists()

    def _set_theme(self, value: str) -> None:
        self.app.set_theme(value)

    def _go_local(self) -> None:
        self.app.set_storage_mode(local=True)

    def _go_network(self) -> None:
        FormDialog(self, "Connect to a MedFlow server", [
            FormField("api_base_url", "Server URL", required=True,
                      placeholder="http://192.168.1.20:8000"),
        ], lambda v: self.app.set_storage_mode(
            local=False, api_base_url=v["api_base_url"]),
            submit_text="Save")

    def _add_department(self) -> None:
        FormDialog(self, "New department", [
            FormField("name", "Department name", required=True,
                      placeholder="e.g. Maternity, Outpatient, Pharmacy"),
        ], self._submit_department, submit_text="Create")

    def _submit_department(self, values: dict) -> None:
        self.app.org.create_unit(values["name"].strip(), "department")
        self.app.toast("Department created", "ok")
        self.refresh_lists()

    def _rename_department(self, unit_id: int, current: str) -> None:
        FormDialog(self, f"Rename — {current}", [
            FormField("name", "New name", required=True),
        ], lambda v: (self.app.org.rename_unit(unit_id, v["name"]),
                      self.app.toast("Department renamed", "ok"),
                      self.refresh_lists()), submit_text="Rename")

    def _delete_department(self, unit_id: int, name: str) -> None:
        if not self.app.confirm("Delete department",
                                f'Delete "{name}"? Departments with records, '
                                "staff or appointments cannot be deleted."):
            return
        try:
            self.app.org.delete_unit(unit_id)
            self.app.toast("Department deleted", "ok")
        except Exception as exc:
            self.app.toast(str(exc), "error")
        self.refresh_lists()

    def _configure_cloud(self) -> None:
        FormDialog(self, "Off-site cloud copy", [
            FormField("provider", "Provider", kind="option",
                      options=("s3", "webdav")),
            FormField("endpoint", "Endpoint URL", required=True,
                      placeholder="https://s3.af-south-1.amazonaws.com"),
            FormField("bucket", "Bucket / folder", required=True),
            FormField("prefix", "Folder prefix", placeholder="optional"),
            FormField("access_key_id", "Access key / username"),
            FormField("secret_access_key", "Secret key / password"),
            FormField("enabled", "Enable uploads", kind="option",
                      options=("no", "yes")),
        ], self._submit_cloud, submit_text="Save")

    def _submit_cloud(self, values: dict) -> None:
        self.app.save_cloud_settings(values)
        self.app.toast("Cloud settings saved", "ok")
        self.refresh_lists()

    def _cloud_upload(self) -> None:
        FormDialog(self, "Upload encrypted copy", [
            FormField("passphrase", "Encryption passphrase",
                      required=True,
                      placeholder="min 8 characters — needed later to restore"),
        ], self._submit_cloud_upload, submit_text="Encrypt & upload")

    def _submit_cloud_upload(self, values: dict) -> None:
        try:
            name = self.app.cloud_upload_now(values["passphrase"])
            self.app.confirm("Off-site copy uploaded",
                             f"{name}\n\nKeep the passphrase safe — MedFlow "
                             "never stores it.")
        except Exception as exc:
            self.app.toast(str(exc), "error")

    def _backup_now(self) -> None:
        try:
            path = self.app.create_backup()
            self.app.toast(f"Backup saved: {path.name}", "ok")
        except Exception as exc:
            self.app.toast(str(exc), "error")
        self.refresh_lists()

    def _restore(self) -> None:
        path = self.app.pick_open_file(
            [("SQLite backup", "*.db"), ("All files", "*.*")])
        if not path:
            return
        if not self.app.confirm("Restore backup",
                                "Replace the live database with this snapshot?\n"
                                "Any changes made after the snapshot are lost."):
            return
        try:
            self.app.restore_backup(path)
            self.app.toast("Restore complete — restarting view", "ok")
            self.app.show_view("dashboard")
        except Exception as exc:
            self.app.toast(str(exc), "error")

    def _restore_patient(self, patient_id: int) -> None:
        self.app.patients.restore(patient_id)
        self.app.toast("Record restored", "ok")
        self.refresh_lists()

    def _revoke_temp(self, user_id: int) -> None:
        user = self.app.repos["users"].get(user_id)
        if user:
            user.active = False
            self.app.repos["users"].update(user, ["active"])
            self.app.toast("Access revoked", "ok")
        self.refresh_lists()

    def _add_user(self) -> None:
        fields = [
            FormField("username", "Username", required=True),
            FormField("display_name", "Full name", required=True),
            FormField("password", "Password", required=True,
                      placeholder="min 8 characters"),
            FormField("role", "Role", kind="option", options=ROLE_OPTIONS),
        ]
        FormDialog(self, "Add staff account", fields, self._submit_user,
                   submit_text="Create account")

    def _submit_user(self, values: dict) -> None:
        self.app.org.create_user(values["username"], values["display_name"],
                                 values["password"] or "", values["role"] or "viewer")
        self.app.toast("Account created", "ok")
        self.refresh_lists()

    def _toggle_user(self, user_id: int, currently_active: bool) -> None:
        self.app.org.set_user_active(user_id, not currently_active)
        self.refresh_lists()

    def _add_rule(self) -> None:
        fields = [
            FormField("name", "Rule name", required=True),
            FormField("fact", "Watch (fact)", kind="option",
                      options=tuple(self.app.automation.FACTS.keys())),
            FormField("operator", "Condition", kind="option",
                      options=(">", ">=", "<", "==")),
            FormField("threshold", "Threshold", required=True),
            FormField("action", "Action", kind="option",
                      options=tuple(self.app.automation.ACTIONS.keys())),
        ]
        FormDialog(self, "New automation rule", fields, self._submit_rule,
                   submit_text="Create rule")

    def _submit_rule(self, values: dict) -> None:
        self.app.automation.add_rule(values["name"], values["fact"],
                                     values["operator"],
                                     float(values["threshold"] or 0),
                                     values["action"])
        self.refresh_lists()

    def _drop_rule(self, rule_id: str) -> None:
        self.app.automation.remove_rule(rule_id)
        self.refresh_lists()

    def _run_rules(self) -> None:
        report = self.app.automation.run_once()
        fired = sum(1 for r in report if r["fired"])
        self.app.toast(f"{fired} of {len(report)} rule(s) fired", "ok")
        self.refresh_lists()
