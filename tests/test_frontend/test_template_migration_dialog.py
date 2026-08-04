from collections.abc import Iterator
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog
import pytest

from src.backend.utils.template_token_migration import TemplateTokenReport
import src.frontend.windows.template_migration_dialog as template_migration_dialog
from src.frontend.windows.template_migration_dialog import TemplateMigrationDialog


@pytest.fixture
def reports() -> list[TemplateTokenReport]:
    return [
        TemplateTokenReport(
            path=Path("movie.txt"),
            renamed={"movie_title": "title"},
            removed=set(),
        ),
        TemplateTokenReport(
            path=Path("series.txt"),
            renamed={"mi_audio_codec": "audio_codec"},
            removed={"movie_full_title"},
        ),
    ]


@pytest.fixture
def dialog(reports: list[TemplateTokenReport]) -> Iterator[TemplateMigrationDialog]:
    """A dialog per test, explicitly torn down.

    This project has no pytest-qt, so there is no `qtbot`. `tests/conftest.py`
    supplies a session-scoped, autouse `qapp` fixture and sets
    `QT_QPA_PLATFORM=offscreen`; widget tests only need to construct and
    dispose of their own widgets.
    """
    widget = TemplateMigrationDialog(reports, parent=None)
    yield widget
    widget.deleteLater()


def test_dialog_lists_every_affected_template(
    dialog: TemplateMigrationDialog,
) -> None:
    body = dialog.summary_text()

    assert "movie.txt" in body
    assert "series.txt" in body
    assert "movie_title" in body
    assert "audio_codec" in body


def test_dialog_flags_removed_tokens_as_manual_work(
    dialog: TemplateMigrationDialog,
) -> None:
    assert "movie_full_title" in dialog.summary_text()
    assert "no replacement" in dialog.summary_text().lower()


def test_defaults_are_decline_and_keep_asking(
    dialog: TemplateMigrationDialog,
) -> None:
    assert dialog.migrate_requested is False
    assert dialog.suppress_future_prompts is False


def test_accepting_sets_migrate_requested(dialog: TemplateMigrationDialog) -> None:
    dialog.update_button.click()

    assert dialog.migrate_requested is True


def test_suppress_checkbox_is_reported(dialog: TemplateMigrationDialog) -> None:
    dialog.suppress_checkbox.setChecked(True)
    dialog.not_now_button.click()

    assert dialog.migrate_requested is False
    assert dialog.suppress_future_prompts is True


def test_suppress_checkbox_is_captured_when_dialog_is_rejected_directly(
    dialog: TemplateMigrationDialog,
) -> None:
    """Esc and the window's close button both call `QDialog.reject()`
    directly, bypassing `_on_not_now`. `done()` must still capture the
    checkbox on that path."""
    dialog.suppress_checkbox.setChecked(True)
    dialog.reject()

    assert dialog.migrate_requested is False
    assert dialog.suppress_future_prompts is True


def test_update_button_is_not_the_keyboard_default(
    dialog: TemplateMigrationDialog,
) -> None:
    """The destructive action must not be what a reflexive Enter triggers."""
    dialog.show()
    QTest.qWait(20)

    assert dialog.update_button.isDefault() is False
    assert dialog.not_now_button.isDefault() is True


def test_pressing_enter_declines_instead_of_migrating(
    dialog: TemplateMigrationDialog,
) -> None:
    """A single reflexive Return -- the natural reaction to an unexpected
    dialog while the user is still reading the summary -- must land on
    "Not now", not silently rewrite the user's templates."""
    dialog.show()
    QTest.qWait(20)

    QTest.keyClick(dialog, Qt.Key.Key_Return)
    QTest.qWait(150)  # QPushButton.animateClick()'s default 100ms delay

    assert dialog.migrate_requested is False
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_show_diff_renders_for_a_real_file(tmp_path: Path) -> None:
    template_path = tmp_path / "movie.txt"
    template_path.write_text("Title: {{ movie_title }}\n", encoding="utf-8")
    report = TemplateTokenReport(
        path=template_path,
        renamed={"movie_title": "title"},
        removed=set(),
    )
    widget = TemplateMigrationDialog([report], parent=None)
    try:
        widget.diff_button.click()

        diff_text = widget.summary_view.toPlainText()
        assert "movie_title" in diff_text
        assert "title" in diff_text
        assert diff_text != "No textual changes to show."
        assert widget.diff_button.isEnabled() is False
    finally:
        widget.deleteLater()


def test_show_diff_reports_no_changes_when_every_file_is_unreadable(
    dialog: TemplateMigrationDialog,
) -> None:
    """The `dialog` fixture's reports point at paths that don't exist on
    disk, so every per-file read inside `_on_show_diff` fails; each is
    skipped individually rather than treated as an error."""
    dialog.diff_button.click()

    assert dialog.summary_view.toPlainText() == "No textual changes to show."


def test_show_diff_falls_back_to_summary_when_diff_building_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_on_show_diff` runs inside `QDialog.exec()`'s nested event loop, so a
    caller wrapping `exec()` in a try/except can never catch an exception
    raised here -- it has to be handled, and logged, locally instead."""
    template_path = tmp_path / "movie.txt"
    template_path.write_text("Title: {{ movie_title }}\n", encoding="utf-8")
    report = TemplateTokenReport(
        path=template_path,
        renamed={"movie_title": "title"},
        removed=set(),
    )
    widget = TemplateMigrationDialog([report], parent=None)
    try:

        def explode(*args: object, **kwargs: object) -> str:
            raise RuntimeError("boom")

        monkeypatch.setattr(template_migration_dialog, "build_diff", explode)

        widget.diff_button.click()  # must not raise

        assert widget.summary_view.toPlainText() == widget.summary_text()
    finally:
        widget.deleteLater()
