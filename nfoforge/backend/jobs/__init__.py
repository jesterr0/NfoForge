"""Saving a configured upload run to disk and restoring it later.

A job captures everything the process page needs to run an upload that was
configured earlier, so a release can be set up now and uploaded whenever the
user is ready -- including after the application has been closed and
reopened.

The package is deliberately free of any Qt imports so it can be unit tested
without launching the application, the same convention `nfoforge/config`
follows.
"""

from nfoforge.backend.jobs.assets import (
    JobAssetError,
    MediaFingerprint,
    archived_base_is_valid,
    base_torrent_path,
    base_torrent_snapshot,
    capture_mediainfo,
    capture_nfos,
    copy_base_torrent,
    copy_images,
    fingerprint_files,
    fingerprints_match,
    read_job_asset,
    template_fingerprint,
    torrent_content_files,
)
from nfoforge.backend.jobs.capture import (
    archive_completed_run,
    build_job_document,
    default_job_name,
    first_generated_torrent,
    job_summary,
    measure_content_size,
    save_new_job,
    update_prepared_archive,
)
from nfoforge.backend.jobs.codec import (
    JobCodecError,
    context_from_dict,
    context_to_dict,
    filter_context_document,
    mediainfo_sources,
    mediainfo_xml,
    reselect_trackers,
)
from nfoforge.backend.jobs.migrations import JOB_SCHEMA_VERSION, JobMigrationError
from nfoforge.backend.jobs.models import JobListing, JobSummary, SavedJob
from nfoforge.backend.jobs.store import (
    JobStoreError,
    build_job,
    delete_job,
    job_dir,
    jobs_dir,
    list_jobs,
    load_job,
    prune_unreferenced_nfos,
    save_job,
    write_job_document,
)
from nfoforge.backend.jobs.update import rebuild_job_document
from nfoforge.backend.jobs.values import UnencodableValue, decode_value, encode_value

__all__ = [
    "JOB_SCHEMA_VERSION",
    "JobAssetError",
    "JobCodecError",
    "JobListing",
    "JobMigrationError",
    "JobStoreError",
    "JobSummary",
    "MediaFingerprint",
    "SavedJob",
    "UnencodableValue",
    "archive_completed_run",
    "archived_base_is_valid",
    "base_torrent_path",
    "base_torrent_snapshot",
    "build_job",
    "build_job_document",
    "capture_mediainfo",
    "capture_nfos",
    "context_from_dict",
    "context_to_dict",
    "copy_base_torrent",
    "copy_images",
    "decode_value",
    "default_job_name",
    "delete_job",
    "encode_value",
    "filter_context_document",
    "fingerprint_files",
    "fingerprints_match",
    "first_generated_torrent",
    "job_dir",
    "job_summary",
    "jobs_dir",
    "list_jobs",
    "load_job",
    "measure_content_size",
    "mediainfo_sources",
    "mediainfo_xml",
    "prune_unreferenced_nfos",
    "read_job_asset",
    "rebuild_job_document",
    "reselect_trackers",
    "save_job",
    "save_new_job",
    "template_fingerprint",
    "torrent_content_files",
    "update_prepared_archive",
    "write_job_document",
]
