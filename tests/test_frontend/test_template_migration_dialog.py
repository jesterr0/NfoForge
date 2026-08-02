from collections.abc import Iterator
from pathlib import Path

import pytest

from src.backend.utils.template_token_migration import TemplateTokenReport
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
