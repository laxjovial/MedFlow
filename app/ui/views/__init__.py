"""Desktop views, one module per screen."""

from app.ui.views.activity import ActivityView
from app.ui.views.appointments import AppointmentsView
from app.ui.views.dashboard import DashboardView
from app.ui.views.patients import PatientsView
from app.ui.views.reports import ReportsView
from app.ui.views.settings import SettingsView

__all__ = [
    "ActivityView",
    "AppointmentsView",
    "DashboardView",
    "PatientsView",
    "ReportsView",
    "SettingsView",
]
