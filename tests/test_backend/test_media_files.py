from pathlib import Path

import pytest

from src.backend.utils import media_files
from src.backend.utils.media_files import (
    filter_media_files,
    find_sidecars,
    find_sidecars_for,
    is_media_file,
    is_sample,
    sidecar_suffix,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    (
        ("Show.S01E01.mkv", True),
        ("Show.S01E01.MKV", True),
        ("Show.S01E01.mp4", True),
        ("Show.S01E01.en.srt", False),
        ("Show.S01E01.nfo", False),
        ("cover.jpg", False),
        ("Show.S01E01.sample.mkv", False),
        ("sample-Show.S01E01.mkv", False),
        # "sample" only counts as a whole separator-delimited word
        ("Show.Sampler.S01E01.mkv", True),
    ),
)
def test_is_media_file(name: str, expected: bool) -> None:
    assert is_media_file(Path(name)) is expected


def test_is_sample_ignores_extension() -> None:
    assert is_sample(Path("Show.sample.mkv")) is True
    assert is_sample(Path("Show.S01E01.mkv")) is False


def test_filter_media_files_preserves_order() -> None:
    paths = [
        Path("b.mkv"),
        Path("a.srt"),
        Path("a.mkv"),
        Path("sample.mkv"),
    ]
    assert filter_media_files(paths) == [Path("b.mkv"), Path("a.mkv")]


@pytest.mark.parametrize(
    ("candidate", "expected"),
    (
        ("ep01.srt", ".srt"),
        ("ep01.en.srt", ".en.srt"),
        ("ep01.nfo", ".nfo"),
        ("ep01-eng.sub", "-eng.sub"),
        ("ep01_2.idx", "_2.idx"),
        # a separator is required, so a longer stem is not a sidecar
        ("ep01a.srt", None),
        ("ep011.srt", None),
        # nothing after the stem at all
        ("ep01", None),
        ("other.srt", None),
    ),
)
def test_sidecar_suffix(candidate: str, expected: str | None) -> None:
    assert sidecar_suffix(Path("ep01.mkv"), Path(candidate)) == expected


def test_sidecar_suffix_is_case_insensitive() -> None:
    assert sidecar_suffix(Path("EP01.mkv"), Path("ep01.en.srt")) == ".en.srt"


def test_find_sidecars_collects_only_matching_siblings(tmp_path: Path) -> None:
    episode = tmp_path / "ep01.mkv"
    episode.write_text("v")
    (tmp_path / "ep01.en.srt").write_text("s")
    (tmp_path / "ep01.nfo").write_text("n")
    (tmp_path / "ep02.srt").write_text("other")
    (tmp_path / "cover.jpg").write_text("i")

    assert find_sidecars(episode) == {
        tmp_path / "ep01.en.srt": ".en.srt",
        tmp_path / "ep01.nfo": ".nfo",
    }


def test_find_sidecars_excludes_other_release_media(tmp_path: Path) -> None:
    """`ep01.mp4` beside `ep01.mkv` is a second encode, not a sidecar."""
    episode = tmp_path / "ep01.mkv"
    other = tmp_path / "ep01.mp4"
    episode.write_text("v")
    other.write_text("v")
    (tmp_path / "ep01.srt").write_text("s")

    assert find_sidecars(episode, exclude={episode, other}) == {
        tmp_path / "ep01.srt": ".srt"
    }


def test_find_sidecars_ignores_directories(tmp_path: Path) -> None:
    episode = tmp_path / "ep01.mkv"
    episode.write_text("v")
    (tmp_path / "ep01.extras").mkdir()

    assert find_sidecars(episode) == {}


def test_find_sidecars_missing_directory_is_empty() -> None:
    assert find_sidecars(Path("does/not/exist/ep01.mkv")) == {}


def test_find_sidecars_for_matches_each_episode(tmp_path: Path) -> None:
    ep1 = tmp_path / "ep01.mkv"
    ep2 = tmp_path / "ep02.mkv"
    ep1.write_text("1")
    ep2.write_text("2")
    (tmp_path / "ep01.en.srt").write_text("s1")
    (tmp_path / "ep02.srt").write_text("s2")
    (tmp_path / "poster.jpg").write_text("i")

    assert find_sidecars_for([ep1, ep2]) == {
        ep1: {tmp_path / "ep01.en.srt": ".en.srt"},
        ep2: {tmp_path / "ep02.srt": ".srt"},
    }


def test_find_sidecars_for_excludes_every_other_episode(tmp_path: Path) -> None:
    """Two encodes of one episode must not adopt each other."""
    mkv = tmp_path / "ep01.mkv"
    mp4 = tmp_path / "ep01.mp4"
    mkv.write_text("1")
    mp4.write_text("1")
    (tmp_path / "ep01.srt").write_text("s")

    result = find_sidecars_for([mkv, mp4])

    assert result[mkv] == {tmp_path / "ep01.srt": ".srt"}
    assert result[mp4] == {tmp_path / "ep01.srt": ".srt"}


def test_find_sidecars_for_spans_season_subfolders(tmp_path: Path) -> None:
    season_one = tmp_path / "Season 01"
    season_two = tmp_path / "Season 02"
    season_one.mkdir()
    season_two.mkdir()
    ep1 = season_one / "ep01.mkv"
    ep2 = season_two / "ep01.mkv"
    ep1.write_text("1")
    ep2.write_text("2")
    (season_one / "ep01.srt").write_text("s")

    result = find_sidecars_for([ep1, ep2])

    assert result[ep1] == {season_one / "ep01.srt": ".srt"}
    # same filename, different folder: no sidecar there
    assert result[ep2] == {}


def test_find_sidecars_for_reads_each_directory_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A flat pack has one folder; scanning it per episode is quadratic I/O."""
    episodes = []
    for index in range(1, 6):
        episode = tmp_path / f"ep{index:02d}.mkv"
        episode.write_text("v")
        (tmp_path / f"ep{index:02d}.srt").write_text("s")
        episodes.append(episode)

    scans: list[Path] = []
    real_scandir = media_files.scandir

    def counting_scandir(path):
        scans.append(Path(path))
        return real_scandir(path)

    monkeypatch.setattr(media_files, "scandir", counting_scandir)
    result = find_sidecars_for(episodes)

    assert scans == [tmp_path]
    assert all(len(sidecars) == 1 for sidecars in result.values())
