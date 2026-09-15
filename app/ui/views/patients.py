"""Patients view: directory, registration, editing, and the chart workspace."""

from __future__ import annotations

import customtkinter as ctk

from app.ui.components import EmptyState, FormDialog, FormField, Section, Toolbar
from app.ui.theme import DANGER, F_BODY, F_SMALL, MUTED
from app.utils.dates import humanize

SEX_OPTIONS = ("female", "male", "other")

PATIENT_FIELDS = [
    FormField("name", "Full name", required=True),
    FormField("age", "Age", placeholder="years"),
    FormField("sex", "Sex", kind="option", options=("", *SEX_OPTIONS)),
    FormField("date_of_birth", "Date of birth", placeholder="YYYY-MM-DD"),
    FormField("phone", "Phone"),
    FormField("email", "Email"),
    FormField("blood_pressure", "Blood pressure", placeholder="e.g. 120/80"),
    FormField("heart_rate", "Heart rate", placeholder="bpm"),
    FormField("weight", "Weight", placeholder="kg"),
    FormField("medical_history", "Medical history", kind="textbox", rows=4),
    FormField("diagnosis", "Working diagnosis", kind="textbox", rows=3),
    FormField("notes", "Notes", kind="textbox", rows=3),
]


def patient_fields(departments: tuple = ()) -> list[FormField]:
    """Patient form plus the facility's live department list."""
    return [*PATIENT_FIELDS,
            FormField("department", "Department", kind="option",
                      options=("", *departments))]


class PatientsView(ctk.CTkFrame):
    def __init__(self, master, app, open_new: bool = False):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.current_id: int | None = None

        self.toolbar = Toolbar(self, "Search by name, number, phone or diagnosis…",
                               on_search=self._on_search,
                               button_text="＋  New patient",
                               on_button=self._new_patient)
        self.toolbar.pack(fill="x", padx=24, pady=(20, 10))

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=24, pady=(0, 20))
        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_columnconfigure(1, weight=2)
        self.body.grid_rowconfigure(0, weight=1)

        self.list_card = Section(self.body, "Directory")
        self.list_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.rows = ctk.CTkScrollableFrame(self.list_card, fg_color="transparent")
        self.rows.grid(row=1, column=0, sticky="nsew", padx=8, pady=(2, 10))
        self.list_card.grid_rowconfigure(1, weight=1)

        self.chart_area = Section(self.body, "Patient record")
        self.chart_area.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self.chart_slot = ctk.CTkFrame(self.chart_area, fg_color="transparent")
        self.chart_slot.grid(row=1, column=0, sticky="nsew", padx=8, pady=(2, 10))
        self.chart_area.grid_rowconfigure(1, weight=1)

        self.refresh_list()
        if open_new:
            self.after(120, self._new_patient)

    # ------------------------------------------------------------------ #
    # directory

    def _on_search(self, query: str) -> None:
        self.refresh_list(query)

    def refresh_list(self, query: str = "") -> None:
        for w in self.rows.winfo_children():
            w.destroy()
        summaries = self.app.patients.search(query)
        if not summaries:
            EmptyState(self.rows, "🔍", "No matching patients",
                       "Try another search or register a new patient.")
            return
        for s in summaries:
            card = ctk.CTkButton(
                self.rows, anchor="w", font=F_BODY, height=54,
                corner_radius=9,
                fg_color="#FFFFFF", hover_color="#E6F4F2",
                text_color="#16283C",
                text=f"  {s.patient_number}   {s.name}"
                     f"{'   ·   ' + str(s.age) + 'y' if s.age else ''}"
                     f"{'   ·   ' + s.diagnosis[:28] if s.diagnosis else ''}",
                command=lambda pid=s.patient_id: self.open_chart(pid))
            card.pack(fill="x", pady=3)

    # ------------------------------------------------------------------ #
    # record (chart)

    def open_chart(self, patient_id: int) -> None:
        try:
            chart = self.app.patients.chart(patient_id)
        except Exception as exc:
            self.app.toast(str(exc), "error")
            return
        self.current_id = patient_id

        for w in self.chart_slot.winfo_children():
            w.destroy()

        patient = chart["patient"]
        head = ctk.CTkFrame(self.chart_slot, fg_color="transparent")
        head.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(head, text=patient.name,
                     font=("Segoe UI", 20, "bold")).pack(side="left")
        dept_label = ""
        if patient.origin_unit_id:
            dept_label = next((f"  ·  {u.name}" for u in self.app.org.list_units()
                               if u.unit_id == patient.origin_unit_id), "")
        ctk.CTkLabel(head, text=f"  {patient.patient_number}  ·  "
                                f"{self.app.age_display(patient)}  ·  "
                                f"{patient.sex or 'sex n/a'}{dept_label}",
                     font=F_SMALL, text_color=MUTED).pack(side="left")
        updated_label = humanize(patient.updated_at.isoformat()
                                 if patient.updated_at else None)
        ctk.CTkLabel(head, text=f"updated {updated_label}",
                     font=F_SMALL, text_color=MUTED).pack(side="right")

        buttons = ctk.CTkFrame(head, fg_color="transparent")
        buttons.pack(side="right", padx=10)
        if "patients.edit" in self.app.permissions:
            ctk.CTkButton(buttons, text="Edit", font=F_SMALL, height=28,
                          fg_color="transparent", border_width=1,
                          border_color="#DFE7F0", text_color="#16283C",
                          command=self._edit_patient).pack(side="left", padx=3)
        if "export.data" in self.app.permissions:
            ctk.CTkButton(buttons, text="Print", font=F_SMALL, height=28,
                          fg_color="transparent", border_width=1,
                          border_color="#DFE7F0", text_color="#16283C",
                          command=self._print_chart).pack(side="left", padx=3)
        if "patients.delete" in self.app.permissions:
            ctk.CTkButton(buttons, text="Delete", font=F_SMALL, height=28,
                          fg_color="#FDECEA", hover_color="#F8D7D4",
                          text_color=DANGER,
                          command=self._delete_patient).pack(side="left", padx=3)

        chart_scroll = ctk.CTkScrollableFrame(self.chart_slot,
                                              fg_color="transparent")
        chart_scroll.pack(fill="both", expand=True)
        self._chart_section(chart_scroll, "Allergies", "allergies", self.app.records,
                            [("substance", "Substance"), ("reaction", "Reaction")],
                            renderer=lambda a: f"{a.substance} — {a.reaction or 'reaction unspecified'} "
                                               f"({a.severity})",
                            rows=chart["allergies"])
        self._chart_section(chart_scroll, "Diagnoses", "diagnoses", self.app.records,
                            [("description", "Diagnosis"), ("code", "Code (ICD)")],
                            renderer=lambda d: f"{d.description} ({d.status})",
                            rows=chart["diagnoses"])
        self._chart_section(chart_scroll, "Medications", "medications", self.app.records,
                            [("name", "Medication"), ("dose", "Dose"),
                             ("frequency", "Frequency")],
                            renderer=lambda m: f"{m.name} {m.dose or ''} {m.frequency or ''} "
                                               f"({m.status})",
                            rows=chart["medications"])
        self._chart_section(chart_scroll, "Vitals", "vitals", self.app.records,
                            [("blood_pressure", "BP"), ("heart_rate", "HR"),
                             ("temperature_c", "Temp °C"),
                             ("oxygen_saturation", "SpO₂ %")],
                            renderer=lambda v: f"{humanize(v.recorded_at.isoformat() if v.recorded_at else None)} — "
                                               f"BP {v.blood_pressure or '—'} · HR {v.heart_rate or '—'} · "
                                               f"{v.temperature_c or '—'}°C · SpO₂ {v.oxygen_saturation or '—'}%",
                            rows=chart["vitals"])
        self._chart_section(chart_scroll, "Lab results", "lab_results", self.app.records,
                            [("panel", "Panel"), ("analyte", "Analyte"),
                             ("value", "Value"), ("unit", "Unit")],
                            renderer=lambda l: f"{l.panel} · {l.analyte}: {l.value or '—'} "
                                               f"{l.unit or ''} [{l.flag}]",
                            rows=chart["lab_results"])
        self._chart_section(chart_scroll, "Notes", "notes", self.app.records,
                            [("body", "Note")],
                            renderer=lambda n: f"{humanize(n.created_at.isoformat() if n.created_at else None)} "
                                               f"({n.category}) — {n.body}",
                            rows=chart["notes"])

        timeline = ctk.CTkFrame(chart_scroll, fg_color="transparent")
        timeline.pack(fill="x", pady=(10, 6))
        ctk.CTkLabel(timeline, text="CLINICAL TIMELINE", font=("Segoe UI", 12, "bold"),
                     text_color=MUTED, anchor="w").pack(fill="x")
        for t in chart["timeline"][:30]:
            ctk.CTkLabel(timeline, text=f"•  {humanize(t.created_at.isoformat() if t.created_at else None)} — "
                                        f"{t.description}",
                         font=F_SMALL, anchor="w", wraplength=520,
                         justify="left").pack(fill="x", pady=1)

    # ------------------------------------------------------------------ #
    # chart sections

    def _chart_section(self, parent, title, section, service, inputs,
                       renderer, rows) -> None:
        box = Section(parent, title)
        box.pack(fill="x", pady=(8, 0))

        listing = ctk.CTkFrame(box, fg_color="transparent")
        listing.grid(row=1, column=0, sticky="ew", padx=12)
        if not rows:
            ctk.CTkLabel(listing, text="Nothing recorded yet", font=F_SMALL,
                         text_color=MUTED, anchor="w").pack(fill="x", pady=2)
        for item in rows:
            ctk.CTkLabel(listing, text=renderer(item), font=F_BODY,
                         anchor="w", wraplength=520,
                         justify="left").pack(fill="x", pady=1)

        if "records.edit" not in self.app.permissions:
            return
        entry_row = ctk.CTkFrame(box, fg_color="transparent")
        entry_row.grid(row=2, column=0, sticky="ew", padx=12, pady=(6, 12))
        widgets = {}
        for key, label in inputs:
            entry = ctk.CTkEntry(entry_row, placeholder_text=label,
                                 font=F_SMALL, width=120, height=32)
            entry.pack(side="left", padx=(0, 6))
            widgets[key] = entry

        def add():
            data = {k: w.get().strip() for k, w in widgets.items()}
            try:
                if section == "allergies":
                    self.app.records.add_allergy(self.current_id, **{
                        "substance": data["substance"],
                        "reaction": data.get("reaction") or None})
                elif section == "diagnoses":
                    self.app.records.add_diagnosis(self.current_id,
                                                   data["description"],
                                                   code=data.get("code") or None)
                elif section == "medications":
                    self.app.records.add_medication(self.current_id, data["name"],
                                                    dose=data.get("dose") or None,
                                                    frequency=data.get("frequency") or None)
                elif section == "vitals":
                    self.app.records.add_vitals(self.current_id, data)
                elif section == "lab_results":
                    self.app.records.add_lab_result(self.current_id, data["panel"],
                                                    data["analyte"],
                                                    value=data.get("value") or None,
                                                    unit=data.get("unit") or None)
                elif section == "notes":
                    self.app.records.add_note(self.current_id, data["body"])
            except Exception as exc:
                self.app.toast(str(exc), "error")
                return
            self.open_chart(self.current_id)

        ctk.CTkButton(entry_row, text="Add", font=F_SMALL, height=32,
                      width=70, command=add).pack(side="left")

    # ------------------------------------------------------------------ #
    # record actions

    def _departments(self) -> tuple:
        try:
            return tuple(u.name for u in self.app.org.list_units()
                         if u.kind != "organization")
        except Exception:
            return ()

    def _new_patient(self) -> None:
        FormDialog(self, "Register patient", patient_fields(self._departments()),
                   self._submit_new, submit_text="Register")

    def _submit_new(self, values: dict) -> None:
        patient = self.app.patients.register(values)
        self.app.toast(f"Registered {patient.patient_number} — {patient.name}", "ok")
        self.refresh_list()
        self.after(150, lambda: self.open_chart(patient.patient_id))

    def _edit_patient(self) -> None:
        patient = self.app.patients.get(self.current_id)
        dept_name = ""
        if patient.origin_unit_id:
            unit = self.app.org.list_units()
            dept_name = next((u.name for u in unit
                              if u.unit_id == patient.origin_unit_id), "")
        values = {
            "name": patient.name, "age": patient.age, "sex": patient.sex or "",
            "date_of_birth": patient.date_of_birth.isoformat()
            if patient.date_of_birth else "", "phone": patient.phone or "",
            "email": patient.email or "", "blood_pressure": patient.blood_pressure or "",
            "heart_rate": patient.heart_rate, "weight": patient.weight,
            "medical_history": patient.medical_history or "",
            "diagnosis": patient.diagnosis or "", "notes": patient.notes or "",
            "department": dept_name,
        }
        FormDialog(self, f"Edit — {patient.name}", patient_fields(self._departments()),
                   self._submit_edit, values=values, submit_text="Save changes")

    def _submit_edit(self, values: dict) -> None:
        self.app.patients.update(self.current_id, values)
        self.app.toast("Record updated", "ok")
        self.refresh_list()
        self.open_chart(self.current_id)

    def _delete_patient(self) -> None:
        patient = self.app.patients.get(self.current_id)
        if not self.app.confirm(
                "Delete patient",
                f"Soft-delete {patient.name} ({patient.patient_number})?\n"
                "The record can be restored from Settings → Recycle bin."):
            return
        self.app.patients.delete(self.current_id)
        self.app.toast("Record deleted", "ok")
        self.current_id = None
        for w in self.chart_slot.winfo_children():
            w.destroy()
        self.refresh_list()

    def _print_chart(self) -> None:
        self.app.print_chart(self.current_id)
