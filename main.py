import customtkinter as ctk
from tkinter import messagebox
from database import PatientDatabase


class AddPatientDialog(ctk.CTkToplevel):
    def __init__(self, parent, on_saved):
        super().__init__(parent)
        self.on_saved = on_saved

        self.title("New Patient")
        self.geometry("520x650")
        self.minsize(480, 600)
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=30, pady=(25, 10))

        ctk.CTkLabel(
            header,
            text="Create Medical Record",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(anchor="w")

        ctk.CTkLabel(
            header,
            text="Enter the patient's information below.",
            text_color=("gray40", "gray70"),
        ).pack(anchor="w", pady=(4, 0))

        form = ctk.CTkScrollableFrame(self, corner_radius=12)
        form.grid(row=1, column=0, sticky="nsew", padx=25, pady=10)
        form.grid_columnconfigure(0, weight=1)

        self.entries = {}

        self._add_entry(form, "Full Name", "name", 0)
        self._add_entry(form, "Age", "age", 1)
        self._add_entry(form, "Blood Pressure", "bp", 2)
        self._add_entry(form, "Heart Rate", "hr", 3)

        ctk.CTkLabel(
            form, text="Medical History", anchor="w",
            font=ctk.CTkFont(weight="bold")
        ).grid(row=4, column=0, sticky="ew", pady=(15, 5))

        self.history = ctk.CTkTextbox(form, height=110)
        self.history.grid(row=5, column=0, sticky="ew", pady=(0, 8))

        ctk.CTkLabel(
            form, text="Diagnosis", anchor="w",
            font=ctk.CTkFont(weight="bold")
        ).grid(row=6, column=0, sticky="ew", pady=(15, 5))

        self.diagnosis = ctk.CTkTextbox(form, height=130)
        self.diagnosis.grid(row=7, column=0, sticky="ew", pady=(0, 15))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="ew", padx=25, pady=(5, 25))
        buttons.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            buttons, text="Cancel", fg_color="transparent",
            border_width=1, command=self.destroy
        ).grid(row=0, column=0, sticky="ew", padx=(0, 6))

        ctk.CTkButton(
            buttons, text="Save Patient", command=self.save
        ).grid(row=0, column=1, sticky="ew", padx=(6, 0))

    def _add_entry(self, parent, label, key, row):
        ctk.CTkLabel(
            parent, text=label, anchor="w",
            font=ctk.CTkFont(weight="bold")
        ).grid(row=row * 2, column=0, sticky="ew", pady=(10, 5))

        entry = ctk.CTkEntry(parent, height=38, placeholder_text=f"Enter {label.lower()}")
        entry.grid(row=row * 2 + 1, column=0, sticky="ew")
        self.entries[key] = entry

    def save(self):
        name = self.entries["name"].get().strip()

        if not name:
            messagebox.showerror(
                "Missing information",
                "Full Name is required.",
                parent=self,
            )
            return

        patient = {
            "name": name,
            "age": self.entries["age"].get().strip() or "--",
            "bp": self.entries["bp"].get().strip() or "--",
            "hr": self.entries["hr"].get().strip() or "--",
            "history": self.history.get("1.0", "end").strip() or "None stated",
            "diag": self.diagnosis.get("1.0", "end").strip() or "Awaiting screening",
        }

        try:
            patient_id = self.on_saved(patient)
            messagebox.showinfo(
                "Patient registered",
                f"{patient_id} has been successfully registered.",
                parent=self,
            )
            self.destroy()
        except Exception as exc:
            messagebox.showerror("Could not save patient", str(exc), parent=self)


class PatientApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.db = PatientDatabase()

        self.title("MedFlow — Patient Management System")
        self.geometry("1180x720")
        self.minsize(950, 620)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.selected_patient_id = None

        self._build_sidebar()
        self._build_main_panel()
        self._build_status_bar()

        self.refresh_patient_list()

    # ---------- UI ----------

    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=300, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        ctk.CTkLabel(
            self.sidebar,
            text="MEDFLOW",
            font=ctk.CTkFont(size=25, weight="bold"),
        ).pack(anchor="w", padx=25, pady=(30, 2))

        ctk.CTkLabel(
            self.sidebar,
            text="Patient Management System",
            text_color=("gray40", "gray70"),
        ).pack(anchor="w", padx=25, pady=(0, 25))

        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.refresh_patient_list())

        self.search = ctk.CTkEntry(
            self.sidebar,
            height=40,
            textvariable=self.search_var,
            placeholder_text="Search name or patient ID...",
        )
        self.search.pack(fill="x", padx=20, pady=(0, 15))

        self.patient_list = ctk.CTkScrollableFrame(
            self.sidebar,
            label_text="PATIENTS",
            corner_radius=10,
        )
        self.patient_list.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        ctk.CTkButton(
            self.sidebar,
            text="+  Add New Patient",
            height=42,
            command=self.open_add_patient,
        ).pack(fill="x", padx=20, pady=(0, 25))

    def _build_main_panel(self):
        self.main = ctk.CTkFrame(self, corner_radius=0, fg_color=("gray95", "gray10"))
        self.main.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(self.main, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=35, pady=(30, 15))
        top.grid_columnconfigure(0, weight=1)

        self.page_title = ctk.CTkLabel(
            top,
            text="Patient Dashboard",
            font=ctk.CTkFont(size=28, weight="bold"),
        )
        self.page_title.grid(row=0, column=0, sticky="w")

        self.theme_button = ctk.CTkButton(
            top,
            text="Toggle Theme",
            width=120,
            command=self.toggle_theme,
        )
        self.theme_button.grid(row=0, column=1, padx=(15, 0))

        self.stats = ctk.CTkFrame(self.main, corner_radius=12)
        self.stats.grid(row=1, column=0, sticky="ew", padx=35, pady=(0, 20))
        self.stats.grid_columnconfigure((0, 1, 2), weight=1)

        self.total_value = self._stat_card(self.stats, "TOTAL PATIENTS", 0)
        self.active_value = self._stat_card(self.stats, "SELECTED RECORD", 1)
        self.storage_value = self._stat_card(self.stats, "STORAGE", 2)

        self.details = ctk.CTkScrollableFrame(
            self.main,
            corner_radius=15,
            label_text="PATIENT PROFILE",
        )
        self.details.grid(row=2, column=0, sticky="nsew", padx=35, pady=(0, 25))
        self.details.grid_columnconfigure(1, weight=1)

        self._show_empty_state()

    def _stat_card(self, parent, title, column):
        card = ctk.CTkFrame(parent, corner_radius=10)
        card.grid(row=0, column=column, sticky="ew", padx=8, pady=8)

        ctk.CTkLabel(
            card, text=title,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray45", "gray65"),
        ).pack(anchor="w", padx=15, pady=(12, 0))

        value = ctk.CTkLabel(
            card, text="—",
            font=ctk.CTkFont(size=21, weight="bold"),
        )
        value.pack(anchor="w", padx=15, pady=(2, 12))

        return value

    def _build_status_bar(self):
        self.status = ctk.CTkLabel(
            self,
            text="Status: System ready",
            anchor="w",
            height=30,
            fg_color=("gray88", "gray15"),
        )
        self.status.grid(row=1, column=0, columnspan=2, sticky="ew")

    def _show_empty_state(self):
        self._clear_details()

        ctk.CTkLabel(
            self.details,
            text="Select a patient",
            font=ctk.CTkFont(size=26, weight="bold"),
        ).grid(row=0, column=0, columnspan=2, pady=(80, 5))

        ctk.CTkLabel(
            self.details,
            text="Choose a record from the directory or create a new patient.",
            text_color=("gray45", "gray65"),
        ).grid(row=1, column=0, columnspan=2)

    def _clear_details(self):
        for widget in self.details.winfo_children():
            widget.destroy()

    # ---------- Patient operations ----------

    def refresh_patient_list(self):
        for widget in self.patient_list.winfo_children():
            widget.destroy()

        query = self.search_var.get().strip()

        patients = self.db.search_patients(query)

        self.total_value.configure(text=str(self.db.count_patients()))

        if not patients:
            ctk.CTkLabel(
                self.patient_list,
                text="No matching patients.",
                text_color=("gray45", "gray65"),
            ).pack(pady=25)
            return

        for patient in patients:
            selected = patient["patient_id"] == self.selected_patient_id

            button = ctk.CTkButton(
                self.patient_list,
                text=f'{patient["patient_id"]}\n{patient["name"]}',
                anchor="w",
                height=58,
                fg_color=("gray82", "gray20") if selected else "transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray75", "gray25"),
                command=lambda pid=patient["patient_id"]: self.show_patient(pid),
            )
            button.pack(fill="x", pady=3)

    def show_patient(self, patient_id):
        patient = self.db.get_patient(patient_id)

        if not patient:
            return

        self.selected_patient_id = patient_id
        self.active_value.configure(text=patient_id)
        self.storage_value.configure(text="SQLite")

        self._clear_details()

        self.details.grid_columnconfigure(0, weight=0)
        self.details.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self.details,
            text=patient["name"],
            font=ctk.CTkFont(size=27, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(15, 2))

        ctk.CTkLabel(
            self.details,
            text=patient_id,
            text_color=("gray45", "gray65"),
        ).grid(row=1, column=0, sticky="w", padx=20, pady=(0, 25))

        info = [
            ("Age", patient["age"]),
            ("Blood Pressure", patient["bp"]),
            ("Heart Rate", patient["hr"]),
        ]

        for row, (label, value) in enumerate(info, start=2):
            ctk.CTkLabel(
                self.details, text=label,
                font=ctk.CTkFont(weight="bold"),
            ).grid(row=row, column=0, sticky="w", padx=20, pady=8)

            ctk.CTkLabel(
                self.details, text=value, anchor="w",
            ).grid(row=row, column=1, sticky="ew", padx=20, pady=8)

        history_row = 5

        ctk.CTkLabel(
            self.details, text="Medical History",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=history_row, column=0, columnspan=2, sticky="w", padx=20, pady=(25, 6))

        history_box = ctk.CTkTextbox(self.details, height=120)
        history_box.grid(row=history_row + 1, column=0, columnspan=2, sticky="ew", padx=20)
        history_box.insert("1.0", patient["history"])
        history_box.configure(state="disabled")

        diagnosis_row = 7

        ctk.CTkLabel(
            self.details, text="Current Diagnosis",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=diagnosis_row, column=0, columnspan=2, sticky="w", padx=20, pady=(25, 6))

        diagnosis_box = ctk.CTkTextbox(self.details, height=120)
        diagnosis_box.grid(row=diagnosis_row + 1, column=0, columnspan=2, sticky="ew", padx=20)
        diagnosis_box.insert("1.0", patient["diag"])
        diagnosis_box.configure(state="disabled")

        actions = ctk.CTkFrame(self.details, fg_color="transparent")
        actions.grid(row=9, column=0, columnspan=2, sticky="ew", padx=20, pady=25)
        actions.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            actions, text="Refresh Record",
            command=lambda: self.show_patient(patient_id),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 6))

        ctk.CTkButton(
            actions, text="Delete Patient",
            fg_color="#b42318",
            hover_color="#8f1c13",
            command=lambda: self.delete_patient(patient_id),
        ).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.status.configure(text=f'Status: Displaying {patient_id} — {patient["name"]}')
        self.refresh_patient_list()

    def open_add_patient(self):
        AddPatientDialog(self, self.add_patient)

    def add_patient(self, patient):
        patient_id = self.db.add_patient(patient)
        self.selected_patient_id = patient_id
        self.refresh_patient_list()
        self.show_patient(patient_id)
        self.status.configure(text=f"Status: Successfully registered {patient_id}")
        return patient_id

    def delete_patient(self, patient_id):
        patient = self.db.get_patient(patient_id)

        if not patient:
            return

        confirmed = messagebox.askyesno(
            "Delete Patient",
            f'Are you sure you want to permanently delete\n\n'
            f'{patient_id} — {patient["name"]}?\n\n'
            f'This action cannot be undone.',
            parent=self,
        )

        if not confirmed:
            return

        self.db.delete_patient(patient_id)
        self.selected_patient_id = None
        self.active_value.configure(text="—")
        self.storage_value.configure(text="SQLite")
        self._show_empty_state()
        self.refresh_patient_list()
        self.status.configure(text=f"Status: {patient_id} deleted successfully")

    def toggle_theme(self):
        current = ctk.get_appearance_mode()

        if current == "Dark":
            ctk.set_appearance_mode("Light")
        else:
            ctk.set_appearance_mode("Dark")


if __name__ == "__main__":
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    app = PatientApp()
    app.mainloop()
