from pathlib import Path

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.enums.series import EpisodeFormat
from src.frontend.wizards.rename_encode_series import RenameEncodeSeries
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload

# a token template that exercises the same "{token|filter}" shape used by the
# real default series tokens (tvr_standard_episode_token pipes season_number
# and episode_number through "|zfill(2)")
TEST_TOKEN = "{title_clean} S{season_number|zfill(2)}E{episode_number|zfill(2)}"


def _paths(tmp_path: Path) -> ConfigPaths:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    source_defaults = Path("runtime/config/defaults")
    default_config = defaults / "default_config.toml"
    default_program = defaults / "default_program_conf.toml"
    default_config.write_text(
        (source_defaults / "default_config.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    default_program.write_text(
        (source_defaults / "default_program_conf.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return ConfigPaths(
        default_config=default_config,
        default_program=default_program,
        program=tmp_path / "program/conf.toml",
        user_configs=tmp_path / "user",
        tracker_cookies=tmp_path / "cookies",
    )


def _make_series_rename_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_path: Path = Path("Show.S01E01.mkv"),
    episode_map: dict | None = None,
) -> RenameEncodeSeries:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )

    # a QApplication instance is required to construct any QWidget
    QApplication.instance() or QApplication([])

    manager = ConfigManager("test", _paths(tmp_path))

    if episode_map is None:
        episode_map = {file_path: {"season": 1, "episode": 1}}

    media_input = MediaInputPayload(
        input_path=Path("Show Season 1"),
        media_type=MediaType.SERIES,
        file_list=[file_path],
        series_episode_map=episode_map,
        series_episode_format=EpisodeFormat.STANDARD,
    )
    media_search = MediaSearchPayload(media_type=MediaType.SERIES, title="Show Title")
    context = ProcessingContext(media_input=media_input, media_search=media_search)

    return RenameEncodeSeries(config=manager, context=context, parent=None)


def test_update_generated_name_populates_override_token_table_for_mapped_episode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard: update_generated_name never ran the series renamer or
    called populate_table, so the override token grid stayed empty for the
    whole page life. It must now populate from a representative (first
    mapped) episode, including the series-specific tokens."""
    page = _make_series_rename_page(tmp_path, monkeypatch)

    page.token_override.setText(TEST_TOKEN)
    page.override_group.setChecked(True)

    table = page.rename_token_control.table
    assert table.rowCount() > 0

    token_values = page.rename_token_control.get_token_values()
    assert token_values.get("{title_clean}") == "Show Title"
    assert token_values.get("{season_number}") == "01"
    assert token_values.get("{episode_number}") == "01"


def test_update_generated_name_with_no_mapped_episodes_clears_table_without_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When there is no episode mapping yet, update_generated_name must not
    crash and must leave the override grid empty rather than stale."""
    page = _make_series_rename_page(tmp_path, monkeypatch)

    page.token_override.setText(TEST_TOKEN)
    page.override_group.setChecked(True)
    assert page.rename_token_control.table.rowCount() > 0

    # simulate returning to this page with the mapping cleared/reset
    page.context.media_input.series_episode_map = None
    page.update_generated_name()

    assert page.rename_token_control.table.rowCount() == 0


def test_editing_override_token_row_feeds_back_into_generated_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Editing a value in the override token grid (row_modified) must update
    backend.override_tokens and regenerate the preview so the grid reflects
    the override -- this path was unreachable while the grid stayed empty."""
    page = _make_series_rename_page(tmp_path, monkeypatch)

    page.token_override.setText(TEST_TOKEN)
    page.override_group.setChecked(True)

    table = page.rename_token_control.table
    row = next(
        r
        for r in range(table.rowCount())
        if table.item(r, 0).text() == "{season_number}"
    )

    # simulate the user editing the "season_number" row's value cell; the
    # real edit path goes through QTableWidget.itemChanged -> _item_changed,
    # which defers the row_modified emit by one tick via QTimer.singleShot.
    # Poll for it instead of a single fixed-length wait: a single short
    # QTest.qWait can miss the deferred emit on a busier run (e.g. when
    # other Qt widgets were constructed earlier in the same test session),
    # since it only pumps the event loop for that fixed window.
    table.item(row, 1).setText("99")
    for _ in range(20):
        if "season_number" in page.backend.override_tokens:
            break
        QTest.qWait(25)

    assert page.backend.override_tokens["season_number"] == "99"
    assert "season_number" in page._overridden_tokens

    # the regenerated grid must reflect the overridden value
    token_values = page.rename_token_control.get_token_values()
    assert token_values.get("{season_number}") == "99"


def test_series_rename_token_control_reset_restores_signals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard: SeriesRenameTokenControl.reset() called
    table.blockSignals(True) but never called blockSignals(False), so once
    reset() ran the table's signals stayed permanently blocked. It was dead
    code until update_generated_name started calling it from the
    no-mapped-episode branch. Signals must be restored after reset()."""
    page = _make_series_rename_page(tmp_path, monkeypatch)

    table = page.rename_token_control.table
    assert table.signalsBlocked() is False

    page.rename_token_control.reset()

    assert table.signalsBlocked() is False
