"""Import-level smoke tests for the UI.

The GUI cannot be driven in a headless environment, so these tests do not click
anything. What they do check is the thing that actually breaks the application on
start: a module that fails to import, a class that no longer exists after a
rename, a view that is registered in the router but never defined, or a theme
token referenced under a name that was changed.

``from app.ui.app import MedFlowApp`` is the test — it imports every view, every
dialog and every widget in the package, so a single broken import anywhere in the
UI fails here rather than in front of a user.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest

#: Importing this pulls in the whole UI package.
from app.ui import app as app_module
from app.ui.app import DEFAULT_VIEW, VIEW_CLASSES, MedFlowApp, build_application
from app.ui.theme import NAV_ITEMS, STATUS_BAR_HEIGHT, SIDEBAR_WIDTH, Palette
from app.ui.views.base import View


def iter_ui_modules():
    """Yield the dotted name of every module in ``app.ui``."""
    package = importlib.import_module("app.ui")
    for info in pkgutil.walk_packages(package.__path__, prefix="app.ui."):
        yield info.name


class TestEveryModuleImports:
    def test_the_ui_package_contains_modules(self) -> None:
        # Guards the guard: if the walk silently found nothing, the test below
        # would pass while importing nothing at all.
        assert len(list(iter_ui_modules())) >= 8

    @pytest.mark.parametrize("module_name", sorted(iter_ui_modules()))
    def test_module_imports_cleanly(self, module_name: str) -> None:
        assert importlib.import_module(module_name) is not None


class TestTheRouter:
    def test_the_default_view_is_registered(self) -> None:
        # A default that is not in the table is a blank window on first launch.
        assert DEFAULT_VIEW in VIEW_CLASSES

    def test_every_navigation_item_has_a_view(self) -> None:
        missing = [key for key, _, _ in NAV_ITEMS if key not in VIEW_CLASSES]
        assert missing == []

    def test_every_registered_view_is_reachable_from_the_sidebar(self) -> None:
        # The reverse direction: a view that exists but cannot be reached is
        # either dead code or a forgotten menu entry.
        reachable = {key for key, _, _ in NAV_ITEMS}
        assert set(VIEW_CLASSES) <= reachable

    def test_every_view_class_is_a_view(self) -> None:
        for key, view_class in VIEW_CLASSES.items():
            assert issubclass(view_class, View), key

    def test_every_view_class_subclasses_customtkinter_through_view(self) -> None:
        import customtkinter as ctk

        for view_class in VIEW_CLASSES.values():
            assert issubclass(view_class, ctk.CTkFrame)

    def test_navigation_items_carry_a_label_and_a_glyph(self) -> None:
        for key, label, glyph in NAV_ITEMS:
            assert key and label and glyph, key
            assert label == label.strip()


class TestViewContract:
    def test_every_view_defines_a_title(self) -> None:
        for key, view_class in VIEW_CLASSES.items():
            assert view_class.title, key

    def test_every_view_overrides_build(self) -> None:
        # The shell calls build() then on_show(). A view that inherits the base
        # build() would render nothing, which looks like a hang.
        for key, view_class in VIEW_CLASSES.items():
            assert view_class.build is not View.build, key

    def test_optional_hooks_keep_the_base_signature(self) -> None:
        for view_class in VIEW_CLASSES.values():
            for hook in ("build", "on_show", "on_hide"):
                method = getattr(view_class, hook)
                assert callable(method)
                assert list(inspect.signature(method).parameters) == ["self"], (
                    f"{view_class.__name__}.{hook}"
                )


class TestDialogs:
    def test_the_confirm_dialog_is_opened_through_a_class_method(self) -> None:
        from app.ui.dialogs.confirm import ConfirmDialog, NotifyDialog

        # Class methods rather than functions so a subclass inherits the behaviour,
        # and so the call site reads as the dialog it opens.
        assert isinstance(inspect.getattr_static(ConfirmDialog, "ask"), classmethod)
        assert isinstance(inspect.getattr_static(NotifyDialog, "show"), classmethod)

    def test_the_confirm_dialogs_take_the_parent_window_first(self) -> None:
        # They are modal over a parent, so the master is required and cannot be
        # inferred — passing it is what makes them centre correctly.
        from app.ui.dialogs.confirm import ConfirmDialog, NotifyDialog

        for owner, name in ((ConfirmDialog, "ask"), (NotifyDialog, "show")):
            signature = inspect.signature(getattr(owner, name))
            first = next(iter(signature.parameters.values()))

            assert first.name == "master", f"{owner.__name__}.{name}"
            assert first.default is inspect.Parameter.empty, f"{owner.__name__}.{name}"
            assert first.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD

    def test_the_text_prompt_is_opened_through_a_class_method(self) -> None:
        from app.ui.dialogs.prompt import TextPromptDialog

        assert isinstance(inspect.getattr_static(TextPromptDialog, "ask"), classmethod)

    def test_every_dialog_is_a_toplevel_window(self) -> None:
        # Not a frame inside the main window: a dialog must be able to take focus
        # and be modal, which only a separate window can do.
        import customtkinter as ctk

        from app.ui.dialogs.confirm import ConfirmDialog, NotifyDialog
        from app.ui.dialogs.patient_form import PatientFormDialog
        from app.ui.dialogs.prompt import TextPromptDialog

        for dialog in (ConfirmDialog, NotifyDialog, TextPromptDialog, PatientFormDialog):
            assert issubclass(dialog, ctk.CTkToplevel), dialog.__name__

    def test_the_patient_form_takes_the_service_not_a_repository(self) -> None:
        # The dialog must reach storage through the service layer only. If it
        # ever took a repository, that would be the layer boundary breaking.
        from app.ui.dialogs.patient_form import PatientFormDialog

        parameters = inspect.signature(PatientFormDialog.__init__).parameters

        assert "service" in parameters
        assert not any("repository" in name for name in parameters)


class TestTheme:
    def test_the_palette_is_a_frozen_dataclass(self) -> None:
        import dataclasses

        assert dataclasses.is_dataclass(Palette)
        assert Palette.__dataclass_params__.frozen

    def test_every_palette_field_is_a_light_dark_pair(self) -> None:
        # CustomTkinter accepts a 2-tuple for automatic light/dark switching. A
        # bare string here would silently freeze one of the two modes.
        for field in Palette.__dataclass_fields__.values():
            value = field.default
            assert isinstance(value, tuple) and len(value) == 2, field.name
            assert all(isinstance(part, str) and part for part in value), field.name

    def test_the_window_metrics_are_numbers(self) -> None:
        assert SIDEBAR_WIDTH > 0
        assert STATUS_BAR_HEIGHT > 0


class TestApplicationShell:
    def test_the_shell_can_be_constructed_on_the_class(self) -> None:
        # MedFlowApp subclasses ctk.CTk, which needs a display to instantiate, so
        # only the class itself is inspected here.
        assert issubclass(MedFlowApp, app_module.ctk.CTk)

    def test_build_application_is_the_documented_entry_point(self) -> None:
        parameters = inspect.signature(build_application).parameters
        assert "container" in parameters
        assert "actor" in parameters

    def test_the_actor_defaults_to_the_configured_system_actor(self) -> None:
        # Every action needs an actor for the audit trail, so there is no path
        # that writes a record with nobody's name against it.
        default = inspect.signature(build_application).parameters["actor"].default
        assert default and default != ""


class TestLayering:
    """The rules the refactor exists to enforce."""

    UI_MODULES = tuple(iter_ui_modules())

    @pytest.mark.parametrize("module_name", sorted(UI_MODULES))
    def test_no_ui_module_imports_sqlite_directly(self, module_name: str) -> None:
        source = inspect.getsource(importlib.import_module(module_name))

        assert "import sqlite3" not in source
        assert "from sqlite3" not in source

    @pytest.mark.parametrize("module_name", sorted(UI_MODULES))
    def test_no_ui_module_reaches_into_the_sqlite_package(self, module_name: str) -> None:
        # A view that imports a concrete repository has hard-wired SQLite into
        # the presentation layer, and the swap to a network backend would need
        # the UI rewritten. That is the whole thing this architecture prevents.
        source = inspect.getsource(importlib.import_module(module_name))

        assert "app.repositories" not in source
