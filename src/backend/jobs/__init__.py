"""Saving a configured upload run to disk and restoring it later.

A job captures everything the process page needs to run an upload that was
configured earlier, so a release can be set up now and uploaded whenever the
user is ready -- including after the application has been closed and
reopened.

The package is deliberately free of any Qt imports so it can be unit tested
without launching the application, the same convention `src/config`
follows.
"""

from src.backend.jobs.assets import (
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
from src.backend.jobs.codec import (
    JobCodecError,
    context_from_dict,
    context_to_dict,
    filter_context_document,
    mediainfo_sources,
    mediainfo_xml,
    reselect_trackers,
)
from src.backend.jobs.migrations import JOB_SCHEMA_VERSION, JobMigrationError
from src.backend.jobs.models import JobListing, JobSummary, SavedJob
from src.backend.jobs.store import (
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
from src.backend.jobs.update import rebuild_job_document
from src.backend.jobs.values import UnencodableValue, decode_value, encode_value

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
    "base_torrent_path",
    "base_torrent_snapshot",
    "archived_base_is_valid",
    "build_job",
    "capture_mediainfo",
    "capture_nfos",
    "context_from_dict",
    "context_to_dict",
    "copy_base_torrent",
    "copy_images",
    "decode_value",
    "delete_job",
    "encode_value",
    "filter_context_document",
    "fingerprint_files",
    "fingerprints_match",
    "job_dir",
    "jobs_dir",
    "list_jobs",
    "load_job",
    "mediainfo_sources",
    "mediainfo_xml",
    "prune_unreferenced_nfos",
    "read_job_asset",
    "rebuild_job_document",
    "reselect_trackers",
    "save_job",
    "template_fingerprint",
    "torrent_content_files",
    "write_job_document",
]
