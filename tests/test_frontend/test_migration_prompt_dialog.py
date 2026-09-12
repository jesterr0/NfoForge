"""The one question a user is ever asked about the layout migration.

Asked once per machine, on the launch that migrates, and never again. That makes
it worth more care than its size suggests: whatever it returns is what happens to
the data, and there is no second chance to read it properly.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from src.config.layout_migration import LegacyInstall
import src.frontend.windows.migration_prompt_dialog as prompt_module
from src.frontend.windows.migration_prompt_dialog import MigrationPromptDialog


def _install(tmp_path: Path, name: str = "previous install") -> LegacyInstall:
    """A directory `recognise_legacy_install` accepts."""
    root = tmp_path / name
    state = root / "bundle" / "runtime"
    (state / "config" / "user").mkdir(parents=True)
    return LegacyInstall(root=root, state=state, plugins=root / "plugins")


@pytest.fixture
def found_dialog(tmp_path: Path) -> Iterator[MigrationPromptDialog]:
    widget = MigrationPromptDialog(_install(tmp_path), parent=None)
    yield widget
    widget.deleteLater()


@pytest.fixture
def not_found_dialog() -> Iterator[MigrationPromptDialog]:
    widget = MigrationPromptDialog(None, parent=None)
    yield widget
    widget.deleteLater()


def test_the_found_state_names_the_folder_it_found(
    found_dialog: MigrationPromptDialog, tmp_path: Path
) -> None:
    """The path is the whole point of the found state.

    A user with more than one copy extracted needs to see which one is about to
    be imported, and it is the only way to tell that the application found the
    right thing.
    """
    assert str(tmp_path / "previous install") in found_dialog.message_text()


def test_the_found_state_offers_to_migrate(
    found_dialog: MigrationPromptDialog,
) -> None:
    assert found_dialog.migrate_button.isEnabled()


def test_the_not_found_state_cannot_migrate_nothing(
    not_found_dialog: MigrationPromptDialog,
) -> None:
    """Offering a disabled action is clearer than offering one that fails.

    Nothing was found, so there is nothing to migrate and the two real choices
    are to point at a folder or to start fresh.
    """
    assert not not_found_dialog.migrate_button.isEnabled()
    assert "start fresh" in not_found_dialog.message_text().lower()


def test_migrating_chooses_the_installation_that_was_found(
    found_dialog: MigrationPromptDialog, tmp_path: Path
) -> None:
    found_dialog.migrate_button.click()

    assert found_dialog.chosen is not None
    assert found_dialog.chosen.root == tmp_path / "previous install"


def test_starting_fresh_chooses_nothing(
    found_dialog: MigrationPromptDialog,
) -> None:
    found_dialog.fresh_button.click()

    assert found_dialog.chosen is None


def test_closing_the_dialog_any_other_way_starts_fresh(
    found_dialog: MigrationPromptDialog,
) -> None:
    """Escape and the window close button both reject without a handler.

    Starting fresh is the safe reading of "I do not understand this dialog":
    nothing is moved that was not already in the data directory, the previous
    installation is untouched, and the import stays available from Settings. The
    summary says so, because a silent skip the user cannot undo would not be
    safe at all.
    """
    found_dialog.reject()

    assert found_dialog.chosen is None


def test_picking_a_folder_that_holds_an_installation_chooses_it(
    not_found_dialog: MigrationPromptDialog,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The answer to the not-found state, and the recovery from a wrong guess."""
    elsewhere = _install(tmp_path, "somewhere else")
    monkeypatch.setattr(
        prompt_module.QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *_args, **_kwargs: str(elsewhere.root)),
    )

    not_found_dialog.choose_button.click()

    assert not_found_dialog.chosen is not None
    assert not_found_dialog.chosen.root == elsewhere.root


def test_picking_a_folder_with_nothing_in_it_says_so_and_stays_open(
    not_found_dialog: MigrationPromptDialog,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closing on a bad choice would leave the user nowhere.

    They picked the wrong folder, which is easily done, so the dialog has to say
    nothing was there and let them try again rather than treating a mistake as a
    decision to start fresh.
    """
    empty = tmp_path / "not an installation"
    empty.mkdir()
    monkeypatch.setattr(
        prompt_module.QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *_args, **_kwargs: str(empty)),
    )
    warned: list[str] = []
    monkeypatch.setattr(
        not_found_dialog, "_report_nothing_found", lambda path: warned.append(str(path))
    )

    not_found_dialog.choose_button.click()

    assert not_found_dialog.chosen is None
    assert not_found_dialog.isVisible() is False  # never shown, so never hidden
    assert warned == [str(empty)]
    assert not_found_dialog.result() == 0


def test_cancelling_the_folder_picker_changes_nothing(
    not_found_dialog: MigrationPromptDialog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty answer is the user backing out of the picker, not a choice."""
    monkeypatch.setattr(
        prompt_module.QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *_args, **_kwargs: ""),
    )
    reported: list[object] = []
    monkeypatch.setattr(
        not_found_dialog, "_report_nothing_found", lambda path: reported.append(path)
    )

    not_found_dialog.choose_button.click()

    assert not_found_dialog.chosen is None
    assert reported == []
    assert not_found_dialog.result() == 0
