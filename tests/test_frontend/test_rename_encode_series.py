from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QMessageBox
import pytest

from src.backend.rename_encode_series import RenameEncodeSeriesBackEnd
from src.backend.utils.filename_claims import PER_FILE_CLAIM_KEYS
from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.enums.series import EpisodeFormat
from src.frontend.custom_widgets.episode_claims_table import (
    CLAIM_COLUMNS,
    VALUE_CLAIMS,
    _is_checked,
)
from src.frontend.wizards.rename_encode_series import RenameEncodeSeries
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from tests.repo_paths import DEFAULT_CONFIG_DIR

# a token template that exercises the same "{token|filter}" shape used by the
# real default series tokens (tvr_standard_episode_token pipes season_number
# and episode_number through "|zfill(2)")
TEST_TOKEN = "{title_clean} S{season_number|zfill(2)}E{episode_number|zfill(2)}"  # noqa: S105 - NFO template token string used as test fixture data, not a credential


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

    manager = ConfigManager("test", _paths(tmp_path))

    if episode_map is None:
        episode_map = {file_path: {"season": 1, "episode": 1}}

    media_input = MediaInputPayload(
        input_path=Path("Show Season 1"),
        media_type=MediaType.SERIES,
        file_list=list(episode_map),
        series_episode_map=episode_map,
        series_episode_format=EpisodeFormat.STANDARD,
    )
    media_search = MediaSearchPayload(media_type=MediaType.SERIES, title="Show Title")
    context = ProcessingContext(media_input=media_input, media_search=media_search)

    return RenameEncodeSeries(config=manager, context=context, parent=None)


def test_initialize_page_does_not_promote_first_episode_values_to_pack_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_file = Path("Show.S01E01.REPACK.1080p.BluRay.REMUX-GRP.mkv")
    second_file = Path("Show.S01E02.720p.WEB-DL-OTHER.mkv")
    page = _make_series_rename_page(
        tmp_path,
        monkeypatch,
        file_path=first_file,
        episode_map={
            first_file: {"season": 1, "episode": 1},
            second_file: {"season": 1, "episode": 2},
        },
    )
    page.config.settings.series.standard_episode_token = TEST_TOKEN

    page.initializePage()

    assert "re_release" not in page.backend.override_tokens
    assert "source" not in page.backend.override_tokens
    assert "remux" not in page.backend.override_tokens


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


def test_all_episode_renames_failing_shows_warning_and_aborts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard: when every episode's token render fails, rename_map
    stayed empty and validatePage fell through to the "no effective renames"
    branch, which can advance the wizard with nothing renamed and no message.
    Every render failing must now abort validation and tell the user which
    files could not be renamed."""
    file_path = Path("Show.S01E01.mkv")
    page = _make_series_rename_page(tmp_path, monkeypatch, file_path=file_path)

    monkeypatch.setattr(page, "_name_validations", lambda: True)
    monkeypatch.setattr(page, "_quality_validations", lambda: True)
    monkeypatch.setattr(
        RenameEncodeSeriesBackEnd, "series_renamer", lambda self, **kwargs: None
    )
    # With the fix, an empty rename_map aborts before this is ever called;
    # mocked here so a pre-fix run fails on the missing warning rather than on
    # an unrelated crash further down (real media info was never supplied).
    monkeypatch.setattr(
        RenameEncodeSeriesBackEnd,
        "series_folder_renamer",
        lambda self, **kwargs: None,
    )

    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, message: messages.append((title, message)),
    )

    assert page.validatePage() is False

    assert messages
    title, message = messages[-1]
    assert title == "Rename Failed"
    assert file_path.name in message


def test_partial_episode_rename_failure_warns_but_does_not_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A single failed episode token render must not be treated as if every
    file failed: the loop should warn about (and skip) only the file(s) that
    actually failed, and validation should still proceed for the rest."""
    good_file = Path("Show.S01E01.mkv")
    bad_file = Path("Show.S01E02.mkv")
    episode_map = {
        good_file: {"season": 1, "episode": 1},
        bad_file: {"season": 1, "episode": 2},
    }
    page = _make_series_rename_page(
        tmp_path, monkeypatch, file_path=good_file, episode_map=episode_map
    )

    monkeypatch.setattr(page, "_name_validations", lambda: True)
    monkeypatch.setattr(page, "_quality_validations", lambda: True)

    def _series_renamer(self, *, media_file: Path, **kwargs: object) -> Path | None:
        return None if media_file == bad_file else Path("Show S01E01 Renamed")

    monkeypatch.setattr(RenameEncodeSeriesBackEnd, "series_renamer", _series_renamer)
    monkeypatch.setattr(
        RenameEncodeSeriesBackEnd,
        "series_folder_renamer",
        lambda self, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.frontend.wizards.rename_encode_series.RenamePreviewDialog.exec",
        lambda self: QDialog.DialogCode.Rejected,
    )

    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, message: messages.append((title, message)),
    )

    # Rejecting the preview dialog returns False before any rename runs; this
    # keeps the assertion focused on the loop's own skip-reporting rather than
    # on the filesystem rename machinery.
    assert page.validatePage() is False

    titles = [title for title, _ in messages]
    assert "Rename Failed" not in titles
    assert "Some Files Skipped" in titles
    skipped_message = next(
        message for title, message in messages if title == "Some Files Skipped"
    )
    assert bad_file.name in skipped_message
    assert good_file.name not in skipped_message


def _captured_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    input_path: Path,
    episode_map: dict,
    renamed_stems: dict[Path, str],
    root_folder_name: str = "Show.S01-S02",
    season_folder_names: dict[int, str] | None = None,
    subfolder_token: str = "",
):
    """Drive `validatePage` far enough to capture the RenamePlan it builds."""
    page = _make_series_rename_page(
        tmp_path,
        monkeypatch,
        file_path=next(iter(episode_map)),
        episode_map=episode_map,
    )
    page.context.media_input.input_path = input_path
    page.config.settings.series.season_subfolder_token = subfolder_token

    monkeypatch.setattr(page, "_name_validations", lambda: True)
    monkeypatch.setattr(page, "_quality_validations", lambda: True)
    # the real `series_renamer` runs in file_name_mode, which appends the
    # primary file's extension; the page then strips it back off with `.stem`
    monkeypatch.setattr(
        RenameEncodeSeriesBackEnd,
        "series_renamer",
        lambda self, *, media_file, **kwargs: Path(
            f"{renamed_stems[media_file]}{media_file.suffix}"
        ),
    )

    names = season_folder_names or {}

    def _folder_renamer(self, *, season_num, season_end=None, **kwargs):
        if season_end is not None and season_end != season_num:
            return Path(root_folder_name)
        return Path(names[season_num]) if season_num in names else None

    monkeypatch.setattr(
        RenameEncodeSeriesBackEnd, "series_folder_renamer", _folder_renamer
    )

    captured: dict = {}

    def _capture(self, rename_map, directory_map=None):
        captured["files"] = rename_map
        captured["directories"] = directory_map

    monkeypatch.setattr(
        "src.frontend.wizards.rename_encode_series.RenamePreviewDialog.set_renames",
        _capture,
    )
    monkeypatch.setattr(
        "src.frontend.wizards.rename_encode_series.RenamePreviewDialog.exec",
        lambda self: QDialog.DialogCode.Rejected,
    )

    assert page.validatePage() is False
    return captured


def test_nested_pack_renames_root_and_each_season_subfolder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "Show.Complete.Series"
    season_one = root / "Season 01"
    season_two = root / "Season 02"
    season_one.mkdir(parents=True)
    season_two.mkdir(parents=True)
    ep1 = season_one / "raw1.mkv"
    ep2 = season_two / "raw2.mkv"
    ep1.write_text("1")
    ep2.write_text("2")

    captured = _captured_plan(
        tmp_path,
        monkeypatch,
        input_path=root,
        episode_map={
            ep1: {"season": 1, "episode": 1},
            ep2: {"season": 2, "episode": 1},
        },
        renamed_stems={ep1: "Show.S01E01", ep2: "Show.S02E01"},
        season_folder_names={1: "Show.S01", 2: "Show.S02"},
    )

    new_root = tmp_path / "Show.S01-S02"
    assert captured["directories"] == {
        root: new_root,
        season_one: new_root / "Show.S01",
        season_two: new_root / "Show.S02",
    }
    assert captured["files"] == {
        ep1: new_root / "Show.S01" / "Show.S01E01.mkv",
        ep2: new_root / "Show.S02" / "Show.S02E01.mkv",
    }


def test_subfolder_token_overrides_the_season_folder_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A set subfolder token names the subfolders without touching the root."""
    root = tmp_path / "Show.Complete.Series"
    season_one = root / "S1"
    season_one.mkdir(parents=True)
    ep1 = season_one / "raw1.mkv"
    ep1.write_text("1")

    captured = _captured_plan(
        tmp_path,
        monkeypatch,
        input_path=root,
        episode_map={ep1: {"season": 1, "episode": 1}},
        renamed_stems={ep1: "Show.S01E01"},
        root_folder_name="Show.S01-S02",
        season_folder_names={1: "Season 01"},
        subfolder_token="Season {season_number|zfill(2)}",  # noqa: S106 - token template fixture, not a credential
    )

    # a single-season pack renders no range, so the root takes the season name
    new_root = tmp_path / "Season 01"
    assert captured["directories"] == {
        root: new_root,
        season_one: new_root / "Season 01",
    }


def test_sidecars_follow_their_episode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "Show.S01"
    root.mkdir()
    ep1 = root / "raw1.mkv"
    ep1.write_text("1")
    subtitle = root / "raw1.en.srt"
    subtitle.write_text("s")
    episode_nfo = root / "raw1.nfo"
    episode_nfo.write_text("n")
    unrelated = root / "poster.jpg"
    unrelated.write_text("i")

    captured = _captured_plan(
        tmp_path,
        monkeypatch,
        input_path=root,
        episode_map={ep1: {"season": 1, "episode": 1}},
        renamed_stems={ep1: "Show.S01E01"},
        season_folder_names={1: "Show.S01.Renamed"},
    )

    new_root = tmp_path / "Show.S01.Renamed"
    assert captured["files"] == {
        ep1: new_root / "Show.S01E01.mkv",
        subtitle: new_root / "Show.S01E01.en.srt",
        episode_nfo: new_root / "Show.S01E01.nfo",
    }
    # not named after the episode, so it is left alone and rides along
    assert unrelated not in captured["files"]


def _series_page_with_episodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *file_paths: Path
) -> RenameEncodeSeries:
    """A series rename page over a pack of the given files."""
    episode_map = {
        path: {"season": 1, "episode": index}
        for index, path in enumerate(file_paths, start=1)
    }
    return _make_series_rename_page(
        tmp_path, monkeypatch, file_path=file_paths[0], episode_map=episode_map
    )


def test_hybrid_is_pre_ticked_when_every_episode_is_hybrid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # HYBRID had no pre-tick at all: _auto_check_remux_checkbox has no
    # hybrid equivalent, so the claim was invisible until the user found
    # the checkbox.
    page = _series_page_with_episodes(
        tmp_path,
        monkeypatch,
        Path("Show.S01E01.HYBRID.1080p.BluRay.x264-GRP.mkv"),
        Path("Show.S01E02.HYBRID.1080p.BluRay.x264-GRP.mkv"),
    )

    page.initializePage()

    assert page.hybrid_checkbox.isChecked() is True


def test_hybrid_is_not_pre_ticked_when_only_some_episodes_are(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _series_page_with_episodes(
        tmp_path,
        monkeypatch,
        Path("Show.S01E01.HYBRID.1080p.BluRay.x264-GRP.mkv"),
        Path("Show.S01E02.1080p.BluRay.x264-GRP.mkv"),
    )

    page.initializePage()

    assert page.hybrid_checkbox.isChecked() is False


def test_remux_is_pre_ticked_only_when_every_episode_is_a_remux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # REMUX keeps its pack-wide pre-tick, now from the same detector as
    # the other five rather than its own bespoke check.
    page = _series_page_with_episodes(
        tmp_path,
        monkeypatch,
        Path("Show.S01E01.1080p.BluRay.REMUX.AVC-GRP.mkv"),
        Path("Show.S01E02.1080p.BluRay.REMUX.AVC-GRP.mkv"),
    )

    page.initializePage()

    assert page.remux_checkbox.isChecked() is True


def test_a_switched_off_category_is_not_pre_filled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _series_page_with_episodes(
        tmp_path, monkeypatch, Path("Show.S01E01.REPACK.1080p.WEB-DL.x264-GRP.mkv")
    )
    page.config.settings.series.claims.re_release = False

    page.initializePage()

    assert page.re_release_combo.currentText() == ""


def test_a_switched_off_category_leaves_the_others_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _series_page_with_episodes(
        tmp_path,
        monkeypatch,
        Path("Show.S01E01.IMAX.REPACK.1080p.WEB-DL.x264-GRP.mkv"),
    )
    page.config.settings.series.claims.frame_size = False

    page.initializePage()

    assert page.frame_size_combo.currentText() == ""
    assert page.re_release_combo.currentText() == "REPACK"


def test_a_plugin_localization_override_survives_a_switched_off_category(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defect this page had: the movie page applied a plugin's value and
    this one never looked for it, so a value written on the way in was
    silently dropped. The claims switches govern filename parsing, and a
    plugin's value is evidence from elsewhere, so the switch does not
    suppress it here either."""
    page = _series_page_with_episodes(
        tmp_path, monkeypatch, Path("Show.S01E01.1080p.WEB-DL.x264-GRP.mkv")
    )
    page.config.settings.series.claims.localization = False
    page.context.shared_data.dynamic_data["localization_override"] = "Subbed"

    page.initializePage()

    assert page.localization_combo.currentText() == "Subbed"


def test_a_plugin_localization_override_beats_the_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both have something to say, so ordering decides: the pre-fill runs
    first and the plugin's value overwrites it."""
    page = _series_page_with_episodes(
        tmp_path, monkeypatch, Path("Show.S01E01.DUBBED.1080p.WEB-DL.x264-GRP.mkv")
    )
    page.context.shared_data.dynamic_data["localization_override"] = "Subbed"

    page.initializePage()

    assert page.localization_combo.currentText() == "Subbed"


def test_release_group_falls_back_to_the_detected_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The settings value is the user's group tag; the filename's is the
    # source group, meaning whoever made the input. With settings blank the
    # field showed empty while the output carried OTHERGROUP -- the field and
    # the output disagreed.
    page = _series_page_with_episodes(
        tmp_path, monkeypatch, Path("Show.S01E01.1080p.WEB-DL.x264-OTHERGROUP.mkv")
    )
    page.config.settings.general.release_group = ""

    page.initializePage()

    assert page.release_group_entry.text() == "OTHERGROUP"


def test_a_configured_release_group_wins_over_the_detected_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _series_page_with_episodes(
        tmp_path, monkeypatch, Path("Show.S01E01.1080p.WEB-DL.x264-OTHERGROUP.mkv")
    )
    page.config.settings.general.release_group = "MYGROUP"

    page.initializePage()

    assert page.release_group_entry.text() == "MYGROUP"


def test_switching_release_group_parsing_off_leaves_the_field_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The switch has to reach output, not just the control. The renderer
    parses no filename of its own, so an undetected source group cannot
    appear anywhere -- which is what makes the empty field honest."""
    page = _series_page_with_episodes(
        tmp_path, monkeypatch, Path("Show.S01E01.1080p.WEB-DL.x264-OTHERGROUP.mkv")
    )
    page.config.settings.general.release_group = ""
    page.config.settings.series.claims.release_group = False

    page.initializePage()

    assert page.release_group_entry.text() == ""
    assert page.backend.override_tokens["release_group"] == ""


def test_clearing_the_field_beats_the_configured_group_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This page is stage 2, so a blank here is a decision -- "this release
    carries no group" -- rather than an absence to fall through from."""
    page = _series_page_with_episodes(
        tmp_path, monkeypatch, Path("Show.S01E01.1080p.WEB-DL.x264-OTHERGROUP.mkv")
    )
    page.config.settings.general.release_group = "MYGROUP"
    page.initializePage()
    assert page.backend.override_tokens["release_group"] == "MYGROUP"

    page.release_group_entry.setText("")
    page.update_generated_name()

    assert page.backend.override_tokens["release_group"] == ""


def _select(combo, text: str) -> None:
    """Pick an entry the way the dropdown does.

    `CustomComboBox` is always editable, and on an editable combo
    `setCurrentText` writes the line edit without moving the index, so the
    `currentIndexChanged` handlers never run.
    """
    index = combo.findText(text)
    assert index > -1, f"{text!r} is not in the combo"
    combo.setCurrentIndex(index)


def _two_episode_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> RenameEncodeSeries:
    """A pack where episode 2 is a repack and episode 1 is not."""
    return _make_series_rename_page(
        tmp_path,
        monkeypatch,
        episode_map={
            Path("Show.S01E01.1080p.WEB-DL.x264-GRP.mkv"): {"season": 1, "episode": 1},
            Path("Show.S01E02.REPACK.1080p.WEB-DL.x264-GRP.mkv"): {
                "season": 1,
                "episode": 2,
            },
        },
    )


def test_each_episode_row_seeds_from_its_own_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case the pack controls cannot express: one combo cannot say
    "REPACK, but only episode 2"."""
    page = _two_episode_page(tmp_path, monkeypatch)

    page.initializePage()

    table = page.episode_claims
    assert page.re_release_combo.currentText() == ""
    assert (
        table.resolved_claims_for(Path("Show.S01E01.1080p.WEB-DL.x264-GRP.mkv")).get(
            "re_release"
        )
        is None
    )
    assert (
        table.resolved_claims_for(Path("Show.S01E02.REPACK.1080p.WEB-DL.x264-GRP.mkv"))[
            "re_release"
        ]
        == "REPACK"
    )


def test_a_pack_claim_leaves_the_episode_rows_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setting the pack control is not a statement about any episode."""
    page = _two_episode_page(tmp_path, monkeypatch)
    page.initializePage()

    _select(page.re_release_combo, "PROPER")

    assert page.backend.override_tokens["re_release"] == "PROPER"
    assert (
        page.episode_claims.resolved_claims_for(
            Path("Show.S01E01.1080p.WEB-DL.x264-GRP.mkv")
        ).get("re_release")
        is None
    )


def test_apply_to_all_stamps_the_pack_value_on_every_episode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _two_episode_page(tmp_path, monkeypatch)
    page.initializePage()
    _select(page.re_release_combo, "PROPER")

    page._apply_claim_to_all("re_release")  # pyright: ignore[reportPrivateUsage]

    claims = page.episode_claims
    for media_file in page.context.media_input.file_list:
        assert claims.resolved_claims_for(media_file)["re_release"] == "PROPER"


def test_revert_to_detected_undoes_an_accidental_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Q7's shortcut has to be survivable when it was a misclick."""
    page = _two_episode_page(tmp_path, monkeypatch)
    page.initializePage()
    _select(page.re_release_combo, "PROPER")
    page._apply_claim_to_all("re_release")  # pyright: ignore[reportPrivateUsage]

    page.episode_claims.revert_to_detected("re_release")

    claims = page.episode_claims
    assert (
        claims.resolved_claims_for(Path("Show.S01E01.1080p.WEB-DL.x264-GRP.mkv")).get(
            "re_release"
        )
        is None
    )
    assert (
        claims.resolved_claims_for(
            Path("Show.S01E02.REPACK.1080p.WEB-DL.x264-GRP.mkv")
        )["re_release"]
        == "REPACK"
    )


def test_a_web_source_suppresses_remux_on_every_episode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A per-file REMUX on a web pack is not a thing, so the column is
    cleared outright rather than parked in hidden state."""
    media_file = Path("Show.S01E01.1080p.BluRay.REMUX.AVC-GRP.mkv")
    page = _make_series_rename_page(
        tmp_path,
        monkeypatch,
        episode_map={media_file: {"season": 1, "episode": 1}},
    )
    page.initializePage()
    assert page.episode_claims.resolved_claims_for(media_file)["remux"] == "REMUX"

    _select(page.quality_combo, "WEB-DL")

    assert page.episode_claims.resolved_claims_for(media_file)["remux"] == ""


def test_returning_to_a_disc_source_restores_the_detected_remux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Suppression has to be survivable. The pack checkbox re-detects when
    the quality comes back, so leaving the episodes suppressed would strand
    them disagreeing with it, invisibly."""
    media_file = Path("Show.S01E01.1080p.BluRay.REMUX.AVC-GRP.mkv")
    page = _make_series_rename_page(
        tmp_path,
        monkeypatch,
        episode_map={media_file: {"season": 1, "episode": 1}},
    )
    page.initializePage()
    _select(page.quality_combo, "WEB-DL")
    assert page.episode_claims.resolved_claims_for(media_file)["remux"] == ""

    _select(page.quality_combo, "BluRay")

    assert page.episode_claims.resolved_claims_for(media_file)["remux"] == "REMUX"
    assert page.remux_checkbox.isChecked() is True


def test_apply_to_all_reads_the_pack_value_from_the_override_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One answer to "what does the pack say", not two. The claim controls
    all write `override_tokens`, so bulk apply reads it rather than asking
    the widgets a second time."""
    page = _two_episode_page(tmp_path, monkeypatch)
    page.initializePage()
    page.backend.override_tokens["re_release"] = "PROPER"

    page._apply_claim_to_all("re_release")  # pyright: ignore[reportPrivateUsage]

    claims = page.episode_claims
    for media_file in page.context.media_input.file_list:
        assert claims.resolved_claims_for(media_file)["re_release"] == "PROPER"


def test_the_pack_name_preview_shows_what_the_pack_controls_produce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pack's controls produce one string, and nothing on the page showed
    it. Setting a pack claim has to move it."""
    page = _two_episode_page(tmp_path, monkeypatch)
    page.config.settings.series.season_folder_token = (
        "{title_clean} S{season_number|zfill(2)} {re_release}"  # noqa: S105 - NFO template token string used as test fixture data, not a credential
    )

    page.initializePage()
    assert page.pack_name_preview.text() == "Show.Title.S01"

    _select(page.re_release_combo, "REPACK")

    assert page.pack_name_preview.text() == "Show.Title.S01.REPACK"


def test_the_pack_preview_does_not_steal_the_override_grid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both renderers assign `backend.token_replacer`. The grid reads it
    expecting the episode's tokens, so the folder render has to come first."""
    page = _two_episode_page(tmp_path, monkeypatch)
    page.config.settings.series.standard_episode_token = TEST_TOKEN

    page.initializePage()
    page.token_override.setText(TEST_TOKEN)
    page.override_group.setChecked(True)

    token_values = page.rename_token_control.get_token_values()
    assert token_values.get("{episode_number}") == "01"


def test_column_widths_do_not_move_when_values_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Widths come from the full option list at construction, not from what
    the cells happen to hold. Sizing to contents made the table reflow when
    a long edition was picked and again when it was cleared."""
    page = _two_episode_page(tmp_path, monkeypatch)
    page.initializePage()
    table = page.episode_claims.table
    before = [table.columnWidth(c) for c in range(table.columnCount())]

    page.episode_claims.apply_to_all("edition", "Directors Cut")
    during = [table.columnWidth(c) for c in range(table.columnCount())]
    page.episode_claims.revert_to_detected("edition")

    assert during == before
    assert [table.columnWidth(c) for c in range(table.columnCount())] == before


def test_every_dropdown_column_shares_one_width(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _two_episode_page(tmp_path, monkeypatch)
    page.initializePage()
    table = page.episode_claims.table

    widths = {table.columnWidth(c) for c in range(1, 6)}

    assert len(widths) == 1


def test_a_switched_off_category_is_not_detected_per_episode_either(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both halves of the page read the same switches. A category the user
    turned off must not come back through the episode table, which is the
    one surface that reads each filename individually."""
    repacked = Path("Show.S01E02.REPACK.1080p.WEB-DL.x264-GRP.mkv")
    page = _make_series_rename_page(
        tmp_path,
        monkeypatch,
        episode_map={repacked: {"season": 1, "episode": 2}},
    )
    page.config.settings.series.claims.re_release = False

    page.initializePage()

    assert page.re_release_combo.currentText() == ""
    assert "re_release" not in page.episode_claims.resolved_claims_for(repacked)


def test_the_master_switch_reaches_the_episode_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media_file = Path("Show.S01E01.IMAX.REPACK.HYBRID.1080p.BluRay.REMUX.AVC-GRP.mkv")
    page = _make_series_rename_page(
        tmp_path,
        monkeypatch,
        episode_map={media_file: {"season": 1, "episode": 1}},
    )
    page.config.settings.series.claims.enabled = False

    page.initializePage()

    resolved = page.episode_claims.resolved_claims_for(media_file)
    assert not {"edition", "frame_size", "re_release", "remux", "hybrid"} & set(
        resolved
    )


def test_a_switched_off_category_is_still_settable_by_hand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Switching a category off means "do not read this from the filename",
    not "this release cannot have one" -- so the column stays editable, the
    way the pack combo stays selectable."""
    media_file = Path("Show.S01E01.1080p.WEB-DL.x264-GRP.mkv")
    page = _make_series_rename_page(
        tmp_path,
        monkeypatch,
        episode_map={media_file: {"season": 1, "episode": 1}},
    )
    page.config.settings.series.claims.re_release = False
    page.initializePage()

    table = page.episode_claims.table
    re_release_column = 1 + [k for k, _ in VALUE_CLAIMS].index("re_release")

    assert table.item(0, re_release_column).flags() & Qt.ItemFlag.ItemIsEditable


def test_streaming_service_is_detected_per_episode_despite_the_master_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The documented asymmetry, pinned so it stays deliberate: service has
    no switch because nothing competes with it, and the settings tooltip
    says so. It is the one column the claim switches never gate."""
    media_file = Path("Show.S01E01.1080p.AMZN.WEB-DL.x264-GRP.mkv")
    page = _make_series_rename_page(
        tmp_path,
        monkeypatch,
        episode_map={media_file: {"season": 1, "episode": 1}},
    )
    page.config.settings.series.claims.enabled = False

    page.initializePage()

    claims = page.episode_claims.resolved_claims_for(media_file)
    assert claims["streaming_service"] == "AMZN"


def _remux_index(page: RenameEncodeSeries, row: int = 0):
    table = page.episode_claims.table
    column = 1 + len(VALUE_CLAIMS)
    return table.model().index(row, column)


def test_clicking_a_remux_cell_toggles_it_both_ways(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard: `index.data(CheckStateRole)` returns a plain int and
    PySide6 enums do not compare equal to ints, so `data(...) ==
    Qt.CheckState.Checked` was always False. The delegate therefore painted
    every box empty and read every cell as unchecked, which turned toggling
    off into a no-op and made bulk apply look broken."""
    media_file = Path("Show.S01E01.1080p.BluRay.x264-GRP.mkv")
    page = _make_series_rename_page(
        tmp_path, monkeypatch, episode_map={media_file: {"season": 1, "episode": 1}}
    )
    page.initializePage()
    claims = page.episode_claims
    model = claims.table.model()
    index = _remux_index(page)

    model.setData(index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert claims.resolved_claims_for(media_file)["remux"] == "REMUX"

    model.setData(index, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert claims.resolved_claims_for(media_file)["remux"] == ""


def test_the_delegate_reads_the_check_state_it_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the delegate paints has to follow the model. This asserts the
    int/enum conversion directly, since a wrong answer here is invisible in
    every other test -- the data is right, only the pixels are wrong."""
    media_file = Path("Show.S01E01.1080p.BluRay.REMUX.AVC-GRP.mkv")
    page = _make_series_rename_page(
        tmp_path, monkeypatch, episode_map={media_file: {"season": 1, "episode": 1}}
    )
    page.initializePage()

    assert _is_checked(_remux_index(page)) is True

    page.episode_claims.apply_to_all("remux", "")

    assert _is_checked(_remux_index(page)) is False


def test_pack_level_apply_to_all_reaches_the_remux_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _two_episode_page(tmp_path, monkeypatch)
    page.initializePage()
    page.remux_checkbox.setChecked(True)

    page._apply_claim_to_all("remux")  # pyright: ignore[reportPrivateUsage]

    claims = page.episode_claims
    for media_file in page.context.media_input.file_list:
        assert claims.resolved_claims_for(media_file)["remux"] == "REMUX"
    assert _is_checked(_remux_index(page, 0))
    assert _is_checked(_remux_index(page, 1))


def test_a_checkbox_cell_never_fills_with_the_selection_colour(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On this palette `highlight()` is the exact colour the checkbox
    indicator is drawn in, so a selected cell painted the box out of
    existence. The episode name column solves it by not being selectable;
    these do the same, and clicking still toggles because `editorEvent`
    reaches enabled items whether or not they can be selected."""
    media_file = Path("Show.S01E01.1080p.BluRay.x264-GRP.mkv")
    page = _make_series_rename_page(
        tmp_path, monkeypatch, episode_map={media_file: {"season": 1, "episode": 1}}
    )
    page.initializePage()
    table = page.episode_claims.table

    for offset in range(2):
        item = table.item(0, 1 + len(VALUE_CLAIMS) + offset)
        assert not item.flags() & Qt.ItemFlag.ItemIsSelectable
        assert item.flags() & Qt.ItemFlag.ItemIsUserCheckable

    # still togglable through the model, which is what a click drives
    index = _remux_index(page)
    table.model().setData(index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert page.episode_claims.resolved_claims_for(media_file)["remux"] == "REMUX"


def test_a_narrow_window_scrolls_rather_than_crushing_the_episode_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The episode name is the only column that stretches, so with no floor
    it absorbs every pixel the claim columns need and collapses to a sliver
    before anything else gives. It floors instead, and the overflow becomes
    the table's own scroll bar -- under the table, where the problem is,
    rather than the wizard's at the bottom of the window."""
    page = _two_episode_page(tmp_path, monkeypatch)
    page.initializePage()
    table = page.episode_claims.table

    page.show()
    try:
        # the column is fitted from the viewport width, which only settles
        # once the layout has actually run
        page.resize(1600, 700)
        QTest.qWait(1)
        wide = table.columnWidth(0)

        page.resize(700, 700)
        QTest.qWait(1)
        narrow = table.columnWidth(0)

        assert wide > narrow, "the episode column should stretch when there is room"
        assert narrow >= 200, "and stop shrinking before it becomes unreadable"
        assert all(table.columnWidth(c) > 0 for c in range(table.columnCount())), (
            "no column may be squeezed out of existence"
        )
        assert table.horizontalScrollBar().isVisible(), (
            "the overflow belongs to the table, not to the page"
        )
    finally:
        page.hide()


def test_the_episode_column_fills_on_open_without_a_resize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fitting from the widget's own `resizeEvent` read a viewport that had
    not been laid out yet, so the column opened at its floor and only found
    its width once the user dragged the window. The viewport's own resize is
    the event that knows the answer."""
    page = _two_episode_page(tmp_path, monkeypatch)
    page.initializePage()
    page.resize(1600, 800)
    page.show()
    try:
        QTest.qWait(1)
        table = page.episode_claims.table

        assert table.columnWidth(0) > 400, "should fill, not sit at its floor"
        assert not table.horizontalScrollBar().isVisible()
    finally:
        page.hide()


def test_the_scroll_bar_does_not_oscillate_across_the_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fitting from a stale viewport width set a column wrong by exactly the
    delta, which the next event corrected -- during a drag that is a scroll
    bar blinking on and off. Sweeping the threshold must cross it once."""
    page = _two_episode_page(tmp_path, monkeypatch)
    page.initializePage()
    page.resize(1150, 800)
    page.show()
    try:
        QTest.qWait(1)
        table = page.episode_claims.table
        seen: list[bool] = []
        for width in range(1150, 950, -10):
            page.resize(width, 800)
            QTest.qWait(1)
            seen.append(table.horizontalScrollBar().isVisible())

        transitions = sum(a != b for a, b in zip(seen, seen[1:], strict=False))
        assert transitions <= 1, f"scroll bar flickered: {seen}"
    finally:
        page.hide()


def test_every_per_file_claim_has_a_column() -> None:
    """The table's columns and the resolver's keys are written out
    separately, so adding a field to `FilenameClaims` would otherwise give it
    a resolved value with nowhere on screen to set it."""
    assert set(CLAIM_COLUMNS) == PER_FILE_CLAIM_KEYS
