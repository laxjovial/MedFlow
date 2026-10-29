"""Import and architecture smoke tests for MedFlow's supported UI runtime.

The current launcher is root-level main.py -> AppController -> MainWindow.
Legacy modules remain import-tested during migration, but tests must not impose
the retired app.ui.app router's contract on the current view classes.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import pkgutil
from pathlib import Path

import pytest

import customtkinter as ctk
import main as launcher
from app.controller import AppController
from app.ui.main_window import MainWindow, NAV_ITEMS
from app.ui.theme import (
    ACCENT,
    F_BODY,
    FONT_BODY,
    FONT_BODY_BOLD,
    FONT_HEADING,
    FONT_METRIC,
    FONT_SMALL,
    FONT_TINY,
    FONT_TITLE,
    GAP_LG,
    GAP_MD,
    GAP_SM,
    GAP_XS,
    NAV_ITEMS as LEGACY_NAV_ITEMS,
    PALETTE,
    Palette,
    RADIUS_MD,
    SIDEBAR_WIDTH,
    STATUS_BAR_HEIGHT,
)


def iter_ui_modules():
    """Yield every dotted module name under app.ui, including packages."""
    package = importlib.import_module("app.ui")
    for info in pkgutil.walk_packages(package.__path__, prefix="app.ui."):
        yield info.name


class TestEveryModuleImports:
    def test_the_ui_package_contains_modules(self) -> None:
        assert len(list(iter_ui_modules())) >= 8

    @pytest.mark.parametrize("module_name", sorted(iter_ui_modules()))
    def test_module_imports_cleanly(self, module_name: str) -> None:
        assert importlib.import_module(module_name) is not None


class TestCanonicalRuntime:
    def test_root_launcher_exposes_desktop_and_server_modes(self) -> None:
        parser = launcher.build_parser()
        assert parser.parse_args([]).server is False
        assert parser.parse_args(["--server"]).server is True

    def test_controller_and_main_window_are_canonical(self) -> None:
        assert callable(AppController.run)
        assert issubclass(MainWindow, ctk.CTk)

    def test_navigation_matches_the_controller_registry(self) -> None:
        registry = AppController.view_registry.fget(None)
        nav_keys = {key for key, _label in NAV_ITEMS}
        assert nav_keys == set(registry)
        assert len(nav_keys) == len(NAV_ITEMS)

    def test_every_registered_view_is_a_customtkinter_frame(self) -> None:
        for key, view_class in AppController.view_registry.fget(None).items():
            assert issubclass(view_class, ctk.CTkFrame), key

    def test_legacy_navigation_alias_is_not_empty(self) -> None:
        assert LEGACY_NAV_ITEMS


class TestDialogs:
    def test_confirmation_and_notification_dialogs_use_class_methods(self) -> None:
        from app.ui.dialogs.confirm import ConfirmDialog, NotifyDialog

        assert isinstance(inspect.getattr_static(ConfirmDialog, "ask"), classmethod)
        assert isinstance(inspect.getattr_static(NotifyDialog, "show"), classmethod)

    def test_dialog_helpers_require_a_parent_window(self) -> None:
        from app.ui.dialogs.confirm import ConfirmDialog, NotifyDialog

        for owner, name in ((ConfirmDialog, "ask"), (NotifyDialog, "show")):
            signature = inspect.signature(getattr(owner, name))
            first = next(iter(signature.parameters.values()))
            assert first.name == "master"
            assert first.default is inspect.Parameter.empty
            assert first.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD

    def test_text_prompt_is_opened_through_a_class_method(self) -> None:
        from app.ui.dialogs.prompt import TextPromptDialog

        assert isinstance(inspect.getattr_static(TextPromptDialog, "ask"), classmethod)

    def test_every_legacy_dialog_is_a_toplevel(self) -> None:
        from app.ui.dialogs.confirm import ConfirmDialog, NotifyDialog
        from app.ui.dialogs.patient_form import PatientFormDialog
        from app.ui.dialogs.prompt import TextPromptDialog

        for dialog in (ConfirmDialog, NotifyDialog, TextPromptDialog, PatientFormDialog):
            assert issubclass(dialog, ctk.CTkToplevel), dialog.__name__

    def test_patient_form_depends_on_service_not_repository(self) -> None:
        from app.ui.dialogs.patient_form import PatientFormDialog

        parameters = inspect.signature(PatientFormDialog.__init__).parameters
        assert "service" in parameters
        assert not any("repository" in name for name in parameters)


class TestTheme:
    def test_palette_is_a_frozen_dataclass(self) -> None:
        assert dataclasses.is_dataclass(Palette)
        assert Palette.__dataclass_params__.frozen

    def test_every_palette_field_is_a_light_dark_pair(self) -> None:
        for field in dataclasses.fields(Palette):
            value = field.default
            assert isinstance(value, tuple) and len(value) == 2, field.name
            assert all(isinstance(part, str) and part for part in value), field.name

    def test_legacy_theme_tokens_are_consistent_with_current_tokens(self) -> None:
        assert FONT_BODY == F_BODY
        assert FONT_BODY_BOLD[0] == FONT_HEADING[0] == FONT_TITLE[0]
        assert FONT_SMALL[0] == FONT_TINY[0] == FONT_METRIC[0]
        assert all(value > 0 for value in (
            GAP_XS, GAP_SM, GAP_MD, GAP_LG, RADIUS_MD,
            SIDEBAR_WIDTH, STATUS_BAR_HEIGHT,
        ))
        assert PALETTE.accent[0] == ACCENT


class TestLayering:
    """Presentation modules must not bypass services and reach into storage."""

    UI_MODULES = tuple(iter_ui_modules())

    def _source(self, module_name: str) -> str:
        module = importlib.import_module(module_name)
        path = getattr(module, "__file__", None)
        return Path(path).read_text(encoding="utf-8") if path else ""

    @pytest.mark.parametrize("module_name", sorted(UI_MODULES))
    def test_no_ui_module_imports_sqlite_directly(self, module_name: str) -> None:
        source = self._source(module_name)
        assert "import sqlite3" not in source
        assert "from sqlite3" not in source

    @pytest.mark.parametrize("module_name", sorted(UI_MODULES))
    def test_no_ui_module_imports_concrete_repository_packages(self, module_name: str) -> None:
        source = self._source(module_name)
        assert "app.repositories.sqlite" not in source
        assert "from app.storage.repositories" not in source
