from collections.abc import Iterator
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QMessageBox, QTreeWidget, QTreeWidgetItem
import pytest

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.frontend.custom_widgets.series_episode_mapper import SeriesEpisodeMapper
from src.frontend.wizards.series_match import SeriesMatch, _incomplete_mapping_message
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from tests.repo_paths import DEFAULT_CONFIG_DIR


def _make_mapper_with_files(file_list: list[Path]) -> SeriesEpisodeMapper:
    mapper = SeriesEpisodeMapper()
    mapper.media_input_payload = MediaInputPayload(
        input_path=Path("Show Season 1"),
        media_type=MediaType.SERIES,
        file_list=file_list,
    )
    return mapper


def _mapper_without_tvdb_data() -> SeriesEpisodeMapper:
    """A mapper with files but no TVDB episode data loaded."""
    return _make_mapper_with_files([Path("Show.S01E01.mkv")])


def _mapper_with_tvdb_data() -> SeriesEpisodeMapper:
    """A mapper with files and TVDB episode data loaded, ready to match.

    Goes through the real ``_load_episode_data()`` path (driven by a
    ``media_search_payload.tvdb_data`` shape, rather than poking
    ``available_episodes`` directly) so ``episode_items`` and
    ``episodes_tree`` are populated exactly as they would be in the app --
    tests that need the tree to actually contain rows (e.g. to exercise its
    paint sites) rely on this.
    """
    mapper = _make_mapper_with_files(
        [Path("Show.S01E01.mkv"), Path("Show.S01E02.mkv"), Path("Show.Bonus.mkv")]
    )
    mapper.media_search_payload = MediaSearchPayload(
        media_type=MediaType.SERIES,
        title="Show",
        tvdb_data={
            "episodes_by_type": {
                0: {
                    "type_name": "Aired Order",
                    "type": "official",
                    "episodes": [
                        {"seasonNumber": 1, "number": 1, "name": "Pilot"},
                        {"seasonNumber": 1, "number": 2, "name": "Second Episode"},
                        {"seasonNumber": 1, "number": 3, "name": "Third Episode"},
                    ],
                }
            }
        },
    )
    mapper._load_episode_data()
    return mapper


def _iter_tree_items(item: QTreeWidgetItem) -> Iterator[QTreeWidgetItem]:
    """Yield ``item`` and every descendant, depth-first."""
    yield item
    for child_index in range(item.childCount()):
        yield from _iter_tree_items(item.child(child_index))  # type: ignore[reportArgumentType]


def _all_tree_items(tree: QTreeWidget) -> list[QTreeWidgetItem]:
    items: list[QTreeWidgetItem] = []
    for top_index in range(tree.topLevelItemCount()):
        top_item = tree.topLevelItem(top_index)
        if top_item is not None:
            items.extend(_iter_tree_items(top_item))
    return items


def test_incomplete_mapping_message_when_tvdb_has_no_episodes() -> None:
    # TVDB returned no episode data at all and the file is still unmapped --
    # the user needs to know they must enter season/episode manually rather
    # than just "finish mapping"
    mapper = _make_mapper_with_files([Path("Show.S01E01.mkv")])

    message = _incomplete_mapping_message(mapper)

    assert "TVDB returned no episode data" in message
    assert "manually" in message


def test_incomplete_mapping_message_for_plain_unmapped_files_with_tvdb_data() -> None:
    # TVDB has episode data, but the user simply hasn't finished mapping
    # every file yet -- this must use the generic "finish mapping" message
    mapper = _make_mapper_with_files([Path("Show.S01E01.mkv"), Path("Show.S01E02.mkv")])
    mapper.episodes_by_type = {
        0: {
            "type_name": "Aired Order",
            "episodes": [{"seasonNumber": 1, "number": 1}],
        }
    }
    mapper.file_episode_mappings = {
        Path("Show.S01E01.mkv"): {"season": 1, "episode": 1}
    }

    message = _incomplete_mapping_message(mapper)

    assert "TVDB returned no episode data" not in message
    assert "properly mapped" in message


def test_incomplete_mapping_message_for_duplicate_targets_with_tvdb_data() -> None:
    # is_valid() also fails when every file IS mapped but two files target
    # the same episode. has_unmapped_files() is False in that case, so the
    # "enter manually" message must not apply even without TVDB data.
    mapper = _make_mapper_with_files([Path("a.mkv"), Path("b.mkv")])
    mapper.file_episode_mappings = {
        Path("a.mkv"): {"season": 1, "episode": 1},
        Path("b.mkv"): {"season": 1, "episode": 1},
    }
    assert mapper.is_valid() is False
    assert mapper.has_unmapped_files() is False

    message = _incomplete_mapping_message(mapper)

    assert "TVDB returned no episode data" not in message
    assert "properly mapped" in message


def test_manual_episode_edit_preserves_a_multi_episode_range() -> None:
    file_path = Path("Show.S01E01E02.mkv")
    mapper = _make_mapper_with_files([file_path])
    mapper._populate_files_table()
    mapper.available_episodes = {
        1: {
            1: {"seasonNumber": 1, "number": 1, "name": "Part One"},
            2: {"seasonNumber": 1, "number": 2, "name": "Part Two"},
        }
    }
    mapper.file_episode_mappings[file_path] = {
        "season": 1,
        "episode": 1,
        "episode_end": 2,
        "episode_data": mapper.available_episodes[1][1],
    }

    mapper.files_table.blockSignals(True)
    mapper.files_table.item(0, 1).setText("1")  # type: ignore[OptionalMemberAccess]
    mapper.files_table.item(0, 2).setText("1")  # type: ignore[OptionalMemberAccess]
    mapper.files_table.blockSignals(False)
    mapper._on_table_item_changed(mapper.files_table.item(0, 2))  # type: ignore[reportArgumentType]

    assert mapper.file_episode_mappings[file_path]["episode_end"] == 2


def test_get_episode_map_returns_a_copy() -> None:
    file_path = Path("Show.S01E01.mkv")
    mapper = _make_mapper_with_files([file_path])
    mapper.file_episode_mappings[file_path] = {"season": 1, "episode": 1}

    returned = mapper.get_episode_map()
    returned.clear()

    assert file_path in mapper.file_episode_mappings


def test_re_match_all_reports_when_there_is_no_episode_data(
    qapp: QCoreApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The button must not be a silent no-op."""
    mapper = _mapper_without_tvdb_data()
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, title, text: shown.append((title, text)),
    )

    mapper._on_re_match_all_clicked()

    assert len(shown) == 1
    assert "TVDB" in shown[0][1]


def test_re_match_all_stays_silent_when_episode_data_exists(
    qapp: QCoreApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard must not fire on the normal path."""
    mapper = _mapper_with_tvdb_data()
    shown: list[object] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: shown.append(a))

    mapper._on_re_match_all_clicked()

    assert shown == []


def test_load_data_stays_silent_when_there_is_no_episode_data(
    qapp: QCoreApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard.

    ``load_data()`` runs on every page visit (``SeriesMatch.initializePage``),
    not just on a button click. A series with no TVDB episode data is an
    anticipated case that already gets a calm inline warning
    (``NO_TVDB_EPISODE_DATA_MESSAGE`` on ``episodes_stats_label``); it must
    not also pop a blocking modal on every Back/Next revisit.
    """
    mapper = _mapper_without_tvdb_data()
    media_search_payload = MediaSearchPayload(media_type=MediaType.SERIES, title="Show")
    shown: list[object] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: shown.append(a))

    assert mapper.media_input_payload is not None
    mapper.load_data(mapper.media_input_payload, media_search_payload)

    assert shown == []


def test_episode_order_changed_stays_silent_when_there_is_no_episode_data(
    qapp: QCoreApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard: changing TVDB order must not pop a modal either."""
    mapper = _mapper_without_tvdb_data()
    shown: list[object] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: shown.append(a))

    mapper._on_episode_order_changed("")

    assert shown == []


def test_every_coloured_cell_also_sets_a_foreground(qapp: QCoreApplication) -> None:
    """A background without a foreground is unreadable on the dark theme.

    Asserts the invariant across the real widget rather than per call site,
    so a future site added without a foreground fails this too. Covers both
    the files table and the episodes tree, and drives auto-match plus both
    manual-edit branches (matched and unverified) so more than one paint
    site is actually exercised, not just the confidence column.

    ``_populate_files_table`` alone never paints a cell -- coloring happens
    in ``_auto_match_files`` (and other assignment paths), so both are
    driven here to actually exercise the invariant rather than iterating an
    always-uncoloured table.
    """
    mapper = _mapper_with_tvdb_data()
    mapper._populate_files_table()
    mapper._auto_match_files()

    # Row 2 ("Show.Bonus.mkv") has no parseable season/episode, so auto-match
    # leaves it unassigned. Manually enter a season/episode that DOES exist
    # in available_episodes -- this exercises the "manual edit matched TVDB"
    # paint site (distinct from the auto-match confidence colours above).
    table = mapper.files_table
    row_2_season = table.item(2, 1)
    row_2_episode = table.item(2, 2)
    assert row_2_season is not None
    assert row_2_episode is not None
    table.blockSignals(True)
    row_2_season.setText("1")
    row_2_episode.setText("3")
    table.blockSignals(False)
    mapper._on_table_item_changed(row_2_episode)

    # Row 0 was auto-matched; overwrite it with a season/episode that does
    # NOT exist in available_episodes to exercise the "manual edit
    # unverified" (amber) paint site.
    row_0_season = table.item(0, 1)
    row_0_episode = table.item(0, 2)
    assert row_0_season is not None
    assert row_0_episode is not None
    table.blockSignals(True)
    row_0_season.setText("9")
    row_0_episode.setText("9")
    table.blockSignals(False)
    mapper._on_table_item_changed(row_0_episode)

    coloured_in_table = 0
    for row in range(table.rowCount()):
        for column in range(table.columnCount()):
            item = table.item(row, column)
            if item is None:
                continue
            background = item.background()
            if background.style() == Qt.BrushStyle.NoBrush:
                continue
            if background.color().alpha() == 0:
                continue
            coloured_in_table += 1
            assert item.foreground().style() != Qt.BrushStyle.NoBrush, (
                f"files_table cell ({row}, {column}) sets a background with no foreground"
            )

    coloured_in_tree = 0
    tree = mapper.episodes_tree
    for tree_item in _all_tree_items(tree):
        for column in range(tree.columnCount()):
            background = tree_item.background(column)
            if background.style() == Qt.BrushStyle.NoBrush:
                continue
            if background.color().alpha() == 0:
                continue
            coloured_in_tree += 1
            assert tree_item.foreground(column).style() != Qt.BrushStyle.NoBrush, (
                f"episodes_tree cell (item={tree_item.text(0)!r}, column={column}) "
                "sets a background with no foreground"
            )

    assert coloured_in_table > 0, (
        "no files_table cell was coloured -- this test would otherwise pass "
        "vacuously for that surface"
    )
    assert coloured_in_tree > 0, (
        "no episodes_tree cell was coloured -- this test would otherwise "
        "pass vacuously for that surface"
    )


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


def _make_series_match_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_list: list[Path],
    mappings: dict[Path, dict[str, object]],
) -> SeriesMatch:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    manager = ConfigManager("test", _paths(tmp_path))
    media_input = MediaInputPayload(
        input_path=Path("Show Season 1"),
        media_type=MediaType.SERIES,
        file_list=file_list,
        # BaseWizardPage.validatePage() insists on a working dir, which the
        # media-input page sets long before this one runs
        working_dir=tmp_path / "working",
    )
    media_search = MediaSearchPayload(media_type=MediaType.SERIES, title="Show")
    context = ProcessingContext(media_input=media_input, media_search=media_search)

    page = SeriesMatch(config=manager, context=context, parent=None)  # type: ignore[reportArgumentType]
    page.series_mapper.media_input_payload = media_input
    page.series_mapper.file_episode_mappings = mappings
    return page


def test_validate_page_blocks_an_unresolvable_episode_number(
    qapp: QCoreApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """is_valid() passes a lone file whose episode is None -- its duplicate
    check has nothing to collide with -- and a date-based filename gives the
    parsing fallback nothing to recover. That combination used to reach the
    uploader with season_number/episode_number silently absent from the
    payload, which UNIT3D rejects."""
    file_path = Path("The.Daily.Show.2024.01.15.1080p.WEB.h264-GROUP.mkv")
    page = _make_series_match_page(
        tmp_path,
        monkeypatch,
        [file_path],
        {file_path: {"season": None, "episode": None}},
    )
    assert page.series_mapper.is_valid() is True

    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, text: shown.append((title, text)),
    )

    assert page.validatePage() is False
    assert len(shown) == 1
    assert "season number and episode number" in shown[0][1]


def test_validate_page_allows_a_normally_mapped_episode(
    qapp: QCoreApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard must not fire on the normal path."""
    file_path = Path("Show.S01E01.mkv")
    page = _make_series_match_page(
        tmp_path, monkeypatch, [file_path], {file_path: {"season": 1, "episode": 1}}
    )

    shown: list[object] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: shown.append(a))

    assert page.validatePage() is True
    assert shown == []
    assert page.context.media_input.series_episode_map == {
        file_path: {"season": 1, "episode": 1}
    }


def test_validate_page_blocks_absolute_numbered_anime_with_no_season(
    qapp: QCoreApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Absolute-numbered anime carries an episode but no season, and the
    bracketed release-group form gives the parsing fallback no season either.
    Only the season is missing, so the message must say so and not also demand
    an episode number the release already has."""
    file_path = Path("[Group] Anime Title - 087 [1080p][HEVC].mkv")
    page = _make_series_match_page(
        tmp_path,
        monkeypatch,
        [file_path],
        {file_path: {"season": None, "episode": 87}},
    )

    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, text: shown.append((title, text)),
    )

    assert page.validatePage() is False
    assert len(shown) == 1
    assert "the season number for this release" in shown[0][1]
    assert "and episode number" not in shown[0][1]
