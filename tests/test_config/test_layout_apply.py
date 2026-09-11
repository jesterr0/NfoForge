"""Carrying out a plan, which is the only code here that can lose data.

Every test builds a synthesised tree under `tmp_path`. The first test is not
about behaviour at all: it is the guarantee the rest of the module is written
under, and it is checked first because it is the one that cannot be restored by
fixing a bug later.
"""

import ast
from pathlib import Path

import pytest

from src.config.layout_apply import (
    Diversion,
    MigrationError,
    apply_plan,
    migrate_layout,
)
from src.config.layout_migration import (
    ActionKind,
    MigrationPlan,
    PlannedAction,
    plan_migration,
)
from src.config.layout_version import (
    CURRENT_LAYOUT_VERSION,
    LayoutRecordError,
    read_layout_version,
    write_layout_version,
)
from tests.repo_paths import REPO_ROOT

FORBIDDEN_CALLS = frozenset({"unlink", "rmtree", "rmdir", "remove", "move"})
"""Every way this module could remove something a user owns.

`move` is on the list because `shutil.move` falls back to copying and then
deleting its source, which makes it a delete wearing another name.
"""


def _calls_made_in(module: Path) -> set[str]:
    """Every function name called in `module`, however it was reached.

    Parsed rather than searched, so that prose explaining why something is not
    used cannot fail the check and, more importantly, cannot pass it either. A
    comment saying "we never delete" is not evidence; the absence of a call is.
    """
    called: set[str] = set()
    for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute):
            called.add(node.func.attr)
        elif isinstance(node.func, ast.Name):
            called.add(node.func.id)
    return called


def test_the_migration_contains_no_way_to_delete_anything() -> None:
    """The safety property, asserted against the source rather than promised.

    A migration that cannot delete cannot destroy a user's data, however wrong
    the rest of it turns out to be.

    The cost is accepted deliberately: a run that fails part way leaves a
    partial copy behind for the user to remove. Leaving litter is a better
    failure than clearing a directory that turned out to hold something else.
    """
    offending = _calls_made_in(REPO_ROOT / "src" / "config" / "layout_apply.py") & (
        FORBIDDEN_CALLS
    )

    assert not offending, (
        f"layout_apply.py calls {sorted(offending)}, giving the migration a way "
        "to delete user data. Moves are renames and copies leave their source "
        "alone; if something genuinely needs removing, the user removes it."
    )


def test_a_planned_move_relocates_the_entry(tmp_path: Path) -> None:
    """A move within the data directory is a rename, and has to happen once.

    The destination's parent will not exist on a first migration, since the
    whole point is that the layout it belongs to is new.
    """
    state_root = tmp_path / "user_data"
    source = state_root / "jobs"
    source.mkdir(parents=True)
    (source / "saved.torrent").write_bytes(b"j" * 12)
    destination = state_root / "workspace" / "jobs"

    plan = MigrationPlan(
        actions=(
            PlannedAction(
                kind=ActionKind.MOVE,
                source=source,
                destination=destination,
                size=12,
            ),
        )
    )

    apply_plan(plan)

    assert (destination / "saved.torrent").read_bytes() == b"j" * 12
    assert not source.exists()


def test_a_planned_copy_duplicates_a_directory_and_leaves_the_source(
    tmp_path: Path,
) -> None:
    """The source is an installation the user still has, and keeps.

    They are told to review it before deleting it, which is only a choice if it
    is still intact when the migration finishes.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    source = tmp_path / "install" / "bundle" / "runtime" / "templates"
    source.mkdir(parents=True)
    (source / "a.jinja").write_bytes(b"t" * 9)
    destination = state_root / "templates"

    apply_plan(
        MigrationPlan(
            actions=(
                PlannedAction(
                    kind=ActionKind.COPY,
                    source=source,
                    destination=destination,
                    size=9,
                ),
            )
        )
    )

    assert (destination / "a.jinja").read_bytes() == b"t" * 9
    assert (source / "a.jinja").read_bytes() == b"t" * 9


def test_a_planned_copy_handles_a_single_file(tmp_path: Path) -> None:
    """Program preferences are one file, and they are renamed on the way."""
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    source = tmp_path / "install" / "bundle" / "runtime" / "config" / "program"
    source.mkdir(parents=True)
    conf = source / "conf.toml"
    conf.write_bytes(b"k" * 4)
    destination = state_root / "config" / "program.toml"

    apply_plan(
        MigrationPlan(
            actions=(
                PlannedAction(
                    kind=ActionKind.COPY,
                    source=conf,
                    destination=destination,
                    size=4,
                ),
            )
        )
    )

    assert destination.read_bytes() == b"k" * 4
    assert conf.read_bytes() == b"k" * 4


def test_an_incomplete_copy_is_refused_rather_than_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A copy that lost something must not be reported as having worked.

    Since nothing is ever deleted, a short copy is recoverable -- the original
    is still there. What makes it dangerous is being told it succeeded, because
    then the user deletes the installation it came from.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    source = tmp_path / "install" / "cookies"
    source.mkdir(parents=True)
    (source / "one.txt").write_bytes(b"1" * 10)
    (source / "two.txt").write_bytes(b"2" * 10)
    destination = state_root / "cookies"

    def losing_copy(src: Path, dst: Path) -> None:
        dst.mkdir(parents=True)
        (dst / "one.txt").write_bytes((Path(src) / "one.txt").read_bytes())

    monkeypatch.setattr("src.config.layout_apply._copy_tree", losing_copy)

    with pytest.raises(MigrationError):
        apply_plan(
            MigrationPlan(
                actions=(
                    PlannedAction(
                        kind=ActionKind.COPY,
                        source=source,
                        destination=destination,
                        size=20,
                    ),
                )
            )
        )


def test_an_occupied_destination_is_never_overwritten(tmp_path: Path) -> None:
    """Importing into a populated data directory must not clobber it.

    Import is offered from Settings at any time, not only on first run, so the
    destination can hold work the user did after choosing to start fresh.
    Merging would silently replace same-named files; diverting keeps both and
    puts the decision in front of them.
    """
    state_root = tmp_path / "user_data"
    existing = state_root / "templates"
    existing.mkdir(parents=True)
    (existing / "theirs.jinja").write_bytes(b"kept")
    source = tmp_path / "install" / "templates"
    source.mkdir(parents=True)
    (source / "imported.jinja").write_bytes(b"diverted")

    outcome = apply_plan(
        MigrationPlan(
            actions=(
                PlannedAction(
                    kind=ActionKind.COPY,
                    source=source,
                    destination=existing,
                    size=8,
                ),
            ),
            state_root=state_root,
        )
    )

    assert (existing / "theirs.jinja").read_bytes() == b"kept"
    assert not (existing / "imported.jinja").exists()
    diverted = state_root / "migration-conflicts" / "templates"
    assert (diverted / "imported.jinja").read_bytes() == b"diverted"
    assert outcome.diverted == (Diversion(planned=existing, actual=diverted),)


def _legacy_tree(tmp_path: Path) -> Path:
    state_root = tmp_path / "user_data"
    (state_root / "jobs").mkdir(parents=True)
    (state_root / "jobs" / "saved.torrent").write_bytes(b"j" * 5)
    return state_root


def test_a_legacy_tree_is_migrated_and_recorded(tmp_path: Path) -> None:
    """The version is written only once the work it describes has happened."""
    state_root = _legacy_tree(tmp_path)

    migrate_layout(plan_migration(state_root))

    assert (state_root / "workspace" / "jobs" / "saved.torrent").exists()
    assert read_layout_version(state_root) == CURRENT_LAYOUT_VERSION


def test_a_tree_already_current_is_left_alone(tmp_path: Path) -> None:
    """The silent path, and the one nearly every launch takes.

    The plan is built before the version is consulted, so a stale plan against
    an already-migrated tree must be refused rather than replayed.
    """
    state_root = _legacy_tree(tmp_path)
    plan = plan_migration(state_root)
    write_layout_version(state_root, CURRENT_LAYOUT_VERSION)

    migrate_layout(plan)

    assert (state_root / "jobs" / "saved.torrent").exists()
    assert not (state_root / "workspace").exists()


def test_a_tree_from_a_newer_build_is_not_touched(tmp_path: Path) -> None:
    """Migrating backwards would rearrange a layout this build cannot read."""
    state_root = _legacy_tree(tmp_path)
    plan = plan_migration(state_root)
    write_layout_version(state_root, CURRENT_LAYOUT_VERSION + 5)

    migrate_layout(plan)

    assert (state_root / "jobs" / "saved.torrent").exists()
    assert not (state_root / "workspace").exists()


def test_an_unreadable_record_stops_the_migration_before_it_starts(
    tmp_path: Path,
) -> None:
    """Not knowing the layout is a reason to do nothing, not to guess."""
    state_root = _legacy_tree(tmp_path)
    plan = plan_migration(state_root)
    (state_root / "layout.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(LayoutRecordError):
        migrate_layout(plan)

    assert (state_root / "jobs" / "saved.torrent").exists()
    assert not (state_root / "workspace").exists()
