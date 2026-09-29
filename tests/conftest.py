"""Shared pytest fixtures/config for the whole suite.

Qt is optional (the `gui` extra), and most of the suite runs without it. So
nothing here imports Qt: its fixtures live in `tests/qt_fixtures.py` and are
pulled in only when PySide6 is installed. Without it, every test file that
imports Qt or the desktop app is skipped at collection, and the rest runs.

Sets the Qt platform plugin to "offscreen" before Qt is ever imported so the
suite is safe to run on a headless CI runner (no X server/display required).
"""

from dataclasses import dataclass
import os

# must be set before any PySide6/Qt import happens, anywhere in the test
# session, so use setdefault to respect an explicit override (e.g. a
# developer running with a real display) while still defaulting to
# offscreen for CI/headless runs.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from importlib.util import find_spec
from pathlib import Path
import re
import struct
import wave

from pymediainfo import MediaInfo
import pytest
from torf import Torrent

from nfoforge.backend.jobs import (
    SavedJob,
    base_torrent_snapshot,
    build_job,
    capture_mediainfo,
    capture_nfos,
    context_to_dict,
    copy_images,
    job_dir,
    save_job,
)
from nfoforge.backend.jobs.models import JobSummary
from nfoforge.backend.utils.example_parsed_movie_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD as MOVIE_EXAMPLE_PAYLOAD,
)
from nfoforge.backend.utils.example_parsed_series_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD as SERIES_EXAMPLE_PAYLOAD,
)
from nfoforge.backend.utils.media_info_utils import clear_restored_mediainfo
from nfoforge.config.paths import DATA_DIR_ENV_VAR, DEV_PLUGINS_ENV_VAR
from nfoforge.context.processing_context import ProcessingContext
from nfoforge.enums.image_host import ImageHost, ImageSource
from nfoforge.enums.media_type import MediaType
from nfoforge.enums.tracker_selection import TrackerSelection
from nfoforge.packages.custom_types import ImageUploadData, ImageUploadFromTo

QT_AVAILABLE = find_spec("PySide6") is not None
"""Whether the optional `gui` extra is installed."""

if QT_AVAILABLE:
    # bound here so pytest registers them for the whole suite
    from tests.qt_fixtures import (  # noqa: F401
        _fresh_global_signals,
        _no_blocking_modals,
        qapp,
    )

_NEEDS_QT = re.compile(
    r"^\s*(?:from|import)\s+(?:PySide6|shiboken6|qtawesome|nfoforge\.frontend|"
    r"nfoforge\.plugins\.plugin_wizard_base|tests\.qt_fixtures)\b|\bqapp\b",
    re.MULTILINE,
)
"""A test file that imports Qt or the desktop app, or asks for the QApplication."""


def pytest_ignore_collect(collection_path: Path) -> bool | None:
    """Without Qt, skip every test file that needs it, rather than erroring.

    Decided by reading the file, not by a folder list: a Qt test outside
    `test_frontend` is still found, and a Qt-free one inside it still runs.
    """
    if QT_AVAILABLE or collection_path.suffix != ".py":
        return None
    if not collection_path.name.startswith("test_"):
        return None
    source = collection_path.read_text(encoding="utf-8", errors="replace")
    return True if _NEEDS_QT.search(source) else None


@pytest.fixture(autouse=True)
def _sandbox_every_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every root at a throwaway directory, for every test.

    Path resolution is not read-only: ``ConfigOperations._load`` calls
    ``default_working_dir(ensure_exists=True)`` for any configuration with no
    explicit working directory, which creates whatever it resolves to. Left
    alone that is the directory a real installation keeps its saved jobs, index
    cache and run output in, and ``default_paths`` would resolve the state root
    to the checkout's own ``runtime`` tree -- a developer's live configuration.
    Neither is somewhere a test may write.

    Setting the override rather than patching ``data_root`` means the real
    resolution runs, so this sandboxes through the same code path a rehearsal
    uses instead of replacing it. A test that needs different resolution sets
    its own value or deletes this one, and several do.

    The development plugin roots are cleared for the same reason, in the other
    direction. Whoever is running the suite may well have that variable set --
    it is what a plugin developer sets and leaves set -- and the loader would
    then import their working tree into the test process, which is neither the
    plugin the test wrote nor code the suite has any business executing.
    """
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path / "user_data"))
    monkeypatch.delenv(DEV_PLUGINS_ENV_VAR, raising=False)


@pytest.fixture(autouse=True)
def _clear_example_payload_analysis_caches() -> None:
    """Reset the shared example payloads' derived-value caches.

    Both example payloads are module-level singletons in production code,
    imported by several test files. Their ``analysis_cache`` would otherwise
    carry values from one test into the next.
    """
    MOVIE_EXAMPLE_PAYLOAD.analysis_cache.clear()
    SERIES_EXAMPLE_PAYLOAD.analysis_cache.clear()


# --------------------------------------------------------------------------
# a real source-less job bundle
# --------------------------------------------------------------------------
def write_sample_media(path: Path) -> Path:
    """Write a tiny real media file libmediainfo can actually parse.

    A synthesized WAV keeps this dependency-free -- no encoder needed -- while
    still exercising the real libmediainfo parse/dump path rather than a
    stubbed one.
    """
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(48000)
        handle.writeframes(struct.pack("<" + "h" * 4800, *([0] * 4800)))
    return path


@dataclass(frozen=True)
class SourceLessBundle:
    """A saved job whose media no longer exists, and the paths it remembers."""

    job: SavedJob
    directory: Path
    working_dir: Path
    media: Path
    """Where the media *was*. Deliberately deleted -- do not recreate it."""

    images: list[Path]
    """The screenshots, inside the job directory. Also deleted by
    `strip_images()`."""

    def strip_images(self) -> None:
        """Remove the copied screenshots, leaving only their uploaded URLs.

        This is the state that matters most: a bundle with neither the media
        nor local image files, which can still upload anywhere it already has
        URLs for and must say so clearly anywhere it does not.
        """
        for image in self.images:
            image.unlink(missing_ok=True)


@pytest.fixture
def source_less_bundle(tmp_path: Path) -> SourceLessBundle:
    """A job bundle built by the real save path, with its media then deleted.

    Every "can this run without the source?" assertion is worth more against a
    bundle that genuinely has no source than against a mocked one, because the
    failure being guarded is precisely some code path reaching for a file
    nobody remembered it touched.
    """
    working_dir = tmp_path / "nfoforge"
    media = write_sample_media(tmp_path / "Example.Movie.2024.wav")
    screenshots = tmp_path / "processing" / "images"
    screenshots.mkdir(parents=True)
    originals = []
    for index in range(2):
        shot = screenshots / f"shot{index}.png"
        shot.write_bytes(b"\x89PNG" + bytes([index]))
        originals.append(shot)

    context = ProcessingContext()
    context.media_input.input_path = media
    context.media_input.media_type = MediaType.MOVIE
    context.media_input.working_dir = tmp_path / "working"
    context.media_input.file_list.append(media)
    context.media_input.file_list_mediainfo[media] = MediaInfo.parse(
        media, legacy_stream_display=True
    )
    context.media_input.input_kind = "file"
    context.media_input.content_size = media.stat().st_size
    context.media_search.title = "Example"
    context.media_search.year = 2024

    shared = context.shared_data
    shared.selected_trackers = [TrackerSelection.AITHER]
    shared.loaded_images = list(originals)
    shared.generated_images = True
    shared.tracker_image_hosts[TrackerSelection.AITHER] = ImageUploadFromTo(
        ImageSource.IMAGES, ImageHost.PIXHOST
    )
    uploaded = {
        index: ImageUploadData(url=f"https://pixhost/{index}.png", medium_url=None)
        for index in range(2)
    }
    shared.uploaded_images[TrackerSelection.AITHER] = dict(uploaded)
    shared.uploaded_image_hosts[TrackerSelection.AITHER] = ImageHost.PIXHOST
    shared.uploaded_images_by_host[ImageHost.PIXHOST] = dict(uploaded)
    shared.tracker_release_data[TrackerSelection.AITHER] = {
        "title": "Example 2024 1080p",
        "nfo": "the aither nfo",
    }

    job = build_job(
        "Example (2024)",
        JobSummary(title="Example", year=2024, trackers=["Aither"]),
        {},
        archived=True,
    )
    directory = job_dir(working_dir, job.job_id, ensure_exists=True)

    torrent = Torrent(path=media, private=True)
    torrent.generate()
    torrent.write(directory / "base.torrent")

    mediainfo_assets = capture_mediainfo(directory, [media])
    nfo_assets = capture_nfos(directory, shared.tracker_release_data)
    copied = copy_images(directory, list(originals))

    document = context_to_dict(context, mediainfo_assets, nfo_assets)
    document["shared_data"]["loaded_images"] = [str(image) for image in copied]
    document["base_torrent"] = {
        "media": str(media),
        "snapshot": base_torrent_snapshot(directory / "base.torrent"),
    }
    job.context = document
    save_job(job, working_dir)

    # the point of the fixture: from here nothing may reach for the media
    media.unlink()
    for original in originals:
        original.unlink()
    clear_restored_mediainfo()

    return SourceLessBundle(
        job=job,
        directory=directory,
        working_dir=working_dir,
        media=media,
        images=copied,
    )
