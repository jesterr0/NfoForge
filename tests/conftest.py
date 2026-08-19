"""Shared pytest fixtures/config for the whole suite.

Sets the Qt platform plugin to "offscreen" before Qt is ever imported so the
suite is safe to run on a headless CI runner (no X server/display required).
Provides one shared ``QApplication`` for the whole test session. Qt permits
only one application instance per process, and all widget tests can reuse it.
"""

from dataclasses import dataclass
import os

# must be set before any PySide6/Qt import happens, anywhere in the test
# session, so use setdefault to respect an explicit override (e.g. a
# developer running with a real display) while still defaulting to
# offscreen for CI/headless runs.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import struct
import wave

from pymediainfo import MediaInfo
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QDialog
import pytest
from torf import Torrent

from src.backend.jobs import (
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
from src.backend.jobs.models import JobSummary
from src.backend.utils.example_parsed_movie_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD as MOVIE_EXAMPLE_PAYLOAD,
)
from src.backend.utils.example_parsed_series_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD as SERIES_EXAMPLE_PAYLOAD,
)
from src.backend.utils.media_info_utils import clear_restored_mediainfo
from src.context.processing_context import ProcessingContext
from src.enums.image_host import ImageHost, ImageSource
from src.enums.media_type import MediaType
from src.enums.tracker_selection import TrackerSelection
from src.packages.custom_types import ImageUploadData, ImageUploadFromTo


@pytest.fixture(scope="session", autouse=True)
def qapp() -> QApplication | QCoreApplication:
    """Create one QApplication for all tests that construct QWidgets."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def _no_blocking_modals(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn an accidentally-opened modal into a failure instead of a hang.

    ``QDialog.exec()`` and ``QMenu.exec()`` start a nested event loop and do
    not return until something closes them. In a test there is nobody to
    close them, so reaching one is not a test that fails -- it is a run that
    stops dead, producing no output and naming no culprit. That is not
    hypothetical: when the job rename prompt moved off
    ``QInputDialog.getText()`` to a hand-built dialog, the tests stubbing the
    old call sailed straight into a modal that never closed, and the suite
    simply stopped part-way through with a pegged CPU.

    Patching ``QDialog`` covers ``QMessageBox``, ``QInputDialog``,
    ``QFileDialog``, ``QWizard`` and the rest: none of them define their own
    ``exec``, so this is the one they all resolve to.

    ``QMenu.exec`` is deliberately *not* patched, and cannot usefully be.
    PySide6 exposes it as a ``staticmethod`` (it has a static overload), and
    instance lookup on ``menu.exec`` returns the built-in straight off the C++
    type without ever consulting the class attribute -- so a patch here would
    look like it applied while a populated ``QMenu.exec()`` went on blocking
    exactly as before. That case is left to the ``timeout`` in
    ``pyproject.toml``, which does not care how the call blocks.

    A test that means to reach one of these stubs it deliberately, patching
    ``QDialog.exec`` -- the class the method actually lives on -- with the
    answer it wants. Doing that overrides this guard for that test, and
    restores it afterwards.
    """

    def refuse(self: object, *_args: object, **_kwargs: object) -> int:
        raise AssertionError(
            f"{type(self).__name__}.exec() opened a real modal dialog, which "
            "would block this test forever -- there is no user to dismiss it. "
            "Stub the prompt instead: patch `QDialog.exec` (and whatever "
            "supplies its result, e.g. `textValue`) with the answer this test "
            "needs."
        )

    monkeypatch.setattr(QDialog, "exec", refuse)


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
