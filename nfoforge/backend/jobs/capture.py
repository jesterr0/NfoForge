"""Turning a configured run into a saved job, and a finished run into an archive.

The desktop Process page used to do all of this inline. It lives here so a
headless run can save and archive jobs the same way: every function takes the
run's `ProcessingContext` and raises on failure, and asking the user anything
(a job name, whether to save at all) stays with the caller.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import shutil
from typing import Any, cast

from nfoforge.backend.jobs.assets import (
    JobAssetError,
    base_torrent_snapshot,
    capture_mediainfo,
    capture_nfos,
    copy_base_torrent,
    copy_images,
    fingerprint_files,
    torrent_content_files,
)
from nfoforge.backend.jobs.codec import (
    context_to_dict,
    filter_context_document,
    mediainfo_sources,
)
from nfoforge.backend.jobs.models import JobSummary, SavedJob
from nfoforge.backend.jobs.store import (
    build_job,
    job_dir,
    load_job,
    prune_unreferenced_nfos,
    save_job,
    write_job_document,
)
from nfoforge.backend.jobs.update import rebuild_job_document
from nfoforge.backend.torrents import BASE_TORRENT_SUFFIX
from nfoforge.backend.upload_retry import TrackerRunOutcome
from nfoforge.backend.utils.file_utilities import release_stem
from nfoforge.context.processing_context import ProcessingContext
from nfoforge.enums.tracker_selection import TrackerSelection
from nfoforge.logger.nfo_forge_logger import LOG

_LANDED = {TrackerRunOutcome.UPLOADED, TrackerRunOutcome.INJECTION_FAILED}


def measure_content_size(input_path: Path) -> int | None:
    """Total bytes of the release, or None when it cannot be measured.

    Matches what a generated torrent reports (`Torrent.size`), so a job that
    has a base torrent and one that does not record the same number: the sum of
    every file for a pack, the file's own size for a single file. `stat()` on a
    directory would report the directory entry instead, which is not a release
    size at all.
    """
    try:
        if input_path.is_dir():
            return sum(
                path.stat().st_size for path in torrent_content_files(input_path)
            )
        return input_path.stat().st_size if input_path.is_file() else None
    except OSError as error:
        LOG.warning(
            LOG.LOG_SOURCE.BE,
            f"Could not measure the size of '{input_path}' for this job: {error}",
        )
        return None


def first_generated_torrent(context: ProcessingContext) -> Path | None:
    """The neutral base this run hashed, usable as a clone source.

    Hashing the media is the single most expensive step, so a job that can
    carry a finished torrent lets a later run skip it entirely.

    Only the base will do. The tracker torrents one level down are stamped
    with a tracker's announce, source and comment, and a UNIT3D one is
    additionally whatever that tracker's server handed back on upload --
    carrying any of those forward would seed the next run from one
    tracker's artifact. `_prepare_base_torrent` always writes the base
    here, including when the run itself reused a carried one, so this is
    the single place to look.
    """
    working_dir = context.media_input.working_dir
    input_path = context.media_input.input_path
    if not working_dir or not input_path:
        return None
    base = working_dir / (
        f"{release_stem(input_path, context.media_input.input_is_directory())}"
        f"{BASE_TORRENT_SUFFIX}"
    )
    return base if base.is_file() else None


def default_job_name(context: ProcessingContext) -> str:
    """Best available human name for this release."""
    title = context.media_search.title
    if title:
        year = context.media_search.year
        return f"{title} ({year})" if year else title
    input_path = context.media_input.input_path
    return input_path.stem if input_path else "Untitled job"


def job_summary(
    context: ProcessingContext,
    keep_trackers: set[TrackerSelection] | None = None,
) -> JobSummary:
    input_path = context.media_input.input_path
    media_type = context.media_input.media_type
    return JobSummary(
        title=context.media_search.title,
        year=context.media_search.year,
        media_type=str(media_type) if media_type else None,
        input_name=input_path.name if input_path else None,
        input_path=str(input_path) if input_path else "",
        file_count=len(context.media_input.file_list),
        # `keep_trackers` is the authority when given. Filtering the run's
        # image-host map by it would drop a tracker the run never touched --
        # one left pending by an earlier run, whose row does not exist this
        # time -- and the summary is what the picker shows and what decides
        # whether a saved job can still be opened.
        trackers=sorted(str(tracker) for tracker in keep_trackers)
        if keep_trackers is not None
        else [str(tracker) for tracker in context.shared_data.tracker_image_hosts],
    )


def build_job_document(
    context: ProcessingContext,
    directory: Path,
    keep_trackers: set[TrackerSelection] | None = None,
) -> dict[str, Any]:
    """Capture the job's assets, then serialize it pointing at those copies.

    Everything a resumed run needs is copied beside the job so it stops
    depending on `processing/`, which Clean Up is meant to empty. When
    `keep_trackers` is given, only the NFOs for those trackers are
    captured -- a narrowed job must not keep sidecars for trackers it no
    longer covers.
    """
    media_input = context.media_input
    input_path = media_input.require_input_path()
    media_input.input_kind = "directory" if input_path.is_dir() else "file"
    # Recorded whether or not a torrent was generated. Without it the two
    # trackers that size a disc release fall back to reading the input path
    # off the filesystem (`beyondhd.py`, `passthepopcorn.py`), which a
    # source-less run cannot do -- and this is the last moment the media is
    # guaranteed to be there to measure.
    if media_input.content_size is None:
        media_input.content_size = measure_content_size(input_path)

    # MediaInfo is captured for every object the context can reach, not
    # just the run's own file list: a plugin holding a per-episode source
    # MediaInfo needs its dump stored too, or a resumed run has nothing to
    # rebuild it from
    mediainfo_assets = capture_mediainfo(directory, list(mediainfo_sources(context)))

    # copied even when the images already uploaded and their URLs were
    # recorded: changing a tracker's image host on resume invalidates those
    # URLs and needs the local files back
    copied_images = copy_images(
        directory,
        [Path(image) for image in (context.shared_data.loaded_images or ())],
    )

    base_torrent = first_generated_torrent(context)
    snapshot: dict[str, Any] | None = None
    if base_torrent:
        copy_base_torrent(directory, base_torrent)
        snapshot = base_torrent_snapshot(base_torrent)
        media_input.content_size = cast(int, snapshot["content_size"])

    # a prepared job's NFOs are the ones that get uploaded, so they cannot
    # be left in `processing/` where Clean Up would take them -- and a
    # narrowed job must not keep sidecars for trackers it no longer covers
    release_data = context.shared_data.tracker_release_data
    if keep_trackers is not None:
        release_data = {
            tracker: release
            for tracker, release in release_data.items()
            if tracker in keep_trackers
        }
    nfo_assets = capture_nfos(directory, release_data)

    document = context_to_dict(context, mediainfo_assets, nfo_assets)
    if copied_images:
        document["shared_data"]["loaded_images"] = [
            str(image) for image in copied_images
        ]
    if base_torrent:
        if snapshot is None:
            raise JobAssetError("Could not capture the base torrent snapshot")
        document["base_torrent"] = {
            "media": str(input_path),
            "snapshot": snapshot,
            # every file, not just the first: the torrent is built from
            # `input_path`, so one file of a pack cannot vouch for the rest
            "fingerprints": fingerprint_files(torrent_content_files(input_path)),
        }
    if keep_trackers is not None:
        document = filter_context_document(document, keep_trackers)
    return document


def save_new_job(
    context: ProcessingContext,
    *,
    name: str,
    working_dir: Path,
    config_profile: str | None,
    keep_trackers: set[TrackerSelection] | None = None,
) -> tuple[SavedJob, Path]:
    """Persist this configured run so it can be processed later.

    Deliberately does not dupe check: results would be stale by the time
    the job is actually run, so that check stays where it is, immediately
    before uploading.

    `keep_trackers` narrows the job to a subset, which is how a partially
    completed run is deferred -- the trackers that already uploaded are
    left out entirely rather than being marked as done, so the saved job
    cannot re-upload them.

    Raises `FileNotFoundError`/`RuntimeError` when the input media is no
    longer there, and `JobAssetError`/`JobCodecError`/`JobStoreError`/`OSError`
    when the job could not be written. Nothing is left on disk on failure.
    """
    media_input = context.media_input
    input_path = media_input.require_input_path()
    media_input.input_kind = "directory" if input_path.is_dir() else "file"
    # capturing MediaInfo reads every input file, so the comparison source
    # has to be there too when one is in play
    media_input.require_existing_media_paths(
        include_comparison=bool(media_input.comparison_pair)
    )

    job = build_job(
        name=name,
        summary=job_summary(context, keep_trackers),
        context={},
        config_profile=config_profile,
    )
    directory = job_dir(working_dir, job.job_id, ensure_exists=True)
    try:
        job.context = build_job_document(context, directory, keep_trackers)
        return job, save_job(job, working_dir)
    except BaseException:
        # the directory only holds half-captured assets at this point and has
        # no job.json, so remove it rather than leaving a stub behind
        shutil.rmtree(directory, ignore_errors=True)
        raise


def archive_completed_run(
    context: ProcessingContext,
    outcomes: Mapping[TrackerSelection, TrackerRunOutcome],
    *,
    working_dir: Path,
    config_profile: str | None,
) -> SavedJob:
    """Persist one reusable archive and reconcile tracker outcomes into it.

    A run that started from an archive updates it in place; any other run
    creates a new one, which is removed again if it could not be written.
    On success the context is pointed at the archive, so the next run from
    it extends the same one.
    """
    landed = {tracker for tracker, outcome in outcomes.items() if outcome in _LANDED}
    uncertain = {
        tracker
        for tracker, outcome in outcomes.items()
        if outcome is TrackerRunOutcome.MAY_HAVE_UPLOADED
    }
    existing_path = context.loaded_job_path
    created_directory: Path | None = None
    try:
        if existing_path is not None:
            job = load_job(existing_path)
            directory = existing_path
        else:
            job = build_job(
                name=default_job_name(context),
                summary=JobSummary(),
                context={},
                config_profile=config_profile,
                archived=True,
            )
            directory = job_dir(working_dir, job.job_id, ensure_exists=True)
            created_directory = directory

        uploaded_all = context.loaded_uploaded_trackers | landed
        uncertain_all = (context.loaded_uncertain_trackers | uncertain) - landed
        # A tracker left pending by an *earlier* run is not in `outcomes`, but
        # its prepared title and NFO are still on the context. Narrowing to
        # only this run's leftovers would drop them from the document, and
        # `prune_unreferenced_nfos` would then delete the sidecars -- silently
        # discarding prepared work whose only way back is preparing that
        # tracker over again.
        pending = (set(outcomes) | set(context.shared_data.tracker_release_data)) - (
            uploaded_all | uncertain_all
        )

        if created_directory is not None:
            document = build_job_document(context, directory, None)
        else:
            document = rebuild_job_document(job, directory, context)

        # An uncertain tracker keeps its title, NFO and image state while
        # staying out of `selected_trackers`, so nothing can resume into a
        # second upload -- and resolving it as "never landed" has the prepared
        # work to put back. Narrowing it away instead left only its name, and
        # offered a resolution the data could not support.
        job.context = filter_context_document(
            document, pending, retain_data_for=uncertain_all
        )
        job.archived = True
        job.uploaded_trackers = sorted(tracker.name for tracker in uploaded_all)
        job.uncertain_trackers = sorted(tracker.name for tracker in uncertain_all)
        job.summary = job_summary(context, pending)
        job.summary.uploaded_trackers = sorted(str(tracker) for tracker in uploaded_all)
        job.summary.uncertain_trackers = sorted(
            str(tracker) for tracker in uncertain_all
        )
        write_job_document(job, directory)
    except BaseException:
        if created_directory is not None:
            shutil.rmtree(created_directory, ignore_errors=True)
        raise

    try:
        prune_unreferenced_nfos(directory, job.context)
    except OSError as error:
        LOG.warning(
            LOG.LOG_SOURCE.BE, f"Archive saved but stale NFO cleanup failed: {error}"
        )

    context.loaded_job_path = directory
    context.loaded_job_id = job.job_id
    context.loaded_job_name = job.name
    context.loaded_job_archived = True
    context.loaded_uploaded_trackers = uploaded_all
    context.loaded_uncertain_trackers = uncertain_all
    return job


def update_prepared_archive(context: ProcessingContext) -> SavedJob | None:
    """Update a loaded archive after preparing newly added trackers.

    Returns `None` when the run did not come from an archive: only an archive
    is updated in place. Preparing an ordinary saved job keeps the named save
    it always had -- silently overwriting the job the user opened is not what
    "Prepare Job" has ever meant, and that job still has its media, so
    `save_new_job` can capture MediaInfo the normal way. An archive cannot: it
    may have no source left, which is what its stored assets are for.
    """
    path = context.loaded_job_path
    if not context.loaded_job_archived or path is None:
        return None
    job = load_job(path)
    job.context = rebuild_job_document(job, path, context)
    job.summary = job_summary(context)
    job.summary.uploaded_trackers = sorted(
        str(tracker) for tracker in context.loaded_uploaded_trackers
    )
    job.summary.uncertain_trackers = sorted(
        str(tracker) for tracker in context.loaded_uncertain_trackers
    )
    write_job_document(job, path)
    return job
