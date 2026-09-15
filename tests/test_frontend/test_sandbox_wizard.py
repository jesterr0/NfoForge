from pathlib import Path

import pytest

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.enums.series import EpisodeFormat
from src.frontend.global_signals import GSigs
from src.frontend.wizards.sandbox_wizard import (
    SandboxMainWindow,
    SandboxSeriesMapperPage,
)
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from tests.repo_paths import build_app_paths


def _paths(tmp_path: Path) -> ConfigPaths:
    return build_app_paths(tmp_path)


def _make_series_mapper_page() -> SandboxSeriesMapperPage:
    file_list = [Path("Show.S01E01.mkv")]
    media_input = MediaInputPayload(
        input_path=Path("Show Season 1"),
        media_type=MediaType.SERIES,
        file_list=file_list,
    )
    media_search = MediaSearchPayload(media_type=MediaType.SERIES, title="Show Title")
    context = ProcessingContext(media_input=media_input, media_search=media_search)

    page = SandboxSeriesMapperPage(config=None, context=context, parent=None)

    # populate the mapper directly instead of running the full load_data/TVDB
    # flow, mirroring the helper used in test_series_match.py
    page.series_mapper.media_input_payload = media_input
    page.series_mapper.file_episode_mappings = {
        file_list[0]: {"season": 1, "episode": 1}
    }
    return page


def test_sandbox_series_mapper_validate_page_persists_series_episode_format() -> None:
    """Regression guard: SandboxSeriesMapperPage.validatePage stored the episode
    map but silently dropped the selected release format (unlike the real
    SeriesMatch.validatePage), so sandbox token formatting always fell back to
    EpisodeFormat.STANDARD regardless of the user's combo box selection."""
    page = _make_series_mapper_page()

    idx = page.series_mapper.release_format_combo.findData(EpisodeFormat.ANIME_ABSOLUTE)
    assert idx != -1
    page.series_mapper.release_format_combo.setCurrentIndex(idx)

    assert page.validatePage() is True
    assert (
        page.context.media_input.series_episode_format is EpisodeFormat.ANIME_ABSOLUTE
    )


def test_sandbox_main_window_disables_itself_while_main_window_set_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard: MediaInput's re-entrancy guard emits
    GSigs().main_window_set_disabled to block the Accept/Next button while its
    MediaInfo worker runs, but only the real MainWindow honored that signal --
    SandboxMainWindow ignored it, so a second click in the sandbox could start
    a second worker and double-connect its signals. SandboxMainWindow must now
    disable/enable itself in response, mirroring MainWindow._toggle_state."""
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )

    manager = ConfigManager("test", _paths(tmp_path))
    context = ProcessingContext()

    window = SandboxMainWindow(config=manager, context=context, parent=None)
    try:
        assert window.isEnabled() is True

        GSigs().main_window_set_disabled.emit(True)
        assert window.isEnabled() is False

        GSigs().main_window_set_disabled.emit(False)
        assert window.isEnabled() is True
    finally:
        GSigs().main_window_set_disabled.disconnect(window._toggle_state)
