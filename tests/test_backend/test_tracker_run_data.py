"""Coverage for the prompt-free builder shared by the process page and queue."""

from pathlib import Path

import pytest

from src.backend.tracker_run_data import (
    build_tracker_data,
    image_host_label,
    tracker_output_dir,
)
from src.enums.image_host import ImageHost, ImageSource
from src.enums.tracker_selection import TrackerSelection
from src.packages.custom_types import ImageUploadFromTo


def _hosts() -> dict[TrackerSelection, ImageUploadFromTo]:
    return {
        TrackerSelection.AITHER: ImageUploadFromTo(
            ImageSource.IMAGES, ImageHost.CHEVERETO_V3
        ),
        TrackerSelection.HUNO: ImageUploadFromTo(ImageSource.URLS, ImageSource.URLS),
    }


def test_each_tracker_gets_its_own_output_path(tmp_path: Path) -> None:
    data = build_tracker_data(tmp_path, tmp_path / "Release.2024.mkv", _hosts())

    assert set(data) == {"Aither", "HUNO"}
    assert data["Aither"]["path"] == tmp_path / "aither" / "Release.2024.torrent"
    assert data["HUNO"]["path"] == tmp_path / "huno" / "Release.2024.torrent"


def test_output_directories_are_created(tmp_path: Path) -> None:
    """The run writes .torrent/.nfo straight in and does not create these."""
    build_tracker_data(tmp_path, tmp_path / "Release.mkv", _hosts())

    assert tracker_output_dir(tmp_path, TrackerSelection.AITHER).is_dir()
    assert tracker_output_dir(tmp_path, TrackerSelection.HUNO).is_dir()


def test_directory_creation_can_be_turned_off(tmp_path: Path) -> None:
    build_tracker_data(tmp_path, tmp_path / "Release.mkv", _hosts(), create_dirs=False)

    assert not tracker_output_dir(tmp_path, TrackerSelection.AITHER).exists()


def test_image_host_data_is_carried_through(tmp_path: Path) -> None:
    data = build_tracker_data(tmp_path, tmp_path / "Release.mkv", _hosts())

    assert data["Aither"]["image_host_data"] == ImageUploadFromTo(
        ImageSource.IMAGES, ImageHost.CHEVERETO_V3
    )


def test_labels_match_what_the_combo_boxes_show(tmp_path: Path) -> None:
    data = build_tracker_data(tmp_path, tmp_path / "Release.mkv", _hosts())

    assert data["Aither"]["image_host"] == image_host_label(
        ImageSource.IMAGES, ImageHost.CHEVERETO_V3
    )


def test_no_trackers_builds_nothing(tmp_path: Path) -> None:
    assert build_tracker_data(tmp_path, tmp_path / "Release.mkv", {}) == {}


def test_building_never_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole reason this is separate: the queue has no user to ask.

    An existing torrent is left alone here; resolving that is the caller's job.
    """
    existing = tracker_output_dir(tmp_path, TrackerSelection.AITHER)
    existing.mkdir(parents=True)
    (existing / "Release.torrent").write_bytes(b"already here")

    data = build_tracker_data(tmp_path, tmp_path / "Release.mkv", _hosts())

    assert data["Aither"]["path"] == existing / "Release.torrent"


@pytest.mark.parametrize(
    ("source", "destination", "expected"),
    [
        (ImageSource.IMAGES, ImageHost.CHEVERETO_V3, "IMGs ➔ Chevereto v3"),
        (ImageSource.IMAGES, ImageHost.DISABLED, "Disabled"),
        (ImageSource.URLS, ImageSource.URLS, "URLs"),
    ],
)
def test_label_formatting(
    source: ImageSource, destination: ImageHost | ImageSource, expected: str
) -> None:
    assert image_host_label(source, destination) == expected
