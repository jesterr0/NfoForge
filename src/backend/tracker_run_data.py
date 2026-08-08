"""Building the per-tracker work items a processing run consumes.

`ProcessBackEnd.process_trackers()` takes a mapping of tracker name to where
that tracker's torrent should be written and where its images come from. The
wizard used to build that inline, mixed together with a "file exists, overwrite?"
dialog -- which made it unusable from anywhere without a user attached, such as
the job queue.

The construction lives here, free of Qt and of any prompting, so the queue and
the process page build identical data. The page keeps the overwrite prompt and
applies it on top.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.enums.image_host import ImageHost, ImageSource
from src.enums.tracker_selection import TrackerSelection
from src.packages.custom_types import ImageUploadFromTo


def image_host_label(
    upload_type: ImageSource, img_host: ImageHost | ImageSource
) -> str:
    """Human label for one image source -> destination pairing.

    Shown in the process page's per-tracker combo boxes, and carried in the run
    data so a saved selection can be matched back to its combo entry without
    duplicating the formatting.
    """
    if img_host in {ImageHost.DISABLED, ImageSource.URLS}:
        return str(img_host)
    return f"{upload_type} ➔ {img_host}"


def tracker_output_dir(working_dir: Path, tracker: TrackerSelection) -> Path:
    """Where one tracker's torrent and NFO are written for this run."""
    return working_dir / str(tracker).lower()


def build_tracker_data(
    working_dir: Path,
    input_path: Path,
    tracker_image_hosts: dict[TrackerSelection, ImageUploadFromTo],
    create_dirs: bool = True,
) -> dict[str, dict[str, Any]]:
    """Assemble the run data for every tracker, prompting for nothing.

    `create_dirs` is on by default and is not incidental: the run writes each
    tracker's `.torrent` and `.nfo` straight into these directories and does not
    create them itself, so a caller that turns this off has to make them.
    """
    tracker_data: dict[str, dict[str, Any]] = {}

    for tracker, image_host_data in tracker_image_hosts.items():
        output_dir = tracker_output_dir(working_dir, tracker)
        if create_dirs:
            output_dir.mkdir(parents=True, exist_ok=True)

        tracker_data[str(tracker)] = {
            "path": output_dir / f"{input_path.stem}.torrent",
            "image_host": image_host_label(
                image_host_data.img_from, image_host_data.img_to
            ),
            "image_host_data": image_host_data,
        }

    return tracker_data
