"""Coverage for reading/writing saved jobs and their schema migrations."""

import json
from pathlib import Path

import pytest

from src.backend.jobs import migrations, store
from src.backend.jobs.migrations import (
    JOB_SCHEMA_VERSION,
    JobMigrationError,
    check_migration_chain,
    migrate_document,
)
from src.backend.jobs.models import JobSummary
from src.backend.utils.working_dir import JOBS_DIR_NAME, jobs_dir


@pytest.fixture
def working_dir(tmp_path: Path) -> Path:
    return tmp_path / "nfoforge"


def _build(name: str = "My job", profile: str = "config") -> store.SavedJob:
    return store.build_job(
        name=name,
        summary=JobSummary(title="Example", year=2024, trackers=["Aither"]),
        context={"media_input": {}, "media_search": {}, "shared_data": {}},
        config_profile=profile,
    )


def test_save_and_load_round_trip(working_dir: Path) -> None:
    job = _build()

    path = store.save_job(job, working_dir)
    loaded = store.load_job(path)

    assert loaded.job_id == job.job_id
    assert loaded.name == "My job"
    assert loaded.schema_version == JOB_SCHEMA_VERSION
    assert loaded.config_profile == "config"
    assert loaded.summary.title == "Example"
    assert loaded.summary.trackers == ["Aither"]
    assert loaded.context == job.context


def test_jobs_live_beside_processing_not_inside_it(working_dir: Path) -> None:
    """Clean up empties everything but the jobs folder, so it must sit there."""
    path = store.save_job(_build(), working_dir)

    assert path.parent == jobs_dir(working_dir)
    assert path.parent.name == JOBS_DIR_NAME
    assert path.parent.parent == working_dir


def test_saved_file_is_json_not_pickle(working_dir: Path) -> None:
    job = _build()

    directory = store.save_job(job, working_dir)

    document = directory / store.JOB_DOCUMENT_NAME
    assert json.loads(document.read_text(encoding="utf-8"))["job_id"] == job.job_id


def test_a_directory_without_a_document_is_ignored(working_dir: Path) -> None:
    """A crash mid-save must not leave a job that loads with missing pieces."""
    store.save_job(_build("complete"), working_dir)
    half_written = jobs_dir(working_dir) / "half-written"
    (half_written / store.JOB_IMAGES_DIR_NAME).mkdir(parents=True)

    listings = store.list_jobs([working_dir])

    assert [listing.name for listing in listings] == ["complete"]


def test_deleting_a_job_removes_everything_it_owns(working_dir: Path) -> None:
    directory = store.save_job(_build(), working_dir)
    images = directory / store.JOB_IMAGES_DIR_NAME
    images.mkdir(parents=True, exist_ok=True)
    (images / "shot.png").write_bytes(b"x")
    (directory / store.JOB_BASE_TORRENT_NAME).write_bytes(b"d8:announce")

    store.delete_job(directory)

    assert not directory.exists()
    assert store.list_jobs([working_dir]) == []


def test_deleting_an_already_removed_job_is_not_an_error(working_dir: Path) -> None:
    directory = store.save_job(_build(), working_dir)

    store.delete_job(directory)
    store.delete_job(directory)


def test_blank_name_falls_back_rather_than_saving_untitled() -> None:
    assert store.build_job("   ", JobSummary(), {}).name == "Untitled job"


def test_list_jobs_is_newest_first(working_dir: Path) -> None:
    older = _build("older")
    older.created_at = "2026-01-01T00:00:00+00:00"
    newer = _build("newer")
    newer.created_at = "2026-06-01T00:00:00+00:00"
    store.save_job(older, working_dir)
    store.save_job(newer, working_dir)

    listings = store.list_jobs([working_dir])

    assert [listing.name for listing in listings] == ["newer", "older"]


def test_list_jobs_spans_several_working_directories(tmp_path: Path) -> None:
    """Each config profile can point somewhere else; all jobs must still list."""
    first, second = tmp_path / "one", tmp_path / "two"
    store.save_job(_build("from-first", profile="one"), first)
    store.save_job(_build("from-second", profile="two"), second)

    listings = store.list_jobs([first, second])

    assert {listing.name for listing in listings} == {"from-first", "from-second"}
    assert {listing.config_profile for listing in listings} == {"one", "two"}


def test_list_jobs_does_not_repeat_a_shared_directory(working_dir: Path) -> None:
    """Profiles commonly share a working directory; jobs must not double up."""
    store.save_job(_build(), working_dir)

    listings = store.list_jobs([working_dir, working_dir])

    assert len(listings) == 1


def test_list_jobs_ignores_a_directory_that_does_not_exist(
    tmp_path: Path, working_dir: Path
) -> None:
    store.save_job(_build(), working_dir)

    listings = store.list_jobs([working_dir, tmp_path / "never-created"])

    assert len(listings) == 1


def test_list_jobs_skips_a_corrupt_job_instead_of_failing(working_dir: Path) -> None:
    store.save_job(_build("good"), working_dir)
    broken = jobs_dir(working_dir) / "broken"
    broken.mkdir(parents=True)
    (broken / store.JOB_DOCUMENT_NAME).write_text("{not json", encoding="utf-8")

    listings = store.list_jobs([working_dir])

    assert [listing.name for listing in listings] == ["good"]


def test_loading_a_deleted_job_reports_it_clearly(working_dir: Path) -> None:
    directory = store.save_job(_build(), working_dir)
    store.delete_job(directory)

    with pytest.raises(store.JobStoreError):
        store.load_job(directory)


@pytest.mark.parametrize("job_id", ["", "../escape", "a/b", "c:\\d", ".", ".."])
def test_path_traversal_ids_are_rejected(job_id: str, working_dir: Path) -> None:
    with pytest.raises(store.JobStoreError):
        store.save_job(
            store.SavedJob(job_id=job_id, name="x", created_at="", nfoforge_version=""),
            working_dir,
        )


@pytest.mark.parametrize("name", ["notes", "important-data"])
def test_directories_outside_a_jobs_folder_are_refused(
    tmp_path: Path, name: str
) -> None:
    """Jobs are addressed by path; that must not become 'rmtree anything'."""
    victim = tmp_path / name
    victim.mkdir(parents=True)
    (victim / "keep.txt").write_text("important", encoding="utf-8")

    with pytest.raises(store.JobStoreError):
        store.delete_job(victim)
    assert (victim / "keep.txt").exists()


def test_corrupt_job_document_raises_a_clear_error(working_dir: Path) -> None:
    directory = jobs_dir(working_dir, ensure_exists=True) / "abc"
    directory.mkdir(parents=True)
    (directory / store.JOB_DOCUMENT_NAME).write_text("[]", encoding="utf-8")

    with pytest.raises(store.JobStoreError):
        store.load_job(directory)


def test_job_from_a_newer_build_is_refused_with_an_actionable_message() -> None:
    with pytest.raises(JobMigrationError, match="newer version"):
        migrate_document({"schema_version": JOB_SCHEMA_VERSION + 1})


def test_document_without_a_schema_version_is_refused() -> None:
    with pytest.raises(JobMigrationError):
        migrate_document({})


def test_current_version_document_passes_through_untouched() -> None:
    document = {"schema_version": JOB_SCHEMA_VERSION, "name": "x"}

    assert migrate_document(document) == document


def test_migration_chain_guard_catches_a_bump_without_a_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(migrations, "JOB_SCHEMA_VERSION", 3)
    monkeypatch.setattr(migrations, "MIGRATIONS", {1: lambda document: dict(document)})

    with pytest.raises(RuntimeError, match="migrations are incomplete"):
        check_migration_chain()


def test_write_job_document_rewrites_an_existing_job(working_dir: Path) -> None:
    job = store.build_job("original", JobSummary(), {"shared_data": {}})
    directory = store.save_job(job, working_dir)

    job.name = "renamed"
    returned = store.write_job_document(job, directory)

    assert returned == directory
    assert store.load_job(directory).name == "renamed"


def test_write_job_document_reports_unserializable_content(working_dir: Path) -> None:
    job = store.build_job("bad", JobSummary(), {"oops": object()})
    directory = store.job_dir(working_dir, job.job_id, ensure_exists=True)

    with pytest.raises(store.JobStoreError, match="cannot be saved"):
        store.write_job_document(job, directory)


def test_prune_unreferenced_nfos_keeps_only_what_the_context_points_at(
    working_dir: Path,
) -> None:
    job = store.build_job("job", JobSummary(), {})
    directory = store.job_dir(working_dir, job.job_id, ensure_exists=True)
    nfo_dir = directory / store.JOB_NFO_DIR_NAME
    nfo_dir.mkdir(parents=True)
    (nfo_dir / "aither.txt").write_text("kept", encoding="utf-8")
    (nfo_dir / "huno.txt").write_text("dropped", encoding="utf-8")

    store.prune_unreferenced_nfos(
        directory,
        {
            "shared_data": {
                "tracker_release_data": {
                    "AITHER": {"title": "t", "nfo_asset": "nfo/aither.txt"}
                }
            }
        },
    )

    assert {path.name for path in nfo_dir.iterdir()} == {"aither.txt"}


def test_prune_unreferenced_nfos_is_a_no_op_without_an_nfo_dir(
    working_dir: Path,
) -> None:
    job = store.build_job("job", JobSummary(), {})
    directory = store.job_dir(working_dir, job.job_id, ensure_exists=True)

    # must not raise
    store.prune_unreferenced_nfos(directory, {"shared_data": {}})
