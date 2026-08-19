"""Re-serializing a run into a job that already exists on disk.

Three call sites need this -- archiving a finished run into the job it was
loaded from, saving newly prepared trackers back into an archive, and the queue
recording what a run produced -- and each had grown its own version. They had
drifted: two skipped `copy_images`, so an updated archive could end up pointing
at screenshots under `processing/`, which Settings -> General "Clean Up" is
meant to empty; the third re-narrowed the document *as loaded from disk*, so
nothing the run produced was written at all.

Updating differs from a first save in one way that matters: the media may be
gone. An archive exists precisely so a release can be uploaded again without
it, so anything already captured is carried forward rather than re-derived, and
only genuinely new state is captured afresh.

Qt-free, like the rest of the package.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from src.backend.jobs.assets import capture_mediainfo, capture_nfos, copy_images
from src.backend.jobs.codec import JobCodecError, context_to_dict, mediainfo_sources
from src.backend.jobs.models import SavedJob
from src.context.processing_context import ProcessingContext
from src.logger.nfo_forge_logger import LOG

__all__ = ["rebuild_job_document"]


def rebuild_job_document(
    job: SavedJob, directory: Path, context: ProcessingContext
) -> dict[str, Any]:
    """Serialize `context` into the job at `directory`, keeping what it owns.

    Returns the new document; writing it is the caller's business, as is any
    narrowing it wants to apply afterwards.
    """
    old_context = job.context if isinstance(job.context, dict) else {}

    mediainfo_assets = _carried_mediainfo_assets(old_context)
    mediainfo_assets.update(
        _capture_new_mediainfo(directory, context, mediainfo_assets)
    )
    if not mediainfo_assets and mediainfo_sources(context):
        # Every consumer of a source-less job reads MediaInfo from these
        # sidecars. Writing a document with none while the context clearly has
        # MediaInfo to store would produce an archive that loads and then fails
        # at the first token that needs it.
        raise JobCodecError(
            "Could not capture or carry forward any MediaInfo for this job"
        )

    nfo_assets = capture_nfos(directory, context.shared_data.tracker_release_data)
    document = context_to_dict(context, mediainfo_assets, nfo_assets)
    _carry_held_image_hosts(document, old_context)

    images = _job_local_images(directory, context.shared_data.loaded_images or ())
    if images:
        document["shared_data"]["loaded_images"] = [str(image) for image in images]

    # Immutable release facts about a torrent this job already carries. They
    # describe `base.torrent` in the directory, which an update never touches,
    # so they are copied across rather than recomputed from media that may be
    # gone.
    base_details = old_context.get("base_torrent")
    if isinstance(base_details, dict):
        document["base_torrent"] = dict(base_details)

    return document


def _carry_held_image_hosts(
    document: dict[str, Any], old_context: dict[str, Any]
) -> None:
    """Keep the image host of a tracker this run built no row for.

    `tracker_image_hosts` mirrors the process page's tracker rows, so a run
    that adds one tracker to an archive re-serializes the map with only that
    tracker in it. Everything else a held-back tracker owns survives on the
    context and comes through untouched -- its frozen title and NFO, the URLs
    its screenshots already got -- so this was the one piece of its state that
    an update quietly dropped.

    That mattered when the tracker came back: resolving an unconfirmed upload
    as "it never landed" re-selects it, and the process page then had no stored
    choice to restore and fell back to the *global* last-used preference for
    that tracker -- a different host than the job chose, whose stored URLs the
    run could then not reuse.

    Scoped to trackers the job still holds prepared work for, so it carries
    what `filter_context_document(retain_data_for=...)` is about to keep rather
    than resurrecting a tracker that has been narrowed away for good.
    """
    shared = document.get("shared_data")
    old_shared = old_context.get("shared_data")
    if not isinstance(shared, dict) or not isinstance(old_shared, dict):
        return

    hosts = shared.get("tracker_image_hosts")
    old_hosts = old_shared.get("tracker_image_hosts")
    release_data = shared.get("tracker_release_data")
    if (
        not isinstance(hosts, dict)
        or not isinstance(old_hosts, dict)
        or not isinstance(release_data, dict)
    ):
        return

    for name, entry in old_hosts.items():
        if name in hosts or name not in release_data:
            continue
        # copied rather than shared, so the rebuilt document does not alias
        # the one still held as `job.context`
        hosts[name] = dict(entry) if isinstance(entry, dict) else entry


def _carried_mediainfo_assets(
    old_context: dict[str, Any],
) -> dict[Path, dict[str, str]]:
    """The sidecars the stored document already points at."""
    media_input = old_context.get("media_input")
    raw_assets = (
        media_input.get("mediainfo_assets") if isinstance(media_input, dict) else None
    )
    if not isinstance(raw_assets, dict):
        return {}
    return {
        Path(raw_path): dict(names)
        for raw_path, names in raw_assets.items()
        if isinstance(raw_path, str) and isinstance(names, dict)
    }


def _capture_new_mediainfo(
    directory: Path,
    context: ProcessingContext,
    already_stored: dict[Path, dict[str, str]],
) -> dict[Path, dict[str, str]]:
    """Store dumps for any MediaInfo this job does not already cover.

    A file that is no longer on disk cannot be captured, which is the normal
    state of an archive rather than an error -- so it is warned about and
    skipped. It only costs something when the object is *also* not already
    stored, and then only that one object.
    """
    missing = [
        path for path in mediainfo_sources(context) if path not in already_stored
    ]
    if not missing:
        return {}

    capturable: list[Path] = []
    for path in missing:
        if path.is_file():
            capturable.append(path)
        else:
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                f"Cannot store MediaInfo for '{path}' while updating this job: the "
                "file is no longer available and the job has no dump for it",
            )
    return capture_mediainfo(directory, capturable)


def _job_local_images(directory: Path, images: Iterable[Path]) -> list[Path]:
    """Bring every screenshot inside the job directory, keeping positions.

    One entry out per entry in: `uploaded_images` is keyed by a screenshot's
    index, so the list has to keep its shape even when an entry cannot be
    copied. An image already inside the job is left exactly where it is --
    copying it again on every update would fill the directory with numbered
    duplicates of the same screenshot.
    """
    root = directory.resolve(strict=False)
    local: list[Path] = []
    for image in images:
        image = Path(image)
        if _is_inside(root, image):
            local.append(image)
            continue
        copied = copy_images(directory, [image])
        local.append(copied[0] if copied else image)
    return local


def _is_inside(root: Path, path: Path) -> bool:
    try:
        return path.resolve(strict=False).is_relative_to(root)
    except OSError:
        return False
