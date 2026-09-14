"""Demo data for a fresh installation.

Seeding is opt-in (``database.seed_demo_data``) and only ever runs against a
database that holds no patients at all, deleted ones included. It exists so a new
user sees a populated interface instead of an empty one — it is never a migration
step, and it never touches a database that already holds real data.

Demo records are created through :class:`~app.services.patient_service.PatientService`
rather than by writing rows directly, so a seeded record is a *normal* record: it
has a patient number from the same counter, a timeline entry and an audit trail.
Seeding by a back door would produce records that behave differently from every
other one in the database.
"""

from __future__ import annotations

from app.config.constants import SYSTEM_ACTOR
from app.services.patient_service import PatientService

#: Deliberately obviously-fictional people. Nothing here resembles a real record,
#: and it is only ever written to a database the user has not put data in.
DEMO_PATIENTS: tuple[dict[str, object], ...] = (
    {
        "first_name": "John",
        "last_name": "Doe",
        "date_of_birth": "1979-04-12",
        "sex": "male",
        "phone": "+254700000001",
        "email": "john.doe@example.com",
        "address": "12 Riverside Drive, Nairobi",
        "blood_pressure": "128/84",
        "heart_rate": "76",
        "weight": "81",
        "height": "178",
        "medical_history": "Hypertension diagnosed 2019. No known drug allergies.",
        "notes": "Reviewed annually. Responding well to current medication.",
        "diagnoses": ("Essential hypertension",),
    },
    {
        "first_name": "Alice",
        "last_name": "Smith",
        "date_of_birth": "1992-11-03",
        "sex": "female",
        "phone": "+254700000002",
        "email": "alice.smith@example.com",
        "address": "48 Kenyatta Avenue, Nakuru",
        "blood_pressure": "112/72",
        "heart_rate": "68",
        "weight": "64",
        "height": "165",
        "medical_history": "Mild seasonal asthma. Uses a salbutamol inhaler as needed.",
        "notes": "Inhaler technique reviewed; no change required.",
        "diagnoses": ("Mild persistent asthma",),
    },
    {
        "first_name": "Victor",
        "last_name": "Kamau",
        "date_of_birth": "1965-02-27",
        "sex": "male",
        "phone": "+254700000003",
        "email": "victor.kamau@example.com",
        "address": "7 Moi Road, Mombasa",
        "blood_pressure": "142/90",
        "heart_rate": "82",
        "weight": "88",
        "height": "172",
        "medical_history": "Type 2 diabetes since 2014. Hypertension since 2016.",
        "notes": "Quarterly review. Discussed diet and exercise at last visit.",
        # Two diagnoses, so the dashboard chart and the diagnoses tab both have
        # something with more than one bar to show.
        "diagnoses": ("Type 2 diabetes mellitus", "Essential hypertension"),
    },
)


def is_empty(service: PatientService) -> bool:
    """Report whether the database holds no patients at all.

    Deleted patients are counted too, so seeding never mistakes a register emptied
    by deletion for a brand-new one and resurrects demo data into it.
    """
    return service.count(include_deleted=True) == 0


def seed(service: PatientService, *, actor: str = SYSTEM_ACTOR) -> int:
    """Create the demo patients, returning how many were made.

    Does nothing when patients already exist, so it is safe to call on every start.
    """
    if not is_empty(service):
        return 0

    created = 0

    for spec in DEMO_PATIENTS:
        payload = {key: value for key, value in spec.items() if key != "diagnoses"}

        diagnoses = spec.get("diagnoses", ())
        assert isinstance(diagnoses, tuple)
        if diagnoses:
            # The first is supplied with registration; the rest are added after,
            # because the form records one opening diagnosis rather than several.
            payload["diagnosis"] = diagnoses[0]

        patient = service.create(payload, actor=actor)

        for text in diagnoses[1:]:
            service.add_diagnosis(patient.patient_number, str(text), actor=actor)

        created += 1

    return created
