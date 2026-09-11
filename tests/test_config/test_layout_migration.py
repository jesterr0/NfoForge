"""What the layout migration would do, before it is able to do anything.

Every test here builds a synthesised tree under `tmp_path` and asks for a plan.
Nothing in this module may write, move or delete: the point of planning as a
separate step is that it can be run against a real installation and shown to
someone before any of it happens.
"""

from pathlib import Path

from src.config.layout_migration import ActionKind, PlannedAction, plan_migration


def test_saved_jobs_at_the_root_are_planned_into_the_workspace(tmp_path: Path) -> None:
    """Saved jobs sat at the root of the data directory, which is now a layout.

    The pre-migration default working directory *was* the root of the data
    directory, so `jobs/` accumulated there. Leaving it would put deliberately
    saved work somewhere the new layout does not look, with an empty `workspace`
    beside it -- which is why this relocation runs whether or not a legacy
    installation is found or imported.
    """
    state_root = tmp_path / "user_data"
    (state_root / "jobs" / "job-1").mkdir(parents=True)
    (state_root / "jobs" / "job-1" / "base.torrent").write_bytes(b"x" * 10)

    plan = plan_migration(state_root)

    assert plan.actions == (
        PlannedAction(
            kind=ActionKind.MOVE,
            source=state_root / "jobs",
            destination=state_root / "workspace" / "jobs",
            size=10,
        ),
    )


def test_a_run_folder_at_the_root_is_planned_into_the_workspace(tmp_path: Path) -> None:
    """Run output landed at the root too, for the same reason saved jobs did.

    The name is the tell: `generate_unique_date_name` stamps a truncated release
    name with a date and time, so a folder carrying that suffix is one this
    application created. Matching on shape is what lets the plan leave anything
    it does not recognise alone.
    """
    state_root = tmp_path / "user_data"
    run_folder = state_root / "Example.Release.Name.2024_09.11.2026_10.09.39"
    run_folder.mkdir(parents=True)
    (run_folder / "screenshot.png").write_bytes(b"y" * 4)

    plan = plan_migration(state_root)

    assert (
        PlannedAction(
            kind=ActionKind.MOVE,
            source=run_folder,
            destination=state_root / "workspace" / run_folder.name,
            size=4,
        )
        in plan.actions
    )


def test_a_directory_the_application_did_not_create_is_left_alone(
    tmp_path: Path,
) -> None:
    """Anything unrecognised is the user's, and the plan does not touch it.

    The data directory was the default working directory, so a user may well
    have put their own folders there. Moving one because it happened to sit at
    the root would be the migration losing track of someone's files, which is
    the failure this whole exercise exists to avoid.
    """
    state_root = tmp_path / "user_data"
    theirs = state_root / "notes and scratch files"
    theirs.mkdir(parents=True)
    (theirs / "thoughts.txt").write_text("keep me", encoding="utf-8")

    plan = plan_migration(state_root)

    assert plan.actions == ()


def test_the_index_cache_is_planned_into_the_cache_directory(tmp_path: Path) -> None:
    """The cache is relocated rather than discarded.

    A rename costs the same as a delete on one volume, so deleting it would only
    buy the user a re-index. It is moved out of the root because the new layout
    gives it a home of its own.
    """
    state_root = tmp_path / "user_data"
    cache = state_root / "frameforge_indexes"
    cache.mkdir(parents=True)
    (cache / "index.ffindex").write_bytes(b"z" * 7)

    plan = plan_migration(state_root)

    assert (
        PlannedAction(
            kind=ActionKind.MOVE,
            source=cache,
            destination=state_root / "cache" / "frameforge_indexes",
            size=7,
        )
        in plan.actions
    )
