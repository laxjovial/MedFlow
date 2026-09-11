"""The settings view.

Two kinds of thing live here, and the distinction is deliberate:

* **Preferences** — appearance. Changing one takes effect immediately and is
  written to ``config.json``, so it survives a restart.
* **Configuration** — where the database lives, how patient numbers are formatted,
  what the validators accept. These are shown read-only, with the path to the file
  that holds them.

The second group is displayed rather than editable because changing where the
database lives, or what a patient number looks like, from inside the running
application is a decision that deserves a text editor and a restart — not a
dropdown that silently points the app at a different register.

Data management — backups, export, import — lives here because it is about the
whole database rather than one patient.
"""

from __future__ import annotations

from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog

from app.config.constants import APP_NAME, EXPORT_FORMATS
from app.core.exceptions import MedFlowError
from app.ui.dialogs.confirm import ConfirmDialog, NotifyDialog
from app.ui.theme import (
    FONT_BODY,
    FONT_BODY_BOLD,
    FONT_SMALL,
    FONT_TINY,
    GAP_MD,
    GAP_SM,
    GAP_XS,
    PALETTE,
    RADIUS_MD,
)
from app.ui.views.base import View
from app.ui.widgets.cards import EmptyState, FieldRow, Section

#: Appearance modes offered. These are CustomTkinter's own accepted values.
APPEARANCE_CHOICES = ("System", "Light", "Dark")

#: Colour themes shipped with CustomTkinter.
THEME_CHOICES = ("blue", "dark-blue", "green", "gold")


class SettingsView(View):
    """Preferences, configuration and data management."""

    title = "Settings"
    subtitle = (
        "Appearance is saved as you change it. Everything else is read from the "
        "configuration file shown at the bottom of this page."
    )

    def build(self) -> None:
        self._scroll = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        self._scroll.grid(row=0, column=0, sticky="nsew")
        self._scroll.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self._build_appearance()
        self._build_storage()
        self._build_data()

    # ---------- appearance ----------

    def _build_appearance(self) -> None:
        section = Section(
            self._scroll,
            title="Appearance",
            subtitle="Applies immediately, and is remembered next time MedFlow starts.",
        )
        section.grid(row=0, column=0, sticky="ew", pady=(0, GAP_SM))

        row = ctk.CTkFrame(section.body, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew", pady=(0, GAP_SM))
        row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            row, text="Mode", font=FONT_SMALL, text_color=PALETTE.text_muted, anchor="w", width=132
        ).grid(row=0, column=0, sticky="w")

        self._mode_selector = ctk.CTkSegmentedButton(
            row,
            values=list(APPEARANCE_CHOICES),
            command=self._on_mode_changed,
            font=FONT_SMALL,
            height=32,
            selected_color=PALETTE.accent,
            selected_hover_color=PALETTE.accent_hover,
            unselected_color=PALETTE.surface_alt,
            unselected_hover_color=PALETTE.border,
            text_color=PALETTE.text,
        )
        self._mode_selector.grid(row=0, column=1, sticky="w")

        theme_row = ctk.CTkFrame(section.body, fg_color="transparent")
        theme_row.grid(row=1, column=0, sticky="ew", pady=(0, GAP_XS))
        theme_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            theme_row,
            text="Colour theme",
            font=FONT_SMALL,
            text_color=PALETTE.text_muted,
            anchor="w",
            width=132,
        ).grid(row=0, column=0, sticky="w")

        self._theme_menu = ctk.CTkOptionMenu(
            theme_row,
            values=list(THEME_CHOICES),
            command=self._on_theme_changed,
            width=180,
            height=30,
            font=FONT_TINY,
            dropdown_font=FONT_TINY,
            fg_color=PALETTE.surface_alt,
            button_color=PALETTE.surface_alt,
            button_hover_color=PALETTE.border,
            text_color=PALETTE.text,
        )
        self._theme_menu.grid(row=0, column=1, sticky="w")

    def _on_mode_changed(self, mode: str) -> None:
        ctk.set_appearance_mode(mode)
        self.app.apply_appearance(mode, self.container.settings.appearance.color_theme)
        self.set_status(f"Appearance set to {mode}.")

    def _on_theme_changed(self, theme: str) -> None:
        ctk.set_default_color_theme(theme)
        self.app.apply_appearance(self.container.settings.appearance.mode, theme)
        self.set_status(f"Colour theme set to {theme}.")

    # ---------- configuration ----------

    def _build_storage(self) -> None:
        self._storage_section = Section(
            self._scroll,
            title="Configuration",
            subtitle="Read from the configuration file. Restart MedFlow after editing it.",
        )
        self._storage_section.grid(row=1, column=0, sticky="ew", pady=(0, GAP_SM))

    def _render_storage(self) -> None:
        settings = self.container.settings
        for child in self._storage_section.body.winfo_children():
            child.destroy()

        entries = (
            ("Storage mode", settings.storage.mode),
            ("Database", str(settings.database_path)),
            ("Backups", str(settings.backup_directory)),
            ("Exports", str(settings.export_directory)),
            ("Logs", str(settings.log_directory)),
            ("Patient numbers", f"{settings.patient_ids.prefix}-{'0' * settings.patient_ids.padding}"),
            ("Age range", f"{settings.validation.min_age}–{settings.validation.max_age}"),
            ("Log level", settings.logging.level),
        )

        for index, (label, value) in enumerate(entries):
            FieldRow(self._storage_section.body, label=label, value=value, wraplength=520).grid(
                row=index, column=0, sticky="ew"
            )

        config_path = settings.config_path or (settings.base_directory / "config.json")
        ctk.CTkLabel(
            self._storage_section.body,
            text=(
                f"Configuration file: {config_path}\n"
                "It is optional — MedFlow runs on built-in defaults when it is absent."
            ),
            font=FONT_TINY,
            text_color=PALETTE.text_muted,
            anchor="w",
            justify="left",
            wraplength=560,
        ).grid(row=len(entries), column=0, sticky="ew", pady=(GAP_SM, 0))

    # ---------- data ----------

    def _build_data(self) -> None:
        section = Section(
            self._scroll,
            title="Data",
            subtitle=(
                "Backups capture the whole database safely while MedFlow is running. "
                "Exports write patient data to a file — treat the file as carefully as "
                "the database itself."
            ),
        )
        section.grid(row=2, column=0, sticky="ew", pady=(0, GAP_SM))

        buttons = ctk.CTkFrame(section.body, fg_color="transparent")
        buttons.grid(row=0, column=0, sticky="ew", pady=(0, GAP_SM))

        for column, (label, command) in enumerate(
            (
                ("Create backup", self._create_backup),
                ("Export CSV", lambda: self._export("csv")),
                ("Export JSON", lambda: self._export("json")),
                ("Import file", self._import),
            )
        ):
            ctk.CTkButton(
                buttons,
                text=label,
                command=command,
                width=124,
                height=34,
                font=FONT_SMALL,
                fg_color=PALETTE.accent if column == 0 else "transparent",
                hover_color=PALETTE.accent_hover if column == 0 else PALETTE.surface_alt,
                border_width=0 if column == 0 else 1,
                border_color=PALETTE.border,
                text_color=PALETTE.text_inverse if column == 0 else PALETTE.text,
            ).grid(row=0, column=column, padx=(0, GAP_XS))

        self._backups = ctk.CTkFrame(section.body, fg_color="transparent")
        self._backups.grid(row=1, column=0, sticky="ew")
        self._backups.grid_columnconfigure(0, weight=1)

    def _render_backups(self) -> None:
        for child in self._backups.winfo_children():
            child.destroy()

        backups = self.container.backups.list_backups()

        if not backups:
            ctk.CTkLabel(
                self._backups,
                text="No backups yet.",
                font=FONT_TINY,
                text_color=PALETTE.text_muted,
                anchor="w",
            ).grid(row=0, column=0, sticky="ew")
            return

        ctk.CTkLabel(
            self._backups,
            text=f"Recent backups ({len(backups)})",
            font=FONT_BODY_BOLD,
            text_color=PALETTE.text,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, GAP_XS))

        for index, info in enumerate(backups[:5], start=1):
            line = ctk.CTkFrame(self._backups, fg_color="transparent")
            line.grid(row=index, column=0, sticky="ew", pady=(0, GAP_XS))
            line.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                line,
                text=f"{info.name} · {info.size_label}",
                font=FONT_TINY,
                text_color=PALETTE.text,
                anchor="w",
            ).grid(row=0, column=0, sticky="w")

            ctk.CTkLabel(
                line,
                text=info.created_at.strftime("%Y-%m-%d %H:%M"),
                font=FONT_TINY,
                text_color=PALETTE.text_muted,
                anchor="e",
            ).grid(row=0, column=1, sticky="e")

    # ---------- actions ----------

    def _create_backup(self) -> None:
        try:
            info = self.container.backups.create_backup(actor=self.app.actor)
        except MedFlowError as error:
            NotifyDialog.show(self.app, title="Backup failed", message=error.message, tone="danger")
            return

        self._render_backups()
        self.set_status(f"Backup written: {info.name}")
        NotifyDialog.show(
            self.app,
            title="Backup complete",
            message=f"Saved {info.name} ({info.size_label}) to:\n{info.path.parent}",
        )

    def _export(self, fmt: str) -> None:
        extension = EXPORT_FORMATS[fmt]
        destination = filedialog.asksaveasfilename(
            parent=self.app,
            title=f"Export patients as {fmt.upper()}",
            initialdir=str(self.container.settings.export_directory),
            initialfile=f"{APP_NAME.lower()}-patients-{self.container.clock.today()}{extension}",
            defaultextension=extension,
            filetypes=[(f"{fmt.upper()} file", f"*{extension}"), ("All files", "*.*")],
        )
        if not destination:
            return

        try:
            path = self.container.transfer.export_patients(
                Path(destination), actor=self.app.actor, fmt=fmt
            )
        except MedFlowError as error:
            NotifyDialog.show(self.app, title="Export failed", message=error.message, tone="danger")
            return

        self.set_status(f"Exported to {path.name}.")
        NotifyDialog.show(self.app, title="Export complete", message=f"Written to:\n{path}")

    def _import(self) -> None:
        source = filedialog.askopenfilename(
            parent=self.app,
            title="Choose a file to import",
            initialdir=str(self.container.settings.export_directory),
            filetypes=[("CSV or JSON", "*.csv *.json"), ("All files", "*.*")],
        )
        if not source:
            return

        try:
            preview = self.container.transfer.preview_import(Path(source))
        except MedFlowError as error:
            NotifyDialog.show(self.app, title="Could not read that file", message=error.message, tone="danger")
            return

        if not preview.total_rows:
            NotifyDialog.show(
                self.app, title="Nothing to import", message="No rows were found in that file."
            )
            return

        detail = preview.summary
        if preview.invalid_rows:
            examples = "\n".join(
                f"• row {row.line}: {row.error_summary}" for row in preview.invalid_rows[:4]
            )
            detail += f"\n\nRows that will be skipped:\n{examples}"

        if not preview.can_import:
            NotifyDialog.show(
                self.app,
                title="Nothing importable",
                message="Every row in that file failed validation.",
                tone="warning",
            )
            return

        if not ConfirmDialog.ask(
            self.app,
            title="Import these patients?",
            message="Rows are validated before they are written, and a bad row is skipped rather than stopping the file.",
            detail=detail,
            confirm_label=f"Import {len(preview.valid_rows)}",
        ):
            return

        try:
            result = self.container.transfer.import_patients(
                Path(source), actor=self.app.actor, preview=preview
            )
        except MedFlowError as error:
            NotifyDialog.show(self.app, title="Import failed", message=error.message, tone="danger")
            return

        message = result.summary
        if result.failures:
            message += "\n\n" + "\n".join(
                f"• {label}: {reason}" for label, reason in result.failures[:4]
            )

        self.set_status(result.summary)
        NotifyDialog.show(self.app, title="Import finished", message=message)

    # ---------- lifecycle ----------

    def on_show(self) -> None:
        settings = self.container.settings
        self._mode_selector.set(settings.appearance.mode)
        self._theme_menu.set(settings.appearance.color_theme)
        self._render_storage()
        self._render_backups()
