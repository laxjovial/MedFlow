"""The patients view.

A master–detail workspace: the register on the left, the selected record on the
right. The detail pane is tabbed because the four things a clinician wants about a
patient — who they are, what they have been diagnosed with, what has happened to
the record, and who has touched it — are read at different moments rather than all
at once.

All four actions the register supports live in one place: create, read, update and
delete, with delete being a soft delete the user can undo.
"""

from __future__ import annotations

import customtkinter as ctk

from app.core.exceptions import MedFlowError
from app.domain.enums import SORT_OPTIONS, DiagnosisStatus, PatientStatus
from app.domain.patient import Patient
from app.ui.dialogs.confirm import ConfirmDialog, NotifyDialog
from app.ui.dialogs.patient_form import PatientFormDialog
from app.ui.dialogs.prompt import TextPromptDialog
from app.ui.theme import (
    FONT_BODY,
    FONT_BODY_BOLD,
    FONT_HEADING,
    FONT_SMALL,
    FONT_TINY,
    GAP_MD,
    GAP_SM,
    GAP_XS,
    PALETTE,
    RADIUS_MD,
    SEARCH_DEBOUNCE_MS,
)
from app.ui.views.base import View
from app.ui.widgets.cards import EmptyState, FieldRow, Section

LIST_WIDTH = 330

SORT_LABELS = {label: key for key, label in SORT_OPTIONS.items()}


class PatientsView(View):
    """Browse, search, create, edit and delete patient records."""

    title = "Patients"
    subtitle = "Search the register, open a record, and record changes to it."

    def build(self) -> None:
        self._selected: Patient | None = None
        self._rows: dict[str, ctk.CTkButton] = {}
        self._search_job: str | None = None
        self._sort_key = next(iter(SORT_OPTIONS))
        self._descending = False
        self._include_deleted = False

        self._build_actions()

        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=0)
        self.content.grid_columnconfigure(1, weight=1)

        self._build_list_panel()
        self._build_detail_panel()

    # ---------- construction ----------

    def _build_actions(self) -> None:
        ctk.CTkButton(
            self.header_actions,
            text="+ New patient",
            command=self.create_patient,
            width=140,
            height=34,
            font=FONT_BODY_BOLD,
            fg_color=PALETTE.accent,
            hover_color=PALETTE.accent_hover,
            text_color=PALETTE.text_inverse,
        ).grid(row=0, column=0, padx=(0, GAP_XS))

        self._export_button = ctk.CTkButton(
            self.header_actions,
            text="Export CSV",
            command=self._export,
            width=110,
            height=34,
            font=FONT_BODY,
            fg_color="transparent",
            border_width=1,
            border_color=PALETTE.border,
            text_color=PALETTE.text,
            hover_color=PALETTE.surface_alt,
        )
        self._export_button.grid(row=0, column=1)

    def _build_list_panel(self) -> None:
        panel = ctk.CTkFrame(
            self.content,
            fg_color=PALETTE.surface,
            corner_radius=RADIUS_MD,
            border_width=1,
            border_color=PALETTE.border,
            width=LIST_WIDTH,
        )
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, GAP_SM))
        panel.grid_propagate(False)
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(3, weight=1)

        self._search = ctk.CTkEntry(
            panel,
            placeholder_text="Search name, number or diagnosis",
            height=34,
            font=FONT_SMALL,
            corner_radius=RADIUS_MD,
        )
        self._search.grid(row=0, column=0, sticky="ew", padx=GAP_SM, pady=(GAP_SM, GAP_XS))
        # Debounced: typing a name should not run a query per keystroke.
        self._search.bind("<KeyRelease>", self._on_search_changed)

        controls = ctk.CTkFrame(panel, fg_color="transparent")
        controls.grid(row=1, column=0, sticky="ew", padx=GAP_SM, pady=(0, GAP_XS))
        controls.grid_columnconfigure(0, weight=1)

        self._sort_menu = ctk.CTkOptionMenu(
            controls,
            values=list(SORT_OPTIONS.values()),
            command=self._on_sort_changed,
            height=30,
            font=FONT_TINY,
            dropdown_font=FONT_TINY,
            fg_color=PALETTE.surface_alt,
            button_color=PALETTE.surface_alt,
            button_hover_color=PALETTE.border,
            text_color=PALETTE.text,
        )
        self._sort_menu.grid(row=0, column=0, sticky="ew")
        self._sort_menu.set(SORT_OPTIONS[self._sort_key])

        self._direction_button = ctk.CTkButton(
            controls,
            text="↓",
            command=self._toggle_direction,
            width=34,
            height=30,
            font=FONT_BODY,
            fg_color=PALETTE.surface_alt,
            hover_color=PALETTE.border,
            text_color=PALETTE.text,
        )
        self._direction_button.grid(row=0, column=1, padx=(GAP_XS, 0))

        self._show_deleted = ctk.CTkSwitch(
            panel,
            text="Include deleted",
            command=self._on_toggle_deleted,
            font=FONT_TINY,
            text_color=PALETTE.text_muted,
            progress_color=PALETTE.accent,
            button_color=PALETTE.neutral,
            button_hover_color=PALETTE.text_muted,
        )
        self._show_deleted.grid(row=2, column=0, sticky="w", padx=GAP_SM, pady=(0, GAP_XS))

        self._list = ctk.CTkScrollableFrame(panel, fg_color="transparent")
        self._list.grid(row=3, column=0, sticky="nsew", padx=GAP_XS, pady=(0, GAP_SM))
        self._list.grid_columnconfigure(0, weight=1)

        self._list_count = ctk.CTkLabel(
            panel, text="", font=FONT_TINY, text_color=PALETTE.text_muted, anchor="w"
        )
        self._list_count.grid(row=4, column=0, sticky="ew", padx=GAP_SM, pady=(0, GAP_SM))

    def _build_detail_panel(self) -> None:
        self._detail = ctk.CTkFrame(
            self.content,
            fg_color=PALETTE.surface,
            corner_radius=RADIUS_MD,
            border_width=1,
            border_color=PALETTE.border,
        )
        self._detail.grid(row=0, column=1, sticky="nsew")
        self._detail.grid_columnconfigure(0, weight=1)
        self._detail.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self._detail, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=GAP_SM + GAP_XS, pady=(GAP_SM, 0))
        header.grid_columnconfigure(0, weight=1)

        self._detail_name = ctk.CTkLabel(
            header, text="", font=FONT_HEADING, text_color=PALETTE.text, anchor="w"
        )
        self._detail_name.grid(row=0, column=0, sticky="w")

        self._detail_meta = ctk.CTkLabel(
            header, text="", font=FONT_TINY, text_color=PALETTE.text_muted, anchor="w"
        )
        self._detail_meta.grid(row=1, column=0, sticky="w")

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=1, rowspan=2, sticky="e")

        self._edit_button = self._action_button(actions, "Edit", self._edit_patient, 0)
        self._diagnosis_button = self._action_button(
            actions, "Add diagnosis", self._add_diagnosis, 1
        )
        self._delete_button = self._action_button(
            actions, "Delete", self._delete_patient, 2, tone="danger"
        )

        self._tabs = ctk.CTkTabview(
            self._detail,
            fg_color="transparent",
            segmented_button_fg_color=PALETTE.surface_alt,
            segmented_button_selected_color=PALETTE.accent,
            segmented_button_selected_hover_color=PALETTE.accent_hover,
            segmented_button_unselected_color=PALETTE.surface_alt,
            text_color=PALETTE.text,
        )
        self._tabs.grid(row=1, column=0, sticky="nsew", padx=GAP_SM, pady=(GAP_SM, GAP_SM))

        self._overview = self._tabs.add("Overview")
        self._diagnoses_tab = self._tabs.add("Diagnoses")
        self._timeline_tab = self._tabs.add("Timeline")
        self._audit_tab = self._tabs.add("Audit")

        for tab in (self._overview, self._diagnoses_tab, self._timeline_tab, self._audit_tab):
            tab.grid_columnconfigure(0, weight=1)

        self._empty = EmptyState(
            self._detail,
            title="No patient selected",
            message="Choose a patient from the register, or register a new one.",
            action_label="+ New patient",
            command=self.create_patient,
        )

    def _action_button(
        self,
        parent: ctk.CTkBaseClass,
        label: str,
        command,
        column: int,
        *,
        tone: str = "neutral",
    ) -> ctk.CTkButton:
        button = ctk.CTkButton(
            parent,
            text=label,
            command=command,
            width=112 if len(label) > 8 else 78,
            height=32,
            font=FONT_SMALL,
            fg_color="transparent",
            border_width=1,
            border_color=PALETTE.border,
            text_color=PALETTE.danger if tone == "danger" else PALETTE.text,
            hover_color=PALETTE.surface_alt,
        )
        button.grid(row=0, column=column, padx=(GAP_XS, 0))
        return button

    # ---------- lifecycle ----------

    def on_show(self) -> None:
        self._refresh_list()
        if self._selected is not None:
            # Re-read rather than trusting the cached copy: the record may have
            # been changed by the dialog that brought us back here.
            refreshed = self.container.patients.get(
                self._selected.patient_number, include_deleted=True
            )
            self._selected = refreshed
        self._render_detail()

    # ---------- list ----------

    def _on_search_changed(self, _event: object = None) -> None:
        if self._search_job is not None:
            self.after_cancel(self._search_job)
        self._search_job = self.after(SEARCH_DEBOUNCE_MS, self._refresh_list)

    def _on_sort_changed(self, label: str) -> None:
        self._sort_key = SORT_LABELS.get(label, self._sort_key)
        self._refresh_list()

    def _toggle_direction(self) -> None:
        self._descending = not self._descending
        self._direction_button.configure(text="↓" if self._descending else "↑")
        self._refresh_list()

    def _on_toggle_deleted(self) -> None:
        self._include_deleted = bool(self._show_deleted.get())
        self._refresh_list()

    def _refresh_list(self) -> None:
        self._search_job = None

        try:
            patients = self.container.patients.search(
                self._search.get(),
                sort_by=self._sort_key,
                descending=self._descending,
                include_deleted=self._include_deleted,
            )
        except MedFlowError as error:
            self.set_status(error.message)
            return

        for child in self._list.winfo_children():
            child.destroy()
        self._rows.clear()

        if not patients:
            EmptyState(
                self._list,
                title="No matching patients",
                message="Try a different search, or register a new patient.",
            ).grid(row=0, column=0, sticky="ew", pady=GAP_MD)
        else:
            for row, patient in enumerate(patients):
                button = self._patient_row(patient)
                button.grid(row=row, column=0, sticky="ew", pady=(0, GAP_XS))
                self._rows[patient.patient_number] = button

        self._highlight_selection()
        self._list_count.configure(
            text=f"{len(patients)} patient(s) shown"
            + (" · including deleted" if self._include_deleted else "")
        )

    def _patient_row(self, patient: Patient) -> ctk.CTkButton:
        caption = patient.full_name
        if patient.is_deleted:
            caption = f"{caption} · deleted"
        elif patient.status != PatientStatus.ACTIVE.value:
            caption = f"{caption} · {patient.status}"

        return ctk.CTkButton(
            self._list,
            text=f"{patient.patient_number}\n{caption}",
            command=lambda number=patient.patient_number: self._select(number),
            anchor="w",
            height=52,
            font=FONT_SMALL,
            fg_color="transparent",
            hover_color=PALETTE.surface_alt,
            text_color=PALETTE.text_muted if patient.is_deleted else PALETTE.text,
        )

    def _highlight_selection(self) -> None:
        for number, button in self._rows.items():
            selected = self._selected is not None and number == self._selected.patient_number
            button.configure(
                fg_color=PALETTE.accent_soft if selected else "transparent",
                text_color=PALETTE.accent if selected else PALETTE.text,
            )

    def _select(self, patient_number: str) -> None:
        patient = self.container.patients.get(patient_number, include_deleted=True)
        if patient is None:
            self.set_status(f"Patient {patient_number} is no longer available.")
            self._refresh_list()
            return
        self._selected = patient
        self._highlight_selection()
        self._render_detail()

    # ---------- detail ----------

    def _render_detail(self) -> None:
        patient = self._selected

        if patient is None:
            self._tabs.grid_remove()
            for child in (
                self._detail_name,
                self._detail_meta,
                self._edit_button,
                self._diagnosis_button,
                self._delete_button,
            ):
                child.grid_remove()
            self._empty.grid(row=0, column=0, rowspan=2, sticky="nsew")
            return

        self._empty.grid_remove()
        self._detail_name.grid()
        self._detail_meta.grid()
        self._edit_button.grid()
        self._delete_button.grid()
        self._tabs.grid()

        self._detail_name.configure(text=patient.full_name)
        status = patient.status.upper()
        if patient.is_deleted:
            status = f"DELETED {self.format_timestamp(patient.deleted_at)}"
        self._detail_meta.configure(
            text=(
                f"{patient.patient_number} · {status} · version {patient.record_version} · "
                f"updated {self.format_timestamp(patient.updated_at)}"
            )
        )

        if patient.is_deleted:
            self._diagnosis_button.grid_remove()
        else:
            self._diagnosis_button.grid()

        self._delete_button.configure(
            text="Restore" if patient.is_deleted else "Delete",
            text_color=PALETTE.success if patient.is_deleted else PALETTE.danger,
        )
        self._edit_button.configure(state="disabled" if patient.is_deleted else "normal")

        self._render_overview(patient)
        self._render_diagnoses(patient)
        self._render_timeline(patient)
        self._render_audit(patient)

    def _render_overview(self, patient: Patient) -> None:
        for child in self._overview.winfo_children():
            child.destroy()

        row = 0
        row = self._add_field_section(
            self._overview,
            "Demographics",
            row,
            (
                ("Patient number", patient.patient_number),
                ("Date of birth", patient.date_of_birth or "Not recorded"),
                ("Age", patient.age_years or "Not recorded"),
                ("Sex", patient.sex or "Not recorded"),
            ),
        )
        row = self._add_field_section(
            self._overview,
            "Contact",
            row,
            (
                ("Phone", patient.phone),
                ("Email", patient.email),
                ("Address", patient.address),
            ),
        )
        row = self._add_field_section(
            self._overview,
            "Clinical record",
            row,
            (
                ("Blood pressure", patient.record.blood_pressure),
                ("Heart rate", patient.record.heart_rate),
                ("Weight", patient.record.weight),
                ("Height", patient.record.height),
                ("Medical history", patient.record.medical_history),
                ("Notes", patient.record.notes),
            ),
        )

        footer = self.caption(
            f"Created {self.format_timestamp(patient.created_at)} by "
            f"{patient.created_by or 'unknown'} · last updated "
            f"{self.format_timestamp(patient.updated_at)} by {patient.updated_by or 'unknown'}"
        )
        footer.grid(row=row, column=0, sticky="ew", pady=(GAP_XS, 0))

    def _add_field_section(
        self,
        parent: ctk.CTkBaseClass,
        title: str,
        row: int,
        entries: tuple[tuple[str, str], ...],
    ) -> int:
        section = Section(parent, title=title)
        section.grid(row=row, column=0, sticky="ew", pady=(0, GAP_SM))

        for index, (label, value) in enumerate(entries):
            FieldRow(section.body, label=label, value=value).grid(
                row=index, column=0, sticky="ew"
            )

        return row + 1

    def _render_diagnoses(self, patient: Patient) -> None:
        for child in self._diagnoses_tab.winfo_children():
            child.destroy()

        if not patient.diagnoses:
            EmptyState(
                self._diagnoses_tab,
                title="No diagnoses recorded",
                message="Use “Add diagnosis” to record one against this patient.",
            ).grid(row=0, column=0, sticky="ew", pady=GAP_MD)
            return

        for row, diagnosis in enumerate(patient.diagnoses):
            card = ctk.CTkFrame(
                self._diagnoses_tab,
                fg_color=PALETTE.surface_alt if row % 2 else "transparent",
                corner_radius=RADIUS_MD,
            )
            card.grid(row=row, column=0, sticky="ew", pady=(0, GAP_XS))
            card.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                card,
                text=diagnosis.diagnosis,
                font=FONT_BODY_BOLD,
                text_color=PALETTE.text,
                anchor="w",
                justify="left",
                wraplength=420,
            ).grid(row=0, column=0, sticky="ew", padx=GAP_SM, pady=(GAP_XS, 0))

            meta = f"{diagnosis.status_label} · recorded {diagnosis.diagnosed_at or '—'}"
            if diagnosis.notes:
                meta += f" · {diagnosis.notes}"

            ctk.CTkLabel(
                card,
                text=meta,
                font=FONT_TINY,
                text_color=_status_colour(diagnosis.status),
                anchor="w",
                justify="left",
                wraplength=420,
            ).grid(row=1, column=0, sticky="ew", padx=GAP_SM, pady=(0, GAP_XS))

            if diagnosis.is_active and not patient.is_deleted:
                ctk.CTkButton(
                    card,
                    text="Resolve",
                    command=lambda identifier=diagnosis.id: self._resolve_diagnosis(identifier),
                    width=80,
                    height=28,
                    font=FONT_TINY,
                    fg_color="transparent",
                    border_width=1,
                    border_color=PALETTE.border,
                    text_color=PALETTE.text,
                    hover_color=PALETTE.surface,
                ).grid(row=0, column=1, rowspan=2, padx=GAP_SM)

    def _render_timeline(self, patient: Patient) -> None:
        for child in self._timeline_tab.winfo_children():
            child.destroy()

        events = self.container.patients.timeline(patient.patient_number)

        if not events:
            EmptyState(
                self._timeline_tab,
                title="No history yet",
                message="Changes to this record are listed here as they happen.",
            ).grid(row=0, column=0, sticky="ew", pady=GAP_MD)
            return

        for row, event in enumerate(events):
            line = ctk.CTkFrame(self._timeline_tab, fg_color="transparent")
            line.grid(row=row, column=0, sticky="ew", pady=(0, GAP_SM))
            line.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                line,
                text=event.label,
                font=FONT_SMALL,
                text_color=PALETTE.text,
                anchor="w",
            ).grid(row=0, column=0, sticky="ew")

            ctk.CTkLabel(
                line,
                text=self.format_timestamp(event.created_at),
                font=FONT_TINY,
                text_color=PALETTE.text_muted,
                anchor="e",
            ).grid(row=0, column=1, sticky="e")

            ctk.CTkLabel(
                line,
                text=f"{event.description} · {event.actor}" if event.actor else event.description,
                font=FONT_TINY,
                text_color=PALETTE.text_muted,
                anchor="w",
                justify="left",
                wraplength=520,
            ).grid(row=1, column=0, columnspan=2, sticky="ew")

    def _render_audit(self, patient: Patient) -> None:
        for child in self._audit_tab.winfo_children():
            child.destroy()

        entries = self.container.patients.audit_trail(patient.patient_number)

        if not entries:
            EmptyState(
                self._audit_tab,
                title="Nothing recorded",
                message="Who viewed or changed this record is logged here.",
            ).grid(row=0, column=0, sticky="ew", pady=GAP_MD)
            return

        for row, entry in enumerate(entries):
            line = ctk.CTkFrame(self._audit_tab, fg_color="transparent")
            line.grid(row=row, column=0, sticky="ew", pady=(0, GAP_SM))
            line.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                line,
                text=entry.summary,
                font=FONT_SMALL,
                text_color=PALETTE.text,
                anchor="w",
                justify="left",
                wraplength=520,
            ).grid(row=0, column=0, sticky="ew")

            ctk.CTkLabel(
                line,
                text=self.format_timestamp(entry.created_at),
                font=FONT_TINY,
                text_color=PALETTE.text_muted,
                anchor="e",
            ).grid(row=0, column=1, sticky="e")

    # ---------- actions ----------

    def _actor(self) -> str:
        return self.app.actor

    def create_patient(self) -> None:
        """Open the registration dialog.

        Public because the shell binds a keyboard shortcut to it, and a shortcut is
        a legitimate second caller rather than something to route through a private
        method.
        """
        dialog = PatientFormDialog(
            self.app,
            service=self.container.patients,
            actor=self._actor(),
        )
        self.app.wait_window(dialog)

        if dialog.saved_patient is not None:
            self._selected = dialog.saved_patient
            self._refresh_list()
            self._render_detail()
            self.set_status(f"Registered {dialog.saved_patient.patient_number}.")

    def _edit_patient(self) -> None:
        if self._selected is None:
            return

        dialog = PatientFormDialog(
            self.app,
            service=self.container.patients,
            actor=self._actor(),
            patient=self._selected,
        )
        self.app.wait_window(dialog)

        if dialog.saved_patient is not None:
            self._selected = dialog.saved_patient
            self._refresh_list()
            self._render_detail()
            self.set_status(f"Updated {dialog.saved_patient.patient_number}.")

    def _delete_patient(self) -> None:
        patient = self._selected
        if patient is None:
            return

        if patient.is_deleted:
            if not ConfirmDialog.ask(
                self.app,
                title="Restore this patient?",
                message=f"{patient.full_name} will return to the active register.",
                detail=f"{patient.patient_number} · the record and its history are unchanged.",
                confirm_label="Restore",
            ):
                return
            action = lambda: self.container.patients.restore(patient.patient_number, actor=self._actor())
            verb = "Restored"
        else:
            if not ConfirmDialog.ask(
                self.app,
                title="Delete this patient?",
                message=f"{patient.full_name} will be removed from the active register.",
                detail=(
                    f"{patient.patient_number} is retained with its full history and can be "
                    "restored later. The patient number will not be reused."
                ),
                confirm_label="Delete",
                tone="danger",
            ):
                return
            action = lambda: self.container.patients.delete(patient.patient_number, actor=self._actor())
            verb = "Deleted"

        try:
            action()
        except MedFlowError as error:
            NotifyDialog.show(self.app, title="Could not complete that", message=error.message, tone="danger")
            return

        self._selected = self.container.patients.get(patient.patient_number, include_deleted=True)
        self._refresh_list()
        self._render_detail()
        self.set_status(f"{verb} {patient.patient_number}.")

    def _add_diagnosis(self) -> None:
        patient = self._selected
        if patient is None:
            return

        dialog = TextPromptDialog(
            self.app,
            title="Add diagnosis",
            message=f"Record a diagnosis against {patient.full_name} ({patient.patient_number}).",
            label="Diagnosis",
            confirm_label="Add diagnosis",
        )
        self.app.wait_window(dialog)

        if dialog.value is None:
            return

        try:
            self.container.patients.add_diagnosis(
                patient.patient_number, dialog.value, actor=self._actor()
            )
        except MedFlowError as error:
            NotifyDialog.show(self.app, title="Could not add that diagnosis", message=error.message, tone="danger")
            return

        self._selected = self.container.patients.get(patient.patient_number, include_deleted=True)
        self._render_detail()
        self.set_status(f"Diagnosis added to {patient.patient_number}.")

    def _resolve_diagnosis(self, diagnosis_id: int | None) -> None:
        patient = self._selected
        if patient is None or diagnosis_id is None:
            return

        try:
            self.container.patients.resolve_diagnosis(
                patient.patient_number,
                diagnosis_id,
                actor=self._actor(),
                status=DiagnosisStatus.RESOLVED,
            )
        except MedFlowError as error:
            NotifyDialog.show(self.app, title="Could not update that diagnosis", message=error.message, tone="danger")
            return

        self._selected = self.container.patients.get(patient.patient_number, include_deleted=True)
        self._render_detail()
        self.set_status("Diagnosis resolved.")

    def _export(self) -> None:
        try:
            path = self.container.transfer.export_patients(
                self.container.settings.export_directory
                / f"patients-{self.container.clock.today()}.csv",
                actor=self._actor(),
                fmt="csv",
            )
        except MedFlowError as error:
            NotifyDialog.show(self.app, title="Export failed", message=error.message, tone="danger")
            return

        self.set_status(f"Exported to {path.name}.")
        NotifyDialog.show(
            self.app,
            title="Export complete",
            message=f"Patients were written to:\n{path}",
        )


def _status_colour(status: str) -> tuple[str, str]:
    if status == DiagnosisStatus.ACTIVE.value:
        return PALETTE.accent
    if status == DiagnosisStatus.RESOLVED.value:
        return PALETTE.success
    return PALETTE.text_muted
