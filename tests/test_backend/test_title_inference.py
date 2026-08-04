from pathlib import Path

import pytest

from src.backend.utils.title_inference import MediaTitleInferer
from src.exceptions import MediaParsingError


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_infers_movie_title_and_year_from_filename(tmp_path: Path) -> None:
    media_file = _touch(tmp_path / "The.Movie.2025.1080p.BluRay.mkv")

    result = MediaTitleInferer().infer(media_file)

    assert result.title == "The Movie 2025"
    assert result.candidates[0] == ("The Movie 2025", 100)


def test_selected_files_are_used_instead_of_unchecked_media(tmp_path: Path) -> None:
    directory = tmp_path / "Media"
    chosen = _touch(directory / "Chosen.Movie.2020.1080p.mkv")
    _touch(directory / "Unrelated.Movie.2021.1080p.mkv")

    result = MediaTitleInferer().infer(directory, video_files=[chosen])

    assert result.title == "Chosen Movie 2020"
    assert all("Unrelated" not in title for title, _ in result.candidates)


def test_series_title_wins_over_season_directory(tmp_path: Path) -> None:
    directory = tmp_path / "The.Show" / "Season 1"
    first = _touch(directory / "The.Show.S01E01.1080p.mkv")
    second = _touch(directory / "The.Show.S01E02.1080p.mkv")

    result = MediaTitleInferer().infer(
        directory,
        video_files=[first, second],
    )

    assert result.title == "The Show"
    assert all("Season" not in title for title, _ in result.candidates)


def test_sample_files_do_not_become_title_evidence(tmp_path: Path) -> None:
    directory = tmp_path / "Movie.Name.2024"
    sample = _touch(directory / "Sample.Movie.2024.sample.mkv")

    result = MediaTitleInferer().infer(directory, video_files=[sample])

    assert result.title == "Movie Name 2024"


def test_directory_context_can_supply_title_without_selected_video(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "A Good Movie (2023)"
    directory.mkdir()
    _touch(directory / "subtitles.srt")

    result = MediaTitleInferer().infer(directory, video_files=[])

    assert result.title == "A Good Movie 2023"


def test_missing_input_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        MediaTitleInferer().infer(tmp_path / "missing")


def test_unsupported_file_is_rejected(tmp_path: Path) -> None:
    text_file = tmp_path / "notes.txt"
    text_file.write_text("not media", encoding="utf-8")

    with pytest.raises(MediaParsingError, match="not a supported video"):
        MediaTitleInferer().infer(text_file)


def test_candidate_ranking_is_deterministic(tmp_path: Path) -> None:
    directory = tmp_path / "Media"
    first = _touch(directory / "Beta.Movie.2020.mkv")
    second = _touch(directory / "Alpha.Movie.2020.mkv")

    result = MediaTitleInferer().infer(directory, video_files=[first, second])

    assert result.title in {"Alpha Movie 2020", "Beta Movie 2020"}
    assert result.candidates[0][1] == 100
