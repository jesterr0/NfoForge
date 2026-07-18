from pathlib import Path

from src.backend.rename_encode_series import RenameEncodeSeriesBackEnd
from src.backend.utils.example_parsed_series_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD,
    EXAMPLE_SEARCH_PAYLOAD,
)
from src.enums.media_type import MediaType
from src.enums.token_replacer import ColonReplace
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload


def _minimal_series_payload() -> MediaInputPayload:
    file_path = Path("Show.S01.mkv")
    return MediaInputPayload(
        input_path=file_path,
        media_type=MediaType.SERIES,
        file_list=[file_path],
    )


def _empty_series_search() -> MediaSearchPayload:
    return MediaSearchPayload(media_type=MediaType.SERIES, tvdb_data={"episodes": []})


def test_series_folder_renamer_renders_multi_season_range() -> None:
    backend = RenameEncodeSeriesBackEnd()
    result = backend.series_folder_renamer(
        media_input_obj=_minimal_series_payload(),
        token="S{season_number|zfill(2)}",
        colon_replacement=ColonReplace.REPLACE_WITH_DASH,
        media_search_payload=_empty_series_search(),
        season_num=1,
        title_clean_rules=None,
        video_dynamic_range=None,
        user_tokens=None,
        season_end=5,
    )
    assert result == Path("S01-S05")


def test_series_folder_renamer_single_season_includes_title() -> None:
    backend = RenameEncodeSeriesBackEnd()
    result = backend.series_folder_renamer(
        media_input_obj=EXAMPLE_MEDIA_INPUT_PAYLOAD,
        token="{title_clean} S{season_number|zfill(2)}",
        colon_replacement=ColonReplace.REPLACE_WITH_DASH,
        media_search_payload=EXAMPLE_SEARCH_PAYLOAD,
        season_num=3,
        title_clean_rules=None,
        video_dynamic_range=None,
        user_tokens=None,
        season_end=3,
    )
    assert result == Path("Series.Name.S03")


def test_series_folder_renamer_omits_episode_context() -> None:
    backend = RenameEncodeSeriesBackEnd()
    result = backend.series_folder_renamer(
        media_input_obj=_minimal_series_payload(),
        token="S{season_number|zfill(2)}{:opt=E:episode_number|zfill(2)}",
        colon_replacement=ColonReplace.REPLACE_WITH_DASH,
        media_search_payload=_empty_series_search(),
        season_num=1,
        title_clean_rules=None,
        video_dynamic_range=None,
        user_tokens=None,
        season_end=1,
    )
    assert result == Path("S01")


def test_build_folder_rename_targets_relocates_pack(tmp_path: Path) -> None:
    src_dir = tmp_path / "show-season-1"
    src_dir.mkdir()
    ep1 = src_dir / "ep1.mkv"
    ep2 = src_dir / "ep2.mkv"
    ep1.write_text("a")
    ep2.write_text("b")
    rename_map = {
        ep1: src_dir / "Show.S01E01.mkv",
        ep2: src_dir / "Show.S01E02.mkv",
    }

    result = RenameEncodeSeriesBackEnd.build_folder_rename_targets(
        input_path=src_dir, rename_map=rename_map, folder_name="Show.S01"
    )

    new_folder = tmp_path / "Show.S01"
    assert result == {
        ep1: new_folder / "Show.S01E01.mkv",
        ep2: new_folder / "Show.S01E02.mkv",
    }


def test_build_folder_rename_targets_single_file_unchanged(tmp_path: Path) -> None:
    # a single opened file: input_path is the file itself, not a directory
    f = tmp_path / "movie.mkv"
    f.write_text("a")
    rename_map = {f: tmp_path / "Renamed.mkv"}

    result = RenameEncodeSeriesBackEnd.build_folder_rename_targets(
        input_path=f, rename_map=rename_map, folder_name="Show.S01"
    )

    assert result == rename_map


def test_build_folder_rename_targets_nested_unchanged(tmp_path: Path) -> None:
    src_dir = tmp_path / "pack"
    nested = src_dir / "sub"
    nested.mkdir(parents=True)
    ep = nested / "ep1.mkv"
    ep.write_text("a")
    rename_map = {ep: nested / "Show.S01E01.mkv"}

    result = RenameEncodeSeriesBackEnd.build_folder_rename_targets(
        input_path=src_dir, rename_map=rename_map, folder_name="Show.S01"
    )

    assert result == rename_map


def test_build_folder_rename_targets_empty_name_unchanged(tmp_path: Path) -> None:
    src_dir = tmp_path / "pack"
    src_dir.mkdir()
    ep = src_dir / "ep1.mkv"
    ep.write_text("a")
    rename_map = {ep: src_dir / "Show.S01E01.mkv"}

    result = RenameEncodeSeriesBackEnd.build_folder_rename_targets(
        input_path=src_dir, rename_map=rename_map, folder_name=""
    )

    assert result == rename_map


def test_folder_rename_end_to_end_via_execute_renames(tmp_path: Path) -> None:
    src_dir = tmp_path / "show-season-1"
    src_dir.mkdir()
    ep1 = src_dir / "raw1.mkv"
    ep2 = src_dir / "raw2.mkv"
    ep1.write_text("1")
    ep2.write_text("2")
    rename_map = {
        ep1: src_dir / "Show.S01E01.mkv",
        ep2: src_dir / "Show.S01E02.mkv",
    }

    relocated = RenameEncodeSeriesBackEnd.build_folder_rename_targets(
        input_path=src_dir, rename_map=rename_map, folder_name="Show.S01"
    )
    mapping, updated_input = RenameEncodeSeriesBackEnd.execute_renames(
        relocated, input_path=src_dir
    )

    new_folder = tmp_path / "Show.S01"
    assert not src_dir.exists()
    assert (new_folder / "Show.S01E01.mkv").exists()
    assert (new_folder / "Show.S01E02.mkv").exists()
    assert updated_input == new_folder
    assert mapping == {
        ep1: new_folder / "Show.S01E01.mkv",
        ep2: new_folder / "Show.S01E02.mkv",
    }
