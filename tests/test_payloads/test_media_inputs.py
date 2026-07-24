from pathlib import Path

from src.enums.media_type import MediaType
from src.packages.custom_types import ComparisonPair
from src.payloads.media_inputs import MediaInputPayload

SOURCE = Path("C:/enc/Movie.2016.remux.mkv")
OLD = Path("C:/enc/Movie.2016.BluRay.1080p-old.mkv")
NEW = Path("C:/enc/Movie.2016.1080p.BluRay.x264-GRP.mkv")


def _movie_payload() -> MediaInputPayload:
    return MediaInputPayload(
        input_path=OLD,
        media_type=MediaType.MOVIE,
        file_list=[OLD],
        file_list_mediainfo={OLD: "mi-encode", SOURCE: "mi-source"},  # type: ignore[dict-item]
        file_list_rename_map={OLD: NEW},
        comparison_pair=ComparisonPair(source=SOURCE, media=OLD, script=None),
    )


def test_apply_rename_mapping_updates_file_list_and_mediainfo() -> None:
    payload = _movie_payload()

    payload.apply_rename_mapping({OLD: NEW})

    assert payload.file_list == [NEW]
    assert payload.file_list_mediainfo == {NEW: "mi-encode", SOURCE: "mi-source"}
    assert payload.file_list_rename_map == {}


def test_apply_rename_mapping_repoints_comparison_pair_media() -> None:
    """Regression guard: the comparison pair kept the pre-rename media path
    while `file_list_mediainfo` was rekeyed to the renamed path, so the
    screenshots page raised `KeyError` on `mi_list[comp_pair.media]`."""
    payload = _movie_payload()

    payload.apply_rename_mapping({OLD: NEW})

    comp_pair = payload.comparison_pair
    assert comp_pair
    assert comp_pair.media == NEW
    # the comparison source is not renamed, so it stays put
    assert comp_pair.source == SOURCE
    # both halves of the pair must resolve against the rekeyed MediaInfo dict
    assert payload.file_list_mediainfo[comp_pair.media]
    assert payload.file_list_mediainfo[comp_pair.source]


def test_apply_rename_mapping_preserves_comparison_script() -> None:
    script = Path("C:/enc/compare.vpy")
    payload = _movie_payload()
    payload.comparison_pair = ComparisonPair(source=SOURCE, media=OLD, script=script)

    payload.apply_rename_mapping({OLD: NEW})

    assert payload.comparison_pair
    assert payload.comparison_pair.script == script


def test_apply_rename_mapping_remaps_comparison_source_when_it_was_renamed() -> None:
    """A comparison source living inside a renamed folder gets a new path too."""
    new_source = Path("C:/enc/renamed/Movie.2016.remux.mkv")
    payload = _movie_payload()

    payload.apply_rename_mapping({OLD: NEW, SOURCE: new_source})

    assert payload.comparison_pair
    assert payload.comparison_pair.source == new_source


def test_apply_rename_mapping_without_comparison_pair() -> None:
    payload = _movie_payload()
    payload.comparison_pair = None

    payload.apply_rename_mapping({OLD: NEW})

    assert payload.comparison_pair is None
    assert payload.file_list == [NEW]


def test_apply_rename_mapping_updates_series_episode_map_and_pair() -> None:
    old_one = Path("C:/enc/Show.S01E01-old.mkv")
    old_two = Path("C:/enc/Show.S01E02-old.mkv")
    new_one = Path("C:/enc/Show.S01E01.1080p.BluRay.x264-GRP.mkv")
    new_two = Path("C:/enc/Show.S01E02.1080p.BluRay.x264-GRP.mkv")
    source = Path("C:/enc/Show.S01E01.remux.mkv")

    payload = MediaInputPayload(
        input_path=Path("C:/enc"),
        media_type=MediaType.SERIES,
        file_list=[old_one, old_two],
        file_list_mediainfo={old_one: "mi-1", old_two: "mi-2", source: "mi-source"},  # type: ignore[dict-item]
        file_list_rename_map={old_one: new_one, old_two: new_two},
        comparison_pair=ComparisonPair(source=source, media=old_one, script=None),
        series_episode_map={
            old_one: {"season": 1, "episode": 1},
            old_two: {"season": 1, "episode": 2},
        },
    )

    payload.apply_rename_mapping({old_one: new_one, old_two: new_two})

    assert payload.file_list == [new_one, new_two]
    assert payload.series_episode_map == {
        new_one: {"season": 1, "episode": 1},
        new_two: {"season": 1, "episode": 2},
    }
    assert payload.comparison_pair
    assert payload.comparison_pair.media == new_one
    assert payload.file_list_mediainfo[payload.comparison_pair.media]


def test_apply_rename_mapping_updates_input_path_when_provided() -> None:
    payload = _movie_payload()
    new_input = Path("C:/enc/renamed")

    payload.apply_rename_mapping({OLD: NEW}, updated_input_path=new_input)

    assert payload.input_path == new_input


def test_apply_rename_mapping_keeps_input_path_when_not_provided() -> None:
    payload = _movie_payload()

    payload.apply_rename_mapping({OLD: NEW})

    assert payload.input_path == OLD


def test_apply_rename_mapping_leaves_unrenamed_entries_alone() -> None:
    untouched = Path("C:/enc/Extra.mkv")
    payload = _movie_payload()
    payload.file_list.append(untouched)
    payload.file_list_mediainfo[untouched] = "mi-extra"  # type: ignore[assignment]

    payload.apply_rename_mapping({OLD: NEW})

    assert payload.file_list == [NEW, untouched]
    assert payload.file_list_mediainfo[untouched] == "mi-extra"
