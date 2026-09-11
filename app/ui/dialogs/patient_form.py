"""The patient form, used for both registration and editing.

One dialog serves both operations because the fields are identical and the
difference is a single call. Keeping them together means a new field is added once
and immediately works in both directions.

Validation is *not* implemented here. The dialog submits to
:class:`~app.services.patient_service.PatientService` and renders whatever
:class:`~app.core.exceptions.ValidationError` comes back. That way the rules live
in one place, cannot be bypassed, and a future web client inherits them unchanged —
this dialog is only responsible for showing them.
"""

from __future__ import annotations

from typing import Any, Callable

import customtkinter as ctk

from app.core.exceptions import MedFlowError, ValidationError
from app.domain.patient import Patient
from app.services.patient_service import PatientService
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
)

#: ``(key, label, placeholder, multiline)`` per field, in display order.
IDENTITY_FIELDS: tuple[tuple[str, str, str, bool], ...] = (
    ("first_name", "First name *", "e.g. Victor", False),
    ("last_name", "Last name", "e.g. Kamau", False),
    ("date_of_birth", "Date of birth", "YYYY-MM-DD", False),
    ("age_years", "Age", "Years", False),
    ("sex", "Sex", "As recorded", False),
)

CONTACT_FIELDS: tuple[tuple[str, str, str, bool], ...] = (
    ("phone", "Phone", "+254…", False),
    ("email", "Email", "name@example.com", False),
    ("address", "Address", "", True),
)

CLINICAL_FIELDS: tuple[tuple[str, str, str, bool], ...] = (
    ("blood_pressure", "Blood pressure", "120/80", False),
    ("heart_rate", "Heart rate", "Beats per minute", False),
    ("weight", "Weight", "", False),
    ("height", "Height", "", False),
    ("medical_history", "Medical history", "", True),
    ("notes", "Notes", "", True),
)


class PatientFormDialog(ctk.CTkToplevel):
    """Modal form for creating or editing a patient.

    After the dialog closes, ``saved_patient`` holds the created or updated record,
    or ``None`` if the user cancelled.
    """

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        *,
        service: PatientService,
        actor: str,
        patient: Patient | None = None,
        on_saved: Callable[[Patient], None] | None = None,
    ) -> None:
        super().__init__(master)

        self._service = service
        self._actor = actor
        self._patient = patient
        self._on_saved = on_saved
        self._editing = patient is not None

        self.saved_patient: Patient | None = None
        self._fields: dict[str, ctk.CTkEntry | ctk.CTkTextbox] = {}
        self._error_labels: dict[str, ctk.CTkLabel] = {}

        self.title(
            f"Edit {patient.patient_number}" if self._editing else "Register new patient"
        )
        self.geometry("760x720")
        self.minsize(680, 560)
        self.configure(fg_color=PALETTE.window)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_body()
        self._build_footer()

        if self._editing:
            self._populate(patient)

        # Modal: the rest of the application stays unreachable until this is
        # answered, so a half-finished edit cannot be left behind a click.
        self.transient(master)
        self.after(60, self._focus_and_grab)

    # ---------- construction ----------

    def _focus_and_grab(self) -> None:
        try:
            self.grab_set()
        except Exception:  # noqa: BLE001 - a lost grab must not break the dialog
            pass
        first = self._fields.get("first_name")
        if first is not None:
            first.focus_set()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=GAP_MD, pady=(GAP_MD, GAP_SM))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Edit patient record" if self._editing else "Register a new patient",
            font=FONT_HEADING,
            text_color=PALETTE.text,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        subtitle = (
            f"{self._patient.patient_number} · version {self._patient.record_version}"
            if self._editing and self._patient is not None
            else "The patient number is allocated automatically when you save."
        )
        ctk.CTkLabel(
            header,
            text=subtitle,
            font=FONT_TINY,
            text_color=PALETTE.text_muted,
            anchor="w",
        ).grid(row=1, column=0, sticky="w")

    def _build_body(self) -> None:
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=GAP_MD, pady=0)
        body.grid_columnconfigure(0, weight=1)

        row = 0
        row = self._add_group(body, "Identity", IDENTITY_FIELDS, row,
                              note="Date of birth is preferred. Age is kept for records "
                                   "migrated from the earlier version, which captured it "
                                   "as text with no birth date.")
        row = self._add_group(body, "Contact", CONTACT_FIELDS, row)

        fields = CLINICAL_FIELDS
        if not self._editing:
            # An opening diagnosis may be recorded at registration. Editing uses a
            # separate action, because a diagnosis is a row with its own history
            # rather than a field that gets overwritten.
            fields = CLINICAL_FIELDS + (("diagnosis", "Opening diagnosis", "", False),)

        row = self._add_group(body, "Clinical", fields, row)

    def _add_group(
        self,
        parent: ctk.CTkBaseClass,
        title: str,
        field_specs: tuple[tuple[str, str, str, bool], ...],
        row: int,
        *,
        note: str = "",
    ) -> int:
        card = ctk.CTkFrame(
            parent,
            fg_color=PALETTE.surface,
            corner_radius=RADIUS_MD,
            border_width=1,
            border_color=PALETTE.border,
        )
        card.grid(row=row, column=0, sticky="ew", pady=(0, GAP_SM))
        card.grid_columnconfigure(0, weight=1)
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card, text=title, font=FONT_BODY_BOLD, text_color=PALETTE.text, anchor="w"
        ).grid(row=0, column=0, columnspan=2, sticky="ew", padx=GAP_SM + GAP_XS,
               pady=(GAP_SM, GAP_XS))

        if note:
            ctk.CTkLabel(
                card,
                text=note,
                font=FONT_TINY,
                text_color=PALETTE.text_muted,
                anchor="w",
                justify="left",
                wraplength=600,
            ).grid(row=1, column=0, columnspan=2, sticky="ew", padx=GAP_SM + GAP_XS,
                   pady=(0, GAP_XS))

        # Multiline fields span the full width; short ones sit two to a row.
        grid_row = 2
        column = 0
        for key, label, placeholder, multiline in field_specs:
            span = 2 if multiline else 1
            if span == 2 and column == 1:
                grid_row += 1
                column = 0

            self._add_field(card, key, label, placeholder, multiline, grid_row, column, span)

            if span == 2:
                grid_row += 1
                column = 0
            else:
                column += 1
                if column > 1:
                    grid_row += 1
                    column = 0

        return row + 1

    def _add_field(
        self,
        parent: ctk.CTkBaseClass,
        key: str,
        label: str,
        placeholder: str,
        multiline: bool,
        row: int,
        column: int,
        span: int,
    ) -> None:
        wrapper = ctk.CTkFrame(parent, fg_color="transparent")
        wrapper.grid(
            row=row, column=column, columnspan=span, sticky="ew",
            padx=(GAP_SM, GAP_XS if span == 2 else GAP_SM), pady=(0, GAP_XS),
        )
        wrapper.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            wrapper, text=label, font=FONT_SMALL, text_color=PALETTE.text_muted, anchor="w"
        ).grid(row=0, column=0, sticky="w")

        if multiline:
            widget: ctk.CTkEntry | ctk.CTkTextbox = ctk.CTkTextbox(
                wrapper, height=78, font=FONT_BODY, corner_radius=RADIUS_MD
            )
        else:
            widget = ctk.CTkEntry(
                wrapper,
                placeholder_text=placeholder,
                font=FONT_BODY,
                height=34,
                corner_radius=RADIUS_MD,
            )
        widget.grid(row=1, column=0, sticky="ew")

        error = ctk.CTkLabel(
            wrapper, text="", font=FONT_TINY, text_color=PALETTE.danger, anchor="w"
        )
        error.grid(row=2, column=0, sticky="w")

        self._fields[key] = widget
        self._error_labels[key] = error

    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=GAP_MD, pady=(GAP_SM, GAP_MD))
        footer.grid_columnconfigure(0, weight=1)

        self._form_error = ctk.CTkLabel(
            footer,
            text="",
            font=FONT_SMALL,
            text_color=PALETTE.danger,
            anchor="w",
            justify="left",
            wraplength=420,
        )
        self._form_error.grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            footer,
            text="Cancel",
            command=self._cancel,
            width=96,
            height=36,
            font=FONT_BODY,
            fg_color="transparent",
            border_width=1,
            border_color=PALETTE.border,
            text_color=PALETTE.text,
            hover_color=PALETTE.surface_alt,
        ).grid(row=0, column=1, padx=(GAP_SM, GAP_XS))

        ctk.CTkButton(
            footer,
            text="Save changes" if self._editing else "Register patient",
            command=self._save,
            width=150,
            height=36,
            font=FONT_BODY_BOLD,
            fg_color=PALETTE.accent,
            hover_color=PALETTE.accent_hover,
            text_color=PALETTE.text_inverse,
        ).grid(row=0, column=2)

        self.bind("<Escape>", lambda _event: self._cancel())
        self.bind("<Control-Return>", lambda _event: self._save())

    # ---------- values ----------

    def _populate(self, patient: Patient) -> None:
        for key, value in patient.to_form_data().items():
            widget = self._fields.get(key)
            if widget is None or not value:
                continue
            if isinstance(widget, ctk.CTkTextbox):
                widget.insert("1.0", value)
            else:
                widget.insert(0, value)

    def _collect(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for key, widget in self._fields.items():
            if isinstance(widget, ctk.CTkTextbox):
                data[key] = widget.get("1.0", "end").strip()
            else:
                data[key] = widget.get().strip()
        return data

    def _clear_errors(self) -> None:
        for label in self._error_labels.values():
            label.configure(text="")
        self._form_error.configure(text="")

    def _show_errors(self, error: ValidationError) -> None:
        """Render per-field messages beside the offending inputs."""
        for field_name, message in error.errors.items():
            label = self._error_labels.get(field_name)
            if label is not None:
                label.configure(text=message)
            else:
                # A problem with no field of its own (or one the form does not
                # show) still has to be visible somewhere.
                current = self._form_error.cget("text")
                self._form_error.configure(
                    text=f"{current} {message}".strip()
                )

    # ---------- actions ----------

    def _save(self) -> None:
        self._clear_errors()
        data = self._collect()

        try:
            if self._editing and self._patient is not None:
                saved = self._service.update(
                    self._patient.patient_number, data, actor=self._actor
                )
            else:
                saved = self._service.create(data, actor=self._actor)
        except ValidationError as error:
            self._show_errors(error)
            return
        except MedFlowError as error:
            self._form_error.configure(text=error.message)
            return

        self.saved_patient = saved
        if self._on_saved is not None:
            self._on_saved(saved)
        self._close()

    def _cancel(self) -> None:
        self.saved_patient = None
        self._close()

    def _close(self) -> None:
        try:
            self.grab_release()
        except Exception:  # noqa: BLE001 - releasing a grab that is already gone is fine
            pass
        self.destroy()
