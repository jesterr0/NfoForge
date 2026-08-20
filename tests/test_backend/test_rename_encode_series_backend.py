from pathlib import Path

from src.backend.rename_encode_series import RenameEncodeSeriesBackEnd
from src.backend.rename_files import RenameExecutor, RenamePlan
from src.backend.utils.example_parsed_series_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD,
    EXAMPLE_SEARCH_PAYLOAD,
)
from src.enums.media_type import MediaType
from src.enums.multi_episode_style import MultiEpisodeStyle
from src.enums.series import EpisodeFormat
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


def test_series_renamer_uses_the_episode_being_rendered() -> None:
    first_file = Path("Show.S01E01.1080p.WEB-DL-GRP.mkv")
    second_file = Path("Show.S01E02.REPACK.720p.WEB-DL-OTHER.mkv")
    payload = MediaInputPayload(
        input_path=Path("Show.S01"),
        media_type=MediaType.SERIES,
        file_list=[first_file, second_file],
    )

    result = RenameEncodeSeriesBackEnd().series_renamer(
        media_input_obj=payload,
        media_file=second_file,
        # {re_release} used to appear here. It is a claim now, and claims are
        # pack-wide: they arrive as overrides rather than being read off the
        # episode being rendered. {resolution} and {release_group} are still
        # per-file, which is what this test is about.
        token="{resolution} {release_group}",  # noqa: S106 - NFO template token string used as test fixture data, not a credential
        colon_replacement=ColonReplace.REPLACE_WITH_DASH,
        media_search_payload=_empty_series_search(),
        season_num=1,
        episode_num=2,
        title_clean_rules=None,
        video_dynamic_range=None,
        user_tokens=None,
        episode_format=EpisodeFormat.STANDARD,
        multi_episode_style=MultiEpisodeStyle.RANGE,
    )

    assert result == Path("720p.OTHER.mkv")


def test_series_folder_renamer_renders_multi_season_range() -> None:
    backend = RenameEncodeSeriesBackEnd()
    result = backend.series_folder_renamer(
        media_input_obj=_minimal_series_payload(),
        token="S{season_number|zfill(2)}",  # noqa: S106 - NFO template token string used as test fixture data, not a credential
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
        token="{title_clean} S{season_number|zfill(2)}",  # noqa: S106 - NFO template token string used as test fixture data, not a credential
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
        token="S{season_number|zfill(2)}{:opt=E:episode_number|zfill(2)}",  # noqa: S106 - NFO template token string used as test fixture data, not a credential
        colon_replacement=ColonReplace.REPLACE_WITH_DASH,
        media_search_payload=_empty_series_search(),
        season_num=1,
        title_clean_rules=None,
        video_dynamic_range=None,
        user_tokens=None,
        season_end=1,
    )
    assert result == Path("S01")


def test_build_pack_rename_targets_relocates_flat_pack(tmp_path: Path) -> None:
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

    files, directories = RenameEncodeSeriesBackEnd.build_pack_rename_targets(
        input_path=src_dir,
        rename_map=rename_map,
        file_seasons={ep1: 1, ep2: 1},
        root_folder_name="Show.S01",
        season_folder_names={1: "Season 01"},
    )

    new_folder = tmp_path / "Show.S01"
    assert files == {
        ep1: new_folder / "Show.S01E01.mkv",
        ep2: new_folder / "Show.S01E02.mkv",
    }
    # a flat pack has no subfolder to name, so the season name goes unused
    assert directories == {src_dir: new_folder}


def test_build_pack_rename_targets_single_file_unchanged(tmp_path: Path) -> None:
    # a single opened file: input_path is the file itself, not a directory
    file_path = tmp_path / "movie.mkv"
    file_path.write_text("a")
    rename_map = {file_path: tmp_path / "Renamed.mkv"}

    files, directories = RenameEncodeSeriesBackEnd.build_pack_rename_targets(
        input_path=file_path,
        rename_map=rename_map,
        file_seasons={file_path: 1},
        root_folder_name="Show.S01",
        season_folder_names={},
    )

    assert files == rename_map
    assert files is not rename_map  # guard-fail path returns a copy, not the input
    assert directories == {}


def test_build_pack_rename_targets_renames_season_subfolders(tmp_path: Path) -> None:
    root = tmp_path / "Show.Complete.Series"
    season_one = root / "Season 01"
    season_two = root / "Season 02"
    season_one.mkdir(parents=True)
    season_two.mkdir(parents=True)
    ep1 = season_one / "ep1.mkv"
    ep2 = season_two / "ep1.mkv"
    ep1.write_text("a")
    ep2.write_text("b")
    rename_map = {
        ep1: season_one / "Show.S01E01.mkv",
        ep2: season_two / "Show.S02E01.mkv",
    }

    files, directories = RenameEncodeSeriesBackEnd.build_pack_rename_targets(
        input_path=root,
        rename_map=rename_map,
        file_seasons={ep1: 1, ep2: 2},
        root_folder_name="Show.S01-S02",
        season_folder_names={1: "Show.S01", 2: "Show.S02"},
    )

    new_root = tmp_path / "Show.S01-S02"
    assert directories == {
        root: new_root,
        season_one: new_root / "Show.S01",
        season_two: new_root / "Show.S02",
    }
    assert files == {
        ep1: new_root / "Show.S01" / "Show.S01E01.mkv",
        ep2: new_root / "Show.S02" / "Show.S02E01.mkv",
    }


def test_build_pack_rename_targets_mixed_season_subfolder_keeps_name(
    tmp_path: Path,
) -> None:
    """A folder holding two seasons has no single season name to take."""
    root = tmp_path / "Show.Pack"
    mixed = root / "Episodes"
    mixed.mkdir(parents=True)
    ep1 = mixed / "ep1.mkv"
    ep2 = mixed / "ep2.mkv"
    ep1.write_text("a")
    ep2.write_text("b")
    rename_map = {ep1: mixed / "Show.S01E01.mkv", ep2: mixed / "Show.S02E01.mkv"}

    files, directories = RenameEncodeSeriesBackEnd.build_pack_rename_targets(
        input_path=root,
        rename_map=rename_map,
        file_seasons={ep1: 1, ep2: 2},
        root_folder_name="Show.S01-S02",
        season_folder_names={1: "Show.S01", 2: "Show.S02"},
    )

    new_root = tmp_path / "Show.S01-S02"
    assert directories == {root: new_root}
    # the folder keeps its name but still moves, because its parent is renamed
    assert files == {
        ep1: new_root / "Episodes" / "Show.S01E01.mkv",
        ep2: new_root / "Episodes" / "Show.S02E01.mkv",
    }


def test_build_pack_rename_targets_empty_name_keeps_root(tmp_path: Path) -> None:
    src_dir = tmp_path / "pack"
    src_dir.mkdir()
    episode = src_dir / "ep1.mkv"
    episode.write_text("a")
    rename_map = {episode: src_dir / "Show.S01E01.mkv"}

    files, directories = RenameEncodeSeriesBackEnd.build_pack_rename_targets(
        input_path=src_dir,
        rename_map=rename_map,
        file_seasons={episode: 1},
        root_folder_name="",
        season_folder_names={},
    )

    assert files == rename_map
    assert directories == {}


def test_build_pack_rename_targets_rejects_file_outside_input(tmp_path: Path) -> None:
    src_dir = tmp_path / "pack"
    src_dir.mkdir()
    outside = tmp_path / "loose.mkv"
    outside.write_text("a")
    rename_map = {outside: tmp_path / "Show.S01E01.mkv"}

    files, directories = RenameEncodeSeriesBackEnd.build_pack_rename_targets(
        input_path=src_dir,
        rename_map=rename_map,
        file_seasons={outside: 1},
        root_folder_name="Show.S01",
        season_folder_names={},
    )

    assert files == rename_map
    assert directories == {}


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

    files, directories = RenameEncodeSeriesBackEnd.build_pack_rename_targets(
        input_path=src_dir,
        rename_map=rename_map,
        file_seasons={ep1: 1, ep2: 1},
        root_folder_name="Show.S01",
        season_folder_names={},
    )
    result = RenameExecutor.execute(
        RenamePlan.build(files, input_path=src_dir, directory_targets=directories)
    )

    new_folder = tmp_path / "Show.S01"
    assert not src_dir.exists()
    assert (new_folder / "Show.S01E01.mkv").exists()
    assert (new_folder / "Show.S01E02.mkv").exists()
    assert result.success is True
    assert result.updated_input_path == new_folder
    assert result.path_mapping == {
        ep1: new_folder / "Show.S01E01.mkv",
        ep2: new_folder / "Show.S01E02.mkv",
    }


def test_nested_pack_rename_end_to_end(tmp_path: Path) -> None:
    """Root and both season subfolders rename; unrelated content rides along."""
    root = tmp_path / "Show.Complete.Series"
    season_one = root / "Season 01"
    season_two = root / "Season 02"
    season_one.mkdir(parents=True)
    season_two.mkdir(parents=True)
    ep1 = season_one / "raw1.mkv"
    ep2 = season_two / "raw2.mkv"
    ep1.write_text("1")
    ep2.write_text("2")
    extras = root / "Extras"
    extras.mkdir()
    (extras / "bts.mkv").write_text("x")

    rename_map = {
        ep1: season_one / "Show.S01E01.mkv",
        ep2: season_two / "Show.S02E01.mkv",
    }
    files, directories = RenameEncodeSeriesBackEnd.build_pack_rename_targets(
        input_path=root,
        rename_map=rename_map,
        file_seasons={ep1: 1, ep2: 2},
        root_folder_name="Show.S01-S02",
        season_folder_names={1: "Show.S01", 2: "Show.S02"},
    )
    result = RenameExecutor.execute(
        RenamePlan.build(files, input_path=root, directory_targets=directories)
    )

    new_root = tmp_path / "Show.S01-S02"
    assert result.success is True, result.message
    assert not root.exists()
    assert result.updated_input_path == new_root
    assert (new_root / "Show.S01" / "Show.S01E01.mkv").read_text() == "1"
    assert (new_root / "Show.S02" / "Show.S02E01.mkv").read_text() == "2"
    # not part of the rename set, but carried by its parent being renamed
    assert (new_root / "Extras" / "bts.mkv").read_text() == "x"


def test_nested_pack_rename_rolls_back_on_failure(tmp_path: Path) -> None:
    """A blocked root rename must undo the subfolder renames already done."""
    root = tmp_path / "Show.Complete.Series"
    season_one = root / "Season 01"
    season_one.mkdir(parents=True)
    ep1 = season_one / "raw1.mkv"
    ep1.write_text("1")
    # the root's destination already exists, so the final folder rename fails
    (tmp_path / "Show.S01-S02").mkdir()

    files, directories = RenameEncodeSeriesBackEnd.build_pack_rename_targets(
        input_path=root,
        rename_map={ep1: season_one / "Show.S01E01.mkv"},
        file_seasons={ep1: 1},
        root_folder_name="Show.S01-S02",
        season_folder_names={1: "Show.S01"},
    )
    result = RenameExecutor.execute(
        RenamePlan.build(files, input_path=root, directory_targets=directories)
    )

    assert result.success is False
    assert result.rollback_complete is True
    assert ep1.read_text() == "1"
    assert season_one.is_dir()
    assert not (root / "Show.S01").exists()
