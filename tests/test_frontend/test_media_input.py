from pathlib import Path
from typing import cast

from pymediainfo import MediaInfo
from PySide6.QtWidgets import QMessageBox
import pytest

from src.context.processing_context import ProcessingContext
from src.exceptions import MediaFileNotFoundError
from src.frontend.wizards.media_input import MediaInput


def test_media_info_failure_reports_missing_files_and_restores_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = MediaInput(config=None, context=ProcessingContext(), parent=None)  # type: ignore[arg-type]
    expected = (Path("one.mkv"), Path("two.mkv"))
    page._loading_completed = True
    page._progress_connected = False
    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda _parent, _title, message: messages.append(message),
    )

    page._worker_finished(
        (
            {expected[0]: cast(MediaInfo, object())},
            {expected[1]: "OSError: unreadable stream"},
        ),
    )

    assert page._loading_completed is False
    assert len(messages) == 1
    assert "two.mkv" in messages[0]
    assert "unreadable stream" in messages[0]
    assert "one.mkv" not in messages[0]


def test_media_info_empty_result_does_not_raise_or_leave_ui_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = MediaInput(config=None, context=ProcessingContext(), parent=None)  # type: ignore[arg-type]
    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda _parent, _title, message: messages.append(message),
    )

    page._worker_finished(({}, {}))

    assert page._loading_completed is False
    assert messages == ["Failed to detect MediaInfo for the selected files."]


def _page_on_directory(directory: Path, monkeypatch: pytest.MonkeyPatch) -> MediaInput:
    page = MediaInput(config=None, context=ProcessingContext(), parent=None)  # type: ignore[arg-type]
    page.media_input_entry.setText(str(directory))
    page.file_tree.build_tree(directory)
    # the worker needs a config for the working dir; the file selection this
    # asserts on is complete before it runs
    monkeypatch.setattr(page, "_run_worker", lambda: None)
    return page


def test_directory_input_keeps_only_video_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Subtitles and metadata must not reach `file_list`.

    Everything in `file_list` is parsed by MediaInfo, listed by the series
    episode mapper as a file needing an episode, and rendered by
    `{episode_mediainfo}` -- none of which is meaningful for a .srt.
    """
    pack = tmp_path / "Show.S01"
    pack.mkdir()
    episode = pack / "Show.S01E01.mkv"
    episode.write_text("v")
    (pack / "Show.S01E01.en.srt").write_text("s")
    (pack / "Show.S01E01.nfo").write_text("n")
    (pack / "poster.jpg").write_text("i")
    (pack / "Show.S01E01.sample.mkv").write_text("smp")

    page = _page_on_directory(pack, monkeypatch)
    page.update_payload_data()

    assert page.context.media_input.file_list == [episode]


def test_directory_input_recurses_into_season_subfolders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "Show.Complete.Series"
    season_one = root / "Season 01"
    season_two = root / "Season 02"
    season_one.mkdir(parents=True)
    season_two.mkdir(parents=True)
    ep1 = season_one / "Show.S01E01.mkv"
    ep2 = season_two / "Show.S02E01.mkv"
    ep1.write_text("1")
    ep2.write_text("2")
    (season_one / "Show.S01E01.srt").write_text("s")

    page = _page_on_directory(root, monkeypatch)
    page.update_payload_data()

    assert page.context.media_input.file_list == sorted([ep1, ep2])


def test_directory_with_no_video_files_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack = tmp_path / "Show.S01"
    pack.mkdir()
    (pack / "readme.nfo").write_text("n")

    page = _page_on_directory(pack, monkeypatch)

    with pytest.raises(MediaFileNotFoundError, match="No supported video files"):
        page.update_payload_data()
