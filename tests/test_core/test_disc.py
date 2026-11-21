from pathlib import Path

import pytest

from nfoforge.core.disc import (
    DiscError,
    DiscSize,
    DiscType,
    choose_playlist,
    detect_disc,
    disc_size_class,
    disc_warnings,
    find_discs,
    normalize_playlist_id,
)
from nfoforge.core.disc.mpls import MplsError, parse_mpls
from nfoforge.core.rename.movie import movie_rename_map
from nfoforge.core.workflow.steps import WorkflowError, collect_media_files
from nfoforge.enums.media_type import MediaType
from nfoforge.payloads.media_inputs import MediaInputPayload
from nfoforge.payloads.series import build_series_release_info
from tests.disc_helpers import make_bluray, make_dvd, mpls_bytes

FEATURE = [("00001", 0, 7200)]


def _no_duration(_: Path) -> None:
    return None


def test_parse_mpls_reads_clips_and_times() -> None:
    items = parse_mpls(mpls_bytes([("00001", 10, 70), ("00002", 0, 30)]))
    assert items == [("00001", 450000, 3150000), ("00002", 0, 1350000)]


@pytest.mark.parametrize("data", [b"", b"NOPE" + b"\0" * 40, mpls_bytes(FEATURE)[:50]])
def test_parse_mpls_rejects_bad_files(data: bytes) -> None:
    with pytest.raises(MplsError):
        parse_mpls(data)


def test_plain_folder_is_not_a_disc(tmp_path: Path) -> None:
    (tmp_path / "movie.mkv").write_bytes(b"x")
    assert detect_disc(tmp_path) is None
    assert detect_disc(tmp_path / "movie.mkv") is None


def test_bluray_is_detected_and_main_feature_marked(tmp_path: Path) -> None:
    root = make_bluray(
        tmp_path / "Movie.2020.BluRay",
        {
            "00800": FEATURE,
            # an extended cut: same clip plus a second one
            "00801": [("00001", 0, 7200), ("00002", 0, 600)],
            "00010": [("00003", 0, 900)],
        },
        {"00001": 5000, "00002": 400, "00003": 300},
    )
    disc = detect_disc(root)

    assert disc is not None
    assert disc.disc_type is DiscType.BDMV
    assert disc.root == root
    assert disc.label == "Movie.2020.BluRay"
    assert disc.has_certificate is True
    # the whole folder is uploaded, so the playlists count as well as the clips
    assert disc.size == sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
    assert disc.playlist("00801").size == 5400  # type: ignore[union-attr]
    assert [p.playlist_id for p in disc.playlists] == ["00010", "00800", "00801"]
    assert [p.playlist_id for p in disc.main_playlists()] == ["00800", "00801"]
    assert disc.playlist("801").duration == 7800  # type: ignore[union-attr]


def test_bluray_filters_short_looping_and_duplicate_playlists(tmp_path: Path) -> None:
    root = make_bluray(
        tmp_path / "disc",
        {
            "00001": FEATURE,
            "00002": FEATURE,  # exact copy of 00001
            "00003": [("00002", 0, 60)],  # too short
            "00004": [("00002", 0, 100)] * 5,  # a loop
            "00005": [("09999", 0, 7200)],  # clip not on disc
        },
        {"00001": 5000, "00002": 100},
        certificate=False,
    )
    disc = detect_disc(root)

    assert disc is not None
    assert [p.playlist_id for p in disc.playlists] == ["00001"]
    assert disc.has_certificate is False
    assert [w.split(" has ")[0] for w in disc_warnings(disc)] == ["disc"]


def test_complete_bluray_and_dvd_have_no_warnings(tmp_path: Path) -> None:
    bluray = detect_disc(
        make_bluray(tmp_path / "bd", {"00001": FEATURE}, {"00001": 10})
    )
    dvd = detect_disc(make_dvd(tmp_path / "dvd", {"01": [10, 200]}, ifos=False))
    assert bluray is not None and dvd is not None
    assert disc_warnings(bluray) == []
    assert disc_warnings(dvd) == []


def test_disc_of_shorts_still_offers_its_playlists(tmp_path: Path) -> None:
    root = make_bluray(tmp_path / "disc", {"00001": [("00001", 0, 90)]}, {"00001": 100})
    disc = detect_disc(root)
    assert disc is not None
    assert [p.playlist_id for p in disc.playlists] == ["00001"]


def test_lowercase_rip_is_detected(tmp_path: Path) -> None:
    root = make_bluray(
        tmp_path / "disc", {"00800": FEATURE}, {"00001": 10}, upper=False
    )
    disc = detect_disc(root)
    assert disc is not None
    assert disc.has_certificate is True
    assert disc.primary_media_file() == root / "bdmv" / "stream" / "00001.m2ts"


def test_uppercase_extensions_are_read(tmp_path: Path) -> None:
    root = make_bluray(tmp_path / "disc", {"00800": FEATURE}, {"00001": 10})
    stream = root / "BDMV" / "STREAM"
    (stream / "00001.m2ts").rename(stream / "00001.M2TS")
    playlist = root / "BDMV" / "PLAYLIST"
    (playlist / "00800.mpls").rename(playlist / "00800.MPLS")

    disc = detect_disc(root)

    assert disc is not None
    assert [p.playlist_id for p in disc.playlists] == ["00800"]
    assert disc.primary_media_file() == stream / "00001.M2TS"


def test_primary_media_file_is_largest_clip_of_selected_playlist(
    tmp_path: Path,
) -> None:
    root = make_bluray(
        tmp_path / "disc",
        {
            "00800": [("00001", 0, 3000), ("00002", 0, 4000)],
            "00801": [("00003", 0, 6500)],
        },
        {"00001": 100, "00002": 900, "00003": 500},
    )
    disc = detect_disc(root)
    assert disc is not None
    stream = root / "BDMV" / "STREAM"

    # nothing selected yet: the first main playlist stands in
    assert disc.primary_media_file() == stream / "00002.m2ts"
    disc.select("801.mpls")
    assert disc.selected == ["00801"]
    assert disc.primary_media_file() == stream / "00003.m2ts"
    with pytest.raises(DiscError, match="not a playlist"):
        disc.select("00999")


def test_dvd_main_title_is_largest_set_without_durations(tmp_path: Path) -> None:
    root = make_dvd(
        tmp_path / "Movie.DVD",
        {"01": [10, 200], "02": [10, 4000, 3000], "03": [50]},  # 03 is menus only
        ifos=False,
    )
    disc = detect_disc(root)

    assert disc is not None
    assert disc.disc_type is DiscType.DVD
    assert disc.has_certificate is None
    assert [p.playlist_id for p in disc.playlists] == ["01", "02"]
    assert [p.playlist_id for p in disc.main_playlists()] == ["02"]
    assert disc.playlists[1].path is None
    assert disc.primary_media_file() == root / "VIDEO_TS" / "VTS_02_1.VOB"


def test_dvd_durations_drop_short_titles_and_mark_alternates(tmp_path: Path) -> None:
    root = make_dvd(
        tmp_path / "disc",
        {"01": [1, 5000], "02": [1, 4800], "03": [1, 300], "04": [1, 50]},
        upper=False,
    )
    durations = {"01": 6000.0, "02": 5500.0, "03": 60.0, "04": None}

    def reader(ifo: Path) -> float | None:
        return durations[ifo.name[4:6]]

    disc = detect_disc(root, reader)

    assert disc is not None
    # 03 is short; 04's runtime is unknown, which is not a reason to drop it
    assert [p.playlist_id for p in disc.playlists] == ["01", "02", "04"]
    assert [p.playlist_id for p in disc.main_playlists()] == ["01", "02"]


def test_dvd_menu_vob_does_not_count_towards_a_title(tmp_path: Path) -> None:
    root = make_dvd(
        tmp_path / "Show.S01.DVD",
        {"01": [900, 800], "02": [1, 810], "03": [1, 790], "04": [1, 300]},
        ifos=False,
    )
    disc = detect_disc(root)
    assert disc is not None
    # the menu VOB does not count: 02 is the largest feature, not 01
    assert disc.playlists[0].size == 800
    assert [p.playlist_id for p in disc.main_playlists()] == ["02"]


def test_like_sized_dvd_titles_do_not_stop_the_run(tmp_path: Path) -> None:
    root = make_dvd(tmp_path / "Show.S01.DVD", {"01": [1, 800], "02": [1, 810]})
    disc = detect_disc(root, lambda _: 1440.0)
    assert disc is not None
    assert [p.playlist_id for p in disc.main_playlists()] == ["01", "02"]
    # episodes, not rival cuts: the first one stands for the disc
    assert choose_playlist(disc).playlist_id == "01"
    assert choose_playlist(disc, "2").playlist_id == "02"


def test_selecting_the_marker_folder_is_refused(tmp_path: Path) -> None:
    root = make_bluray(tmp_path / "disc", {"00800": FEATURE}, {"00001": 10})
    with pytest.raises(DiscError, match="contains BDMV"):
        detect_disc(root / "BDMV")


def test_empty_disc_is_refused(tmp_path: Path) -> None:
    root = make_bluray(tmp_path / "disc", {}, {})
    with pytest.raises(DiscError, match="Nothing playable"):
        detect_disc(root)


def test_multi_disc_set_is_found_but_not_accepted_yet(tmp_path: Path) -> None:
    make_bluray(tmp_path / "set" / "Disc2", {"00800": FEATURE}, {"00001": 10})
    make_bluray(tmp_path / "set" / "Disc1", {"00800": FEATURE}, {"00001": 10})

    assert [d.label for d in find_discs(tmp_path / "set")] == ["Disc1", "Disc2"]
    with pytest.raises(DiscError, match="Multi-disc"):
        detect_disc(tmp_path / "set")


def test_single_disc_one_level_down_is_accepted(tmp_path: Path) -> None:
    make_dvd(tmp_path / "set" / "Disc1", {"01": [1, 100]}, ifos=False)
    disc = detect_disc(tmp_path / "set", _no_duration)
    assert disc is not None
    assert disc.root == tmp_path / "set" / "Disc1"


def test_mixed_disc_types_are_refused(tmp_path: Path) -> None:
    make_bluray(tmp_path / "set" / "BD", {"00800": FEATURE}, {"00001": 10})
    make_dvd(tmp_path / "set" / "DVD", {"01": [1, 100]}, ifos=False)
    with pytest.raises(DiscError, match="mixes"):
        find_discs(tmp_path / "set", _no_duration)


@pytest.mark.parametrize(
    ("disc_type", "size", "expected"),
    [
        (DiscType.BDMV, 20 * 10**9, DiscSize.BD25),
        (DiscType.BDMV, 45 * 10**9, DiscSize.BD50),
        (DiscType.BDMV, 60 * 10**9, DiscSize.BD66),
        (DiscType.BDMV, 90 * 10**9, DiscSize.BD100),
        (DiscType.DVD, 4 * 10**9, DiscSize.DVD5),
        (DiscType.DVD, 7 * 10**9, DiscSize.DVD9),
    ],
)
def test_disc_size_class(disc_type: DiscType, size: int, expected: DiscSize) -> None:
    assert disc_size_class(disc_type, size) is expected


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("800", "00800"),
        ("00800", "00800"),
        ("00800.MPLS", "00800"),
        ("2", "02"),
        ("VTS_02_0.IFO", "02"),
    ],
)
def test_normalize_playlist_id(given: str, expected: str) -> None:
    assert normalize_playlist_id(given) == expected


# --------------------------------------------------------------------------
# the disc as a release: payload, input step, rename
# --------------------------------------------------------------------------
def _two_cut_disc(root: Path) -> Path:
    return make_bluray(
        root,
        {"00800": FEATURE, "00801": [("00002", 0, 7500)]},
        {"00001": 5000, "00002": 4900},
    )


def test_choose_playlist_refuses_to_guess_between_cuts(tmp_path: Path) -> None:
    disc = detect_disc(_two_cut_disc(tmp_path / "disc"))
    assert disc is not None
    with pytest.raises(DiscError, match="2 possible main playlists") as caught:
        choose_playlist(disc)
    assert "00800" in str(caught.value) and "2:05:00" in str(caught.value)
    assert choose_playlist(disc, "801").playlist_id == "00801"


def test_collect_media_files_yields_the_disc_primary_clip(tmp_path: Path) -> None:
    root = make_bluray(
        tmp_path / "Movie.2020.BluRay",
        {"00800": FEATURE, "00010": [("00002", 0, 600)]},
        {"00001": 5000, "00002": 400},
    )
    assert collect_media_files(root) == [root / "BDMV" / "STREAM" / "00001.m2ts"]


def test_collect_media_files_needs_a_playlist_for_an_ambiguous_disc(
    tmp_path: Path,
) -> None:
    root = _two_cut_disc(tmp_path / "disc")
    stream = root / "BDMV" / "STREAM"

    with pytest.raises(WorkflowError, match="possible main playlists"):
        collect_media_files(root)
    assert collect_media_files(root, "00801") == [stream / "00002.m2ts"]
    # a caller that only needs a file to look at is not stopped
    assert collect_media_files(root, settle_playlist=False) == [stream / "00001.m2ts"]
    with pytest.raises(WorkflowError, match="not a playlist"):
        collect_media_files(root, "00999")


def _disc_payload(root: Path) -> MediaInputPayload:
    disc = detect_disc(root)
    assert disc is not None
    choose_playlist(disc)
    primary = disc.primary_media_file()
    assert primary is not None
    return MediaInputPayload(
        input_path=root,
        media_type=MediaType.MOVIE,
        file_list=[primary],
        input_kind="directory",
        content_size=disc.size,
        discs=[disc],
    )


def test_disc_payload_is_named_after_its_folder(tmp_path: Path) -> None:
    root = make_bluray(
        tmp_path / "Movie.2020.1080p.BluRay.AVC-GRP", {"00800": FEATURE}, {"00001": 9}
    )
    payload = _disc_payload(root)

    assert payload.is_disc()
    assert payload.primary_media_file() == root / "BDMV" / "STREAM" / "00001.m2ts"
    assert payload.release_name_path() == root
    assert payload.release_name() == "Movie.2020.1080p.BluRay.AVC-GRP"
    # the dupe search asks trackers about the release, not about `00001`
    assert build_series_release_info(payload).search_name == root.name

    payload.reset()
    assert not payload.is_disc()


def test_file_payload_is_named_after_its_file(tmp_path: Path) -> None:
    media = tmp_path / "Movie.2020.1080p.BluRay.x264-GRP.mkv"
    payload = MediaInputPayload(input_path=media, file_list=[media])

    assert not payload.is_disc()
    assert payload.primary_media_file() == media
    assert payload.release_name() == "Movie.2020.1080p.BluRay.x264-GRP"


def test_nothing_on_a_disc_is_renamed(tmp_path: Path) -> None:
    root = make_dvd(tmp_path / "Movie.DVD9", {"01": [1, 100]}, ifos=False)
    assert movie_rename_map(_disc_payload(root), "Movie.2020.NTSC.DVD9-GRP") == {}
