from pathlib import Path
from typing import cast

from pymediainfo import MediaInfo
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog
import pytest

from src.backend.rename_encode import RenameEncodeBackEnd
from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.frontend.wizards.rename_encode import RenameEncode
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from tests.repo_paths import DEFAULT_CONFIG_DIR


def _paths(tmp_path: Path) -> ConfigPaths:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    source_defaults = DEFAULT_CONFIG_DIR
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


def test_failed_render_clears_stale_generated_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _make_movie_rename_page(tmp_path, monkeypatch)
    page._input_ext = ".mkv"
    page.output_entry.setText("Stale.Name")
    monkeypatch.setattr(
        RenameEncodeBackEnd,
        "media_renamer",
        lambda self, **kwargs: None,
    )

    page.update_generated_name()

    assert page.output_entry.text() == ""
    assert page._input_ext is None


def test_hybrid_is_pre_ticked_from_the_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # HYBRID had no pre-tick, so the claim was invisible until the user
    # found the checkbox.
    page = _make_movie_rename_page(
        tmp_path,
        monkeypatch,
        file_path=Path("Movie.2024.HYBRID.1080p.BluRay.x264-GRP.mkv"),
    )

    page.initializePage()

    assert page.hybrid_checkbox.isChecked() is True


def test_claims_are_pre_filled_from_the_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _make_movie_rename_page(
        tmp_path,
        monkeypatch,
        file_path=Path(
            "Movie.2024.Directors.Cut.IMAX.REPACK.1080p.BluRay.x264-GRP.mkv"
        ),
    )

    page.initializePage()

    assert page.edition_combo.currentText() == "Directors Cut"
    assert page.frame_size_combo.currentText() == "IMAX"
    assert page.re_release_combo.currentText() == "REPACK"


def test_a_switched_off_category_is_not_pre_filled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _make_movie_rename_page(
        tmp_path,
        monkeypatch,
        file_path=Path("Movie.2024.IMAX.REPACK.1080p.BluRay.x264-GRP.mkv"),
    )
    page.config.settings.movie.claims.frame_size = False

    page.initializePage()

    assert page.frame_size_combo.currentText() == ""
    assert page.re_release_combo.currentText() == "REPACK"


def test_release_group_falls_back_to_the_detected_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _make_movie_rename_page(
        tmp_path,
        monkeypatch,
        file_path=Path("Movie.2024.1080p.WEB-DL.x264-OTHERGROUP.mkv"),
    )
    page.config.settings.movie.release_group = ""

    page.initializePage()

    assert page.release_group_entry.text() == "OTHERGROUP"


def test_a_configured_release_group_wins_over_the_detected_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _make_movie_rename_page(
        tmp_path,
        monkeypatch,
        file_path=Path("Movie.2024.1080p.WEB-DL.x264-OTHERGROUP.mkv"),
    )
    page.config.settings.movie.release_group = "MYGROUP"

    page.initializePage()

    assert page.release_group_entry.text() == "MYGROUP"
