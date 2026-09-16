from collections.abc import Iterator
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QMessageBox, QTreeWidget, QTreeWidgetItem
import pytest

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.enums.series import EpisodeFormat
from src.frontend.custom_widgets.series_episode_mapper import SeriesEpisodeMapper
from src.frontend.wizards.series_match import SeriesMatch, _incomplete_mapping_message
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from tests.repo_paths import build_app_paths


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


def test_incomplete_mapping_message_names_the_unmapped_files() -> None:
    # TVDB has episode data, but the user hasn't finished mapping every file.
    # Saying "ensure all files are properly mapped" named nothing and left the
    # user to find the gap by eye, so the message must list the files.
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
    assert "Show.S01E02.mkv" in message
    assert "Show.S01E01.mkv" not in message


def test_incomplete_mapping_message_names_both_files_claiming_one_episode() -> None:
    # is_valid() also fails when every file IS mapped but two files target the
    # same episode. That case reached the user as "ensure all files are
    # properly mapped" with every row on screen filled in -- it has to name
    # the episode and the files fighting over it instead.
    mapper = _make_mapper_with_files([Path("a.mkv"), Path("b.mkv")])
    mapper.file_episode_mappings = {
        Path("a.mkv"): {"season": 1, "episode": 1},
        Path("b.mkv"): {"season": 1, "episode": 1},
    }
    assert mapper.is_valid() is False
    assert mapper.has_unmapped_files() is False

    message = _incomplete_mapping_message(mapper)

    assert "TVDB returned no episode data" not in message
    assert "S01E01" in message
    assert "a.mkv" in message
    assert "b.mkv" in message


def test_incomplete_mapping_message_names_a_span_overlapping_a_single_episode() -> None:
    # The start numbers differ, so only expanding the span catches this: the
    # two-episode file and the single-episode file both claim S01E02.
    mapper = _make_mapper_with_files([Path("span.mkv"), Path("single.mkv")])
    mapper.file_episode_mappings = {
        Path("span.mkv"): {"season": 1, "episode": 1, "episode_list": [1, 2]},
        Path("single.mkv"): {"season": 1, "episode": 2},
    }
    assert mapper.is_valid() is False

    message = _incomplete_mapping_message(mapper)

    assert "S01E02" in message
    assert "span.mkv" in message
    assert "single.mkv" in message


def _span_mapper() -> tuple[SeriesEpisodeMapper, Path]:
    file_path = Path("Show.S01E01E02.mkv")
    mapper = _make_mapper_with_files([file_path])
    mapper._populate_files_table()
    mapper.available_episodes = {
        1: {
            1: {"seasonNumber": 1, "number": 1, "name": "Part One"},
            2: {"seasonNumber": 1, "number": 2, "name": "Part Two"},
        }
    }
    mapper._auto_match_files()
    return mapper, file_path


def test_editing_the_season_of_a_span_keeps_the_span() -> None:
    """Touching one field must not silently narrow the row."""
    mapper, file_path = _span_mapper()
    assert mapper.files_table.item(0, mapper.COL_EPISODE).text() == "1-2"  # type: ignore[OptionalMemberAccess]

    mapper.files_table.item(0, mapper.COL_SEASON).setText("2")  # type: ignore[OptionalMemberAccess]

    mapping = mapper.file_episode_mappings[file_path]
    assert mapping["season"] == 2
    assert mapping["episode_end"] == 2


def test_a_span_can_be_narrowed_to_a_single_episode() -> None:
    """The cell means what it says.

    ``episode_end`` used to be carried forward under whatever was typed, so
    a span detected from the filename could never be corrected -- retyping
    the episode left the row still claiming the episode after it.
    """
    mapper, file_path = _span_mapper()

    mapper.files_table.item(0, mapper.COL_EPISODE).setText("1")  # type: ignore[OptionalMemberAccess]

    mapping = mapper.file_episode_mappings[file_path]
    assert mapping["episode_end"] is None
    assert mapping["episode_list"] == [1]


def test_a_typed_title_override_reaches_the_mapping() -> None:
    mapper, file_path = _span_mapper()

    mapper.files_table.item(0, mapper.COL_TITLE).setText("Lost & Found")  # type: ignore[OptionalMemberAccess]

    assert (
        mapper.file_episode_mappings[file_path]["episode_title_override"]
        == "Lost & Found"
    )


def _loaded_mapper(
    file_list: list[Path],
    episodes: list[dict[str, object]],
    series_episode_map: dict[Path, dict[str, object]] | None = None,
) -> SeriesEpisodeMapper:
    """A mapper driven through the real ``load_data`` entry point."""
    media_input = MediaInputPayload(
        input_path=Path("Show Season 1"),
        media_type=MediaType.SERIES,
        file_list=file_list,
    )
    if series_episode_map is not None:
        media_input.series_episode_map = series_episode_map  # type: ignore[assignment]
    media_search = MediaSearchPayload(
        media_type=MediaType.SERIES,
        title="Show",
        tvdb_data={
            "episodes_by_type": {
                1: {
                    "type_name": "Aired Order",
                    "type": "official",
                    "episodes": episodes,
                }
            }
        },
    )
    mapper = SeriesEpisodeMapper()
    mapper.load_data(media_input, media_search)
    return mapper


def _aired(count: int) -> list[dict[str, object]]:
    return [
        {"seasonNumber": 1, "number": number, "name": f"Episode {number} Title"}
        for number in range(1, count + 1)
    ]


def test_a_multi_episode_file_marks_every_episode_it_covers_assigned() -> None:
    """A file covering two episodes leaves neither unassigned.

    Counting only the span's first episode reported "1/2 assigned" with the
    second painted unassigned -- a gap the user has no second file to fill
    and cannot act on, while validation was already satisfied.
    """
    mapper = _loaded_mapper([Path("Show.S01E01-E02.mkv")], _aired(2))

    assert mapper.is_valid() is True
    assert [item.episode for item in mapper.episode_items if not item.is_assigned] == []
    assert "2/2 assigned" in mapper.episodes_tree.topLevelItem(0).text(0)  # type: ignore[OptionalMemberAccess]


def test_a_parsed_episode_the_ordering_lacks_is_kept_and_flagged() -> None:
    """The filename states S01E03 plainly; the ordering stops at 2.

    Discarding it left the row blank and handed the file to fuzzy matching,
    which bound it to whichever title scored best -- in a full pack that is
    an episode another file already claims, so the pack failed to validate
    with every cell on screen filled in.
    """
    third = Path("Show.S01E03.mkv")
    mapper = _loaded_mapper([Path("Show.S01E01.mkv"), third], _aired(2))

    mapping = mapper.file_episode_mappings[third]

    assert mapping["episode"] == 3
    assert mapping["verified"] is False
    assert mapping["episode_data"] == {
        "season": 1,
        "episode": 3,
        "name": None,
        "aired": None,
    }
    assert mapper.is_valid() is True


def test_re_entering_the_page_keeps_a_hand_typed_mapping() -> None:
    """``initializePage`` calls ``load_data`` again on every visit.

    Repopulating the table wrote every cell blank with signals live, which
    deleted each row's mapping on the way past, and auto-matching then
    recomputed the very answer the user had corrected.
    """
    file_list = [Path("Show.S01E01.mkv"), Path("Show.S01E02.mkv")]
    episodes = _aired(2)
    media_input = MediaInputPayload(
        input_path=Path("Show Season 1"),
        media_type=MediaType.SERIES,
        file_list=file_list,
    )
    media_search = MediaSearchPayload(
        media_type=MediaType.SERIES,
        title="Show",
        tvdb_data={
            "episodes_by_type": {
                1: {
                    "type_name": "Aired Order",
                    "type": "official",
                    "episodes": episodes,
                }
            }
        },
    )
    mapper = SeriesEpisodeMapper()
    mapper.load_data(media_input, media_search)

    mapper.files_table.item(1, 2).setText("1")  # type: ignore[OptionalMemberAccess]
    assert mapper.file_episode_mappings[file_list[1]]["episode"] == 1

    mapper.load_data(media_input, media_search)

    assert mapper.file_episode_mappings[file_list[1]]["episode"] == 1
    assert mapper.files_table.item(1, 2).text() == "1"  # type: ignore[OptionalMemberAccess]


def test_a_committed_episode_map_is_adopted_on_load() -> None:
    """A resumed job carries its mapping on the payload, not in the widget."""
    file_path = Path("Show.S01E01.mkv")
    mapper = _loaded_mapper(
        [file_path],
        _aired(2),
        series_episode_map={
            file_path: {
                "season": 1,
                "episode": 2,
                "episode_name": "Chosen Earlier",
                "assignment_method": "manual",
                "confidence": 1.0,
            }
        },
    )

    mapping = mapper.file_episode_mappings[file_path]

    assert mapping["episode"] == 2
    assert mapping["episode_name"] == "Chosen Earlier"
    assert mapper.files_table.item(0, 2).text() == "2"  # type: ignore[OptionalMemberAccess]


def test_re_match_all_still_discards_the_current_answers() -> None:
    """Preserving edits on load must not disarm the explicit re-match."""
    file_path = Path("Show.S01E01.mkv")
    mapper = _loaded_mapper([file_path], _aired(2))
    mapper.files_table.item(0, 2).setText("2")  # type: ignore[OptionalMemberAccess]
    assert mapper.file_episode_mappings[file_path]["episode"] == 2

    mapper._on_re_match_all_clicked()

    assert mapper.file_episode_mappings[file_path]["episode"] == 1


#: TVDB aired order for the pack in issues.md, and the same season with the
#: two-part premiere merged into one entry -- which shifts every later
#: episode down by one while still containing an episode 3, so the numbers
#: alone cannot tell the two apart.
_PRODIGY_AIRED = [
    "Lost & Found (1)",
    "Lost & Found (2)",
    "Starstruck",
    "Dream Catcher",
    "Terror Firma",
]
_PRODIGY_MERGED = ["Lost & Found"] + _PRODIGY_AIRED[2:]


def _named_episodes(names: list[str]) -> list[dict[str, object]]:
    return [
        {"seasonNumber": 1, "number": index, "name": name}
        for index, name in enumerate(names, start=1)
    ]


def _prodigy_files() -> list[Path]:
    return [
        Path("Star.Trek.Prodigy.S01E01-E02.Lost-Found.BluRay.1080p.x264-G.mkv"),
        Path("Star.Trek.Prodigy.S01E03.Starstruck.BluRay.1080p.x264-G.mkv"),
        Path("Star.Trek.Prodigy.S01E04.Dream.Catcher.BluRay.1080p.x264-G.mkv"),
        Path("Star.Trek.Prodigy.S01E05.Terror.Firma.BluRay.1080p.x264-G.mkv"),
    ]


def _mapper_with_orderings(
    file_list: list[Path], episodes_by_type: dict[object, dict[str, object]]
) -> SeriesEpisodeMapper:
    media_input = MediaInputPayload(
        input_path=Path("Star Trek Prodigy S01"),
        media_type=MediaType.SERIES,
        file_list=file_list,
    )
    media_search = MediaSearchPayload(
        media_type=MediaType.SERIES,
        title="Star Trek: Prodigy",
        tvdb_data={"episodes_by_type": episodes_by_type},
    )
    mapper = SeriesEpisodeMapper()
    mapper.load_data(media_input, media_search)
    return mapper


def test_the_ordering_that_fits_the_filenames_is_preselected() -> None:
    """Taking whichever ordering came first was not a choice.

    Every ordering of a season has an episode 3, so a pack numbered against
    one binds cleanly to another and renames every file after the first
    divergence -- silently, and at full confidence.
    """
    mapper = _mapper_with_orderings(
        _prodigy_files(),
        {
            2: {
                "type_name": "DVD Order",
                "type": "dvd",
                "episodes": _named_episodes(_PRODIGY_MERGED),
            },
            1: {
                "type_name": "Aired Order",
                "type": "official",
                "episodes": _named_episodes(_PRODIGY_AIRED),
            },
        },
    )

    assert mapper.episode_order_combo.currentData() == 1
    assert "Aired Order" in mapper.episode_order_combo.currentText()
    # and the evidence it was chosen on is on the item, not hidden
    assert "matched" in mapper.episode_order_combo.currentText()


def test_the_matched_episode_column_names_what_each_row_bound_to() -> None:
    """A right-looking number pointing at the wrong episode is the failure."""
    mapper = _mapper_with_orderings(
        _prodigy_files(),
        {
            1: {
                "type_name": "Aired Order",
                "type": "official",
                "episodes": _named_episodes(_PRODIGY_AIRED),
            }
        },
    )

    matched = [
        mapper.files_table.item(row, mapper.COL_MATCHED).text()  # type: ignore[OptionalMemberAccess]
        for row in range(mapper.files_table.rowCount())
    ]

    assert matched[0].startswith("S01E01-E02")
    assert "Lost & Found" in matched[0]
    assert "S01E03" in matched[1] and "Starstruck" in matched[1]


def test_a_pack_disagreeing_with_its_ordering_is_reported_once() -> None:
    """Twelve amber rows are one ordering problem, not twelve row problems."""
    mapper = _mapper_with_orderings(
        _prodigy_files(),
        {
            1: {
                "type_name": "Aired Order",
                "type": "official",
                "episodes": _named_episodes(_PRODIGY_AIRED),
            },
            2: {
                "type_name": "DVD Order",
                "type": "dvd",
                "episodes": _named_episodes(_PRODIGY_MERGED),
            },
        },
    )
    assert mapper.title_warning_label.isHidden() is True

    # the user overrides the fitted choice for the merged ordering
    mapper.episode_order_combo.setCurrentIndex(1)

    assert mapper.title_warning_label.isHidden() is False
    assert "DVD Order" in mapper.title_warning_label.text()
    methods = {
        mapper.files_table.item(row, mapper.COL_METHOD).text()  # type: ignore[OptionalMemberAccess]
        for row in range(mapper.files_table.rowCount())
    }
    assert any("title ->" in method for method in methods)


def test_relabelling_the_order_combo_does_not_clear_assignments() -> None:
    """The item labels carry the fit evidence and are rewritten on load.

    Keyed on text, that relabelling read as the user picking a different
    ordering and cleared every assignment.
    """
    files = _prodigy_files()
    episodes_by_type = {
        1: {
            "type_name": "Aired Order",
            "type": "official",
            "episodes": _named_episodes(_PRODIGY_AIRED),
        }
    }
    mapper = _mapper_with_orderings(files, episodes_by_type)
    assert len(mapper.file_episode_mappings) == len(files)

    mapper._setup_episode_order_combo_from_data()

    assert len(mapper.file_episode_mappings) == len(files)


def test_changing_the_ordering_keeps_what_the_user_typed() -> None:
    """Only which episode a number names changes with the ordering.

    Clearing every assignment first threw away the user's own answers to
    recompute something they had already corrected.
    """
    files = _prodigy_files()
    mapper = _mapper_with_orderings(
        files,
        {
            1: {
                "type_name": "Aired Order",
                "type": "official",
                "episodes": _named_episodes(_PRODIGY_AIRED),
            },
            2: {
                "type_name": "DVD Order",
                "type": "dvd",
                "episodes": _named_episodes(_PRODIGY_MERGED),
            },
        },
    )
    mapper.files_table.item(3, mapper.COL_EPISODE).setText("4-5")  # type: ignore[OptionalMemberAccess]
    assert mapper.file_episode_mappings[files[3]]["episode_list"] == [4, 5]

    mapper.episode_order_combo.setCurrentIndex(1)

    assert mapper.file_episode_mappings[files[3]]["episode_list"] == [4, 5]


def test_dvd_order_selects_the_dvd_naming_format() -> None:
    """The enum existed but was not offered, so the choice did nothing."""
    mapper = _mapper_with_orderings(
        _prodigy_files(),
        {
            1: {
                "type_name": "Aired Order",
                "type": "official",
                "episodes": _named_episodes(_PRODIGY_AIRED),
            },
            2: {
                "type_name": "DVD Order",
                "type": "dvd",
                "episodes": _named_episodes(_PRODIGY_MERGED),
            },
        },
    )
    assert mapper.get_series_format() is EpisodeFormat.STANDARD

    mapper.episode_order_combo.setCurrentIndex(1)

    assert mapper.get_series_format() is EpisodeFormat.DVD


def test_fuzzy_matching_cannot_take_an_episode_another_file_holds() -> None:
    """This is how a full pack manufactured its own overlap.

    A file whose number the ordering does not list has only its title left
    to match on, and in a complete pack the best-scoring episode is one some
    other file already covers -- so the pack failed to validate.
    """
    taken = Path("Show.S01E01.Pilot.mkv")
    stray = Path("Show.S01E09.Pilot.Again.mkv")
    mapper = _loaded_mapper([taken, stray], _aired(2))

    assert mapper.file_episode_mappings[taken]["episode"] == 1
    # the stray keeps its own parsed number instead of being put on episode 1
    assert mapper.file_episode_mappings[stray]["episode"] == 9
    assert mapper.is_valid() is True


def test_validation_selects_the_first_row_that_needs_fixing() -> None:
    """Naming the files still leaves them to be found in a long list."""
    files = _prodigy_files()
    mapper = _mapper_with_orderings(
        files,
        {
            1: {
                "type_name": "Aired Order",
                "type": "official",
                "episodes": _named_episodes(_PRODIGY_AIRED),
            }
        },
    )
    mapper.files_table.item(2, mapper.COL_EPISODE).setText("")  # type: ignore[OptionalMemberAccess]
    assert mapper.is_valid() is False

    mapper.focus_first_problem()

    assert mapper.files_table.currentRow() == 2


def test_fuzzy_matching_maps_a_file_named_for_a_whole_two_part_story() -> None:
    """Title matching could only ever answer with one episode.

    A release ships a two-part premiere as one file while the provider lists
    it as two, so matching the first half left the second with no file to
    give it -- and no way to say the one file covered both.
    """
    whole = Path("Star.Trek.Prodigy.Lost.and.Found.1080p.BluRay.x264-G.mkv")
    mapper = _mapper_with_orderings(
        [whole, Path("Star.Trek.Prodigy.Starstruck.1080p.BluRay.x264-G.mkv")],
        {
            1: {
                "type_name": "Aired Order",
                "type": "official",
                "episodes": _named_episodes(_PRODIGY_AIRED),
            }
        },
    )

    mapping = mapper.file_episode_mappings[whole]

    assert mapping["episode_list"] == [1, 2]
    assert mapping["episode_end"] == 2
    assert mapping["assignment_method"] == "fuzzy"
    assert mapper.is_valid() is True


def test_fuzzy_matching_keeps_the_parts_of_a_story_apart() -> None:
    """Releases write "A.Moral.Star.1" with no season and no "part".

    GuessIt reads that trailing 1 as an episode number, leaving a title with
    no part marker in it -- so the number has to be carried through as the
    part it actually is, or both files match the whole story and collide.
    """
    first = Path("Star.Trek.Prodigy.A.Moral.Star.1.1080p.BluRay.x264-G.mkv")
    second = Path("Star.Trek.Prodigy.A.Moral.Star.2.1080p.BluRay.x264-G.mkv")
    mapper = _mapper_with_orderings(
        [first, second],
        {
            1: {
                "type_name": "Aired Order",
                "type": "official",
                "episodes": [
                    {"seasonNumber": 1, "number": 9, "name": "A Moral Star (1)"},
                    {"seasonNumber": 1, "number": 10, "name": "A Moral Star (2)"},
                ],
            }
        },
    )

    assert mapper.file_episode_mappings[first]["episode_list"] == [9]
    assert mapper.file_episode_mappings[second]["episode_list"] == [10]
    assert mapper.is_valid() is True


def test_a_title_resolves_an_episode_number_the_ordering_does_not_list() -> None:
    """Where the numbering and the provider genuinely disagree, the title is
    the better evidence -- but only a strong one, since it overrides a number
    the filename states plainly."""
    mismatched = Path("Star.Trek.Prodigy.S01E97.Starstruck.1080p.BluRay.x264-G.mkv")
    unknown = Path("Star.Trek.Prodigy.S01E98.Nothing.Like.It.1080p.BluRay.x264-G.mkv")
    mapper = _mapper_with_orderings(
        [mismatched, unknown],
        {
            1: {
                "type_name": "Aired Order",
                "type": "official",
                "episodes": _named_episodes(_PRODIGY_AIRED),
            }
        },
    )

    assert mapper.file_episode_mappings[mismatched]["episode"] == 3
    assert mapper.file_episode_mappings[mismatched]["assignment_method"] == "title"
    # nothing matched it, so its own numbers stand rather than being guessed at
    assert mapper.file_episode_mappings[unknown]["episode"] == 98
    assert mapper.file_episode_mappings[unknown]["verified"] is False


def test_the_episode_title_comes_from_the_filename_not_its_directory() -> None:
    """GuessIt was handed the whole path, so the folders competed for it.

    For a pack inside a folder carrying its own release info, the grandparent
    was read as the show and every file's episode title came back as the
    containing directory's name -- the same wrong value for the whole pack,
    invisible until fuzzy matching read it.
    """
    parsed = SeriesEpisodeMapper._parse_file(
        Path(
            "C:/Users/someone/Downloads/Show.S01.BluRay.1080p.x264-G/Show.S01E03.Starstruck.1080p.mkv"
        )
    )

    assert parsed["episode_title"] == "Starstruck"
    assert parsed["season"] == 1
    assert parsed["episode"] == 3


def test_a_season_carried_only_by_a_parent_folder_is_still_found() -> None:
    """Nested packs keep bare filenames under a ``Season NN`` directory."""
    parsed = SeriesEpisodeMapper._parse_file(Path("X:/Show/Season 02/ep05.mkv"))

    assert parsed["season"] == 2
    assert parsed["episode"] == 5


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
    return build_app_paths(tmp_path)


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
