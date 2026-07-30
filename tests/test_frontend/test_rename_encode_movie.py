from pathlib import Path
from typing import cast

from pymediainfo import MediaInfo
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog
import pytest

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.frontend.wizards.rename_encode import RenameEncode
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload


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


def _make_movie_rename_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_path: Path = Path("Movie.2020.mkv"),
) -> RenameEncode:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )

    manager = ConfigManager("test", _paths(tmp_path))

    media_input = MediaInputPayload(
        input_path=Path("Movie Folder"),
        media_type=MediaType.MOVIE,
        file_list=[file_path],
    )
    media_search = MediaSearchPayload(media_type=MediaType.MOVIE, title="Movie Title")
    context = ProcessingContext(media_input=media_input, media_search=media_search)

    return RenameEncode(config=manager, context=context, parent=None)


def test_proper_reason_combo_line_edit_gets_its_own_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard: in __init__, the local variable
    `proper_reason_combo_line_edit` was wired to
    `repack_reason_combo.lineEdit()` instead of
    `proper_reason_combo.lineEdit()`, so `proper_reason_combo`'s line edit
    never received its intended placeholder text (it isn't stored as a
    `self` attribute, so we assert on the resulting placeholder instead)."""
    page = _make_movie_rename_page(tmp_path, monkeypatch)

    proper_line_edit = page.proper_reason_combo.lineEdit()
    repack_line_edit = page.repack_reason_combo.lineEdit()

    assert proper_line_edit is not repack_line_edit
    assert proper_line_edit.placeholderText() == page.REASON_STR
    assert repack_line_edit.placeholderText() == page.REASON_STR


def test_confirmed_folder_and_file_rename_updates_payload_asynchronously(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_directory = tmp_path / "Old Movie"
    source_directory.mkdir()
    source = source_directory / "old.mkv"
    source.write_text("data")
    target_directory = tmp_path / "Movie.2020"
    target = target_directory / "Movie.2020.mkv"

    page = _make_movie_rename_page(tmp_path, monkeypatch, source)
    page.context.media_input.input_path = source_directory
    page.context.media_input.file_list_mediainfo = {source: cast(MediaInfo, object())}
    page.context.media_input.working_dir = tmp_path / "work"
    page._input_ext = ".mkv"
    page.output_entry.setText("Movie.2020")

    monkeypatch.setattr(page, "_name_validations", lambda: True)
    monkeypatch.setattr(page, "_quality_validations", lambda: True)
    monkeypatch.setattr(
        "src.frontend.wizards.rename_encode.RenamePreviewDialog.exec",
        lambda self: QDialog.DialogCode.Accepted,
    )

    assert page.validatePage() is False
    for _ in range(80):
        if not page._rename_operation.is_running:
            break
        QTest.qWait(25)

    assert page._advance_after_rename is True
    assert page.context.media_input.input_path == target_directory
    assert page.context.media_input.file_list == [target]
    assert target.is_file()
    assert not source_directory.exists()
