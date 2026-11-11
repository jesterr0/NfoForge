from pathlib import Path
from types import SimpleNamespace
from typing import cast

from pymediainfo import MediaInfo
from PySide6.QtWidgets import QMessageBox
import pytest

from nfoforge.context.processing_context import ProcessingContext
from nfoforge.exceptions import MediaFileNotFoundError
from nfoforge.frontend.wizards.media_input import MediaInput
from tests.disc_helpers import make_bluray, make_dvd


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
            None,
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

    page._worker_finished(({}, {}, None))

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


def _disc_page(monkeypatch: pytest.MonkeyPatch, bdinfo: Path | None) -> MediaInput:
    config = SimpleNamespace(
        settings=SimpleNamespace(dependencies=SimpleNamespace(bdinfo=bdinfo))
    )
    page = MediaInput(config=config, context=ProcessingContext(), parent=None)  # type: ignore[arg-type]
    monkeypatch.setattr(page, "_run_worker", lambda: None)
    return page


def _two_cut_disc(root: Path) -> Path:
    return make_bluray(
        root,
        {"00800": [("00001", 0, 7200)], "00801": [("00002", 0, 7500)]},
        {"00001": 4900, "00002": 5000},
    )


def test_a_disc_shows_its_playlists_instead_of_the_file_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _two_cut_disc(tmp_path / "Movie.2020.BluRay")
    page = _disc_page(monkeypatch, tmp_path / "bdinfo-rs.exe")

    page._update_media_input(root)

    assert page.file_tree.isHidden() and not page.disc_widget.isHidden()
    assert not page.comparison_toggle_btn.isEnabled()
    assert "2 possible main playlists" in page.disc_note.text()
    assert page.disc_table.rowCount() == 2
    # the larger cut is suggested, and the suggestion can be changed
    assert page.disc_table.currentRow() == 1
    page.disc_table.selectRow(0)
    page.update_payload_data()

    media_input = page.context.media_input
    (disc,) = media_input.discs
    assert disc.selected == ["00800"]
    assert media_input.file_list == [root / "BDMV" / "STREAM" / "00001.m2ts"]
    assert media_input.input_kind == "directory"
    assert media_input.content_size == disc.size

    # opening a plain folder afterwards puts the tree back
    plain = tmp_path / "plain"
    plain.mkdir()
    page._update_media_input(plain)
    assert page.disc_widget.isHidden() and not page.file_tree.isHidden()
    assert not page.context.media_input.discs


def test_a_dvd_preselects_its_first_main_title_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_dvd(tmp_path / "Show.DVD9", {"01": [1, 100], "02": [1, 100]})
    page = _disc_page(monkeypatch, None)

    page._update_media_input(root)
    page.update_payload_data()

    assert page.context.media_input.discs[0].selected == ["01"]


def test_a_bluray_without_a_bdinfo_path_is_refused_before_any_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_bluray(tmp_path / "disc", {"00800": [("00001", 0, 7200)]}, {"00001": 9})
    page = _disc_page(monkeypatch, None)
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _parent, _title, text: warnings.append(text)
    )

    page._update_media_input(root)
    with pytest.raises(MediaFileNotFoundError):
        page.update_payload_data()

    assert len(warnings) == 1 and "BDInfo" in warnings[0]


def test_an_unusable_disc_is_refused_rather_than_read_as_loose_clips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_bluray(tmp_path / "set" / "D1", {"00800": [("00001", 0, 7200)]}, {"00001": 9})
    make_bluray(tmp_path / "set" / "D2", {"00800": [("00001", 0, 7200)]}, {"00001": 9})
    page = _disc_page(monkeypatch, None)
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _parent, _title, text: warnings.append(text)
    )

    page._update_media_input(tmp_path / "set")

    assert len(warnings) == 1 and "Multi-disc" in warnings[0]
    assert page.media_input_entry.text() == ""
    assert page.file_tree.isHidden() and page.disc_widget.isHidden()


def test_a_disc_that_cannot_be_scanned_reports_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _disc_page(monkeypatch, None)
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda _parent, title, message: shown.append((title, message)),
    )

    page._worker_finished(({}, {}, "bdinfo-rs failed: unreadable disc"))

    assert shown == [("Disc Error", "bdinfo-rs failed: unreadable disc")]
    assert page._loading_completed is False


def test_the_wizard_has_no_stray_back_arrow() -> None:
    """Qt 6.12 shows an Aero back arrow on every wizard; ours hide it."""
    from PySide6.QtWidgets import QAbstractButton, QPushButton, QWizard, QWizardPage

    from nfoforge.frontend.utils.wizard_back_arrow import hide_stray_back_arrow

    wizard = QWizard()
    wizard.setWizardStyle(QWizard.WizardStyle.ModernStyle)
    page = QWizardPage()
    keep = QPushButton("on the page", page)
    wizard.addPage(page)
    hide_stray_back_arrow(wizard)
    wizard.show()

    own = {wizard.button(QWizard.WizardButton(i)) for i in range(9)}
    shown = [
        button
        for button in wizard.findChildren(QAbstractButton)
        if button.isVisible() and button not in own
    ]
    assert shown == [keep]
    wizard.close()
