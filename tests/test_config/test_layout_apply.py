"""Carrying out a plan, which is the only code here that can lose data.

Every test builds a synthesised tree under `tmp_path`. The first test is not
about behaviour at all: it is the guarantee the rest of the module is written
under, and it is checked first because it is the one that cannot be restored by
fixing a bug later.
"""

import ast
import json
from pathlib import Path

import pytest
import tomllib

from src.config.layout_apply import (
    Diversion,
    MigrationError,
    apply_plan,
    import_legacy,
    migrate_layout,
    startup_migration,
)
from src.config.layout_migration import (
    ActionKind,
    LegacyInstall,
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
from src.config.paths import AppPaths
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


def test_a_migration_records_what_it_did(tmp_path: Path) -> None:
    """The trail is what a user, or someone helping them, reads afterwards.

    Which entries moved, which were copied and from where, and which collided.
    Without it the only account of a migration is a dialog nobody kept, and the
    question "where did my templates go" has no answer.
    """
    state_root = _legacy_tree(tmp_path)
    legacy_root = tmp_path / "install"
    legacy = LegacyInstall(
        root=legacy_root,
        state=legacy_root / "bundle" / "runtime",
        plugins=legacy_root / "plugins",
    )
    (legacy.state / "cookies").mkdir(parents=True)
    (legacy.state / "cookies" / "a.txt").write_bytes(b"c")

    migrate_layout(plan_migration(state_root, legacy=legacy))

    document = json.loads((state_root / "layout.json").read_text(encoding="utf-8"))
    assert document["legacy_source"] == str(legacy_root)
    assert document["migrated_at"]
    assert {
        "source": str(state_root / "jobs"),
        "destination": str(state_root / "workspace" / "jobs"),
    } in document["moved"]
    assert {
        "source": str(legacy.state / "cookies"),
        "destination": str(state_root / "cookies"),
    } in document["copied"]


def test_a_migration_with_no_previous_installation_records_no_source(
    tmp_path: Path,
) -> None:
    """Starting fresh still relocates what accumulated at the root."""
    state_root = _legacy_tree(tmp_path)

    migrate_layout(plan_migration(state_root))

    document = json.loads((state_root / "layout.json").read_text(encoding="utf-8"))
    assert document["legacy_source"] is None
    assert document["copied"] == []


def _profile(state_root: Path, name: str, body: str) -> Path:
    profiles = state_root / "config" / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    path = profiles / f"{name}.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_a_rewrite_repoints_the_setting_in_the_migrated_profile(
    tmp_path: Path,
) -> None:
    """A planned rewrite has to reach the document, or it changed nothing.

    Applied to the copy in the data directory, never to the installation it came
    from: the original keeps its original values, so the user reviewing that
    folder later still sees what it said.
    """
    state_root = tmp_path / "user_data"
    profile = _profile(
        state_root,
        "main",
        "# keep this comment\n"
        "[general]\n"
        'working_dir = "C:/old/place"\n'
        "\n"
        "[dependencies]\n"
        'ffmpeg = "C:/old/tools/ffmpeg.exe"\n'
        'mkbrr = "D:/elsewhere/mkbrr.exe"\n',
    )

    apply_plan(
        MigrationPlan(
            actions=(
                PlannedAction(
                    kind=ActionKind.REWRITE,
                    source=Path("C:/old/place"),
                    destination=state_root / "workspace",
                    size=0,
                    detail="working directory",
                ),
                PlannedAction(
                    kind=ActionKind.REWRITE,
                    source=Path("C:/old/tools/ffmpeg.exe"),
                    destination=state_root / "tools" / "ffmpeg.exe",
                    size=0,
                    detail="dependency ffmpeg",
                ),
            ),
            state_root=state_root,
        )
    )

    document = tomllib.loads(profile.read_text(encoding="utf-8"))
    assert Path(document["general"]["working_dir"]) == state_root / "workspace"
    assert (
        Path(document["dependencies"]["ffmpeg"]) == state_root / "tools" / "ffmpeg.exe"
    )


def test_a_setting_no_rewrite_names_is_left_exactly_as_it_was(tmp_path: Path) -> None:
    """Only the paths a plan names are touched, and the file keeps its shape.

    A dependency the user keeps on another disk was never moved, so changing it
    would be the migration relocating something it did not relocate. The comment
    and the ordering survive too, because this is the user's file and a
    migration has no business reformatting it.
    """
    state_root = tmp_path / "user_data"
    original = (
        '# a comment the user wrote\n[dependencies]\nmkbrr = "D:/elsewhere/mkbrr.exe"\n'
    )
    profile = _profile(state_root, "main", original)

    apply_plan(
        MigrationPlan(
            actions=(
                PlannedAction(
                    kind=ActionKind.REWRITE,
                    source=Path("C:/old/tools/ffmpeg.exe"),
                    destination=state_root / "tools" / "ffmpeg.exe",
                    size=0,
                    detail="dependency ffmpeg",
                ),
            ),
            state_root=state_root,
        )
    )

    assert profile.read_text(encoding="utf-8") == original


def test_applied_rewrites_are_reported(tmp_path: Path) -> None:
    """The summary says which settings changed, so nothing moves unannounced."""
    state_root = tmp_path / "user_data"
    _profile(state_root, "main", '[general]\nworking_dir = "C:/old/place"\n')

    outcome = apply_plan(
        MigrationPlan(
            actions=(
                PlannedAction(
                    kind=ActionKind.REWRITE,
                    source=Path("C:/old/place"),
                    destination=state_root / "workspace",
                    size=0,
                    detail="working directory",
                ),
            ),
            state_root=state_root,
        )
    )

    assert outcome.rewritten == ("main: working directory",)


def _legacy_with_cookies(tmp_path: Path) -> LegacyInstall:
    root = tmp_path / "install"
    legacy = LegacyInstall(
        root=root, state=root / "bundle" / "runtime", plugins=root / "plugins"
    )
    (legacy.state / "config" / "user").mkdir(parents=True)
    (legacy.state / "cookies").mkdir(parents=True)
    (legacy.state / "cookies" / "a.txt").write_bytes(b"c")
    return legacy


def test_startup_does_nothing_when_the_layout_is_current(tmp_path: Path) -> None:
    """The path almost every launch takes, and it must be silent and cheap.

    No discovery, no question, no plan: a data directory already at this layout
    has nothing to decide, so the user is not asked anything ever again.
    """
    state_root = _legacy_tree(tmp_path)
    write_layout_version(state_root, CURRENT_LAYOUT_VERSION)
    paths = AppPaths(state_root=state_root, asset_root=tmp_path / "assets")
    asked = []

    outcome = startup_migration(
        paths, decide=lambda found: asked.append(found), probe_root=tmp_path
    )

    assert outcome is None
    assert asked == []
    assert (state_root / "jobs").exists()


def test_startup_offers_the_installation_it_discovered(tmp_path: Path) -> None:
    """Whatever was found beside the executable is what the user is asked about.

    Handed to the decision rather than assumed, so the same code serves the
    found state, a folder the user picks instead, and starting fresh.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    legacy = _legacy_with_cookies(tmp_path)
    paths = AppPaths(state_root=state_root, asset_root=tmp_path / "assets")
    offered: list[LegacyInstall | None] = []

    def decide(found: LegacyInstall | None) -> LegacyInstall | None:
        offered.append(found)
        return found

    startup_migration(paths, decide=decide, probe_root=tmp_path)

    assert offered and offered[0] is not None
    assert offered[0].root == legacy.root


def test_startup_imports_what_the_decision_accepts(tmp_path: Path) -> None:
    state_root = _legacy_tree(tmp_path)
    legacy = _legacy_with_cookies(tmp_path)
    paths = AppPaths(state_root=state_root, asset_root=tmp_path / "assets")

    startup_migration(paths, decide=lambda found: found, probe_root=tmp_path)

    assert (state_root / "cookies" / "a.txt").read_bytes() == b"c"
    assert (state_root / "workspace" / "jobs" / "saved.torrent").exists()
    assert (legacy.state / "cookies" / "a.txt").exists()


def test_declining_the_import_still_relocates_what_is_already_there(
    tmp_path: Path,
) -> None:
    """Starting fresh is a choice about the old installation, not about this one.

    Saved jobs and run output accumulated in the data directory under the old
    layout regardless of where the application was installed, so they are
    relocated either way. Leaving them would hide a user's saved jobs behind a
    decision they made about something else.
    """
    state_root = _legacy_tree(tmp_path)
    _legacy_with_cookies(tmp_path)
    paths = AppPaths(state_root=state_root, asset_root=tmp_path / "assets")

    startup_migration(paths, decide=lambda _found: None, probe_root=tmp_path)

    assert (state_root / "workspace" / "jobs" / "saved.torrent").exists()
    assert not (state_root / "cookies").exists()


def test_a_declined_import_is_recorded_so_it_is_never_offered_again(
    tmp_path: Path,
) -> None:
    """Asked once, ever. The record is what makes that true.

    Distinguished from "no installation was found", because the two are not the
    same fact: one day a user may ask why they were never offered the import,
    and the answer has to be in the record.
    """
    state_root = _legacy_tree(tmp_path)
    _legacy_with_cookies(tmp_path)
    paths = AppPaths(state_root=state_root, asset_root=tmp_path / "assets")

    startup_migration(paths, decide=lambda _found: None, probe_root=tmp_path)

    record = json.loads((state_root / "layout.json").read_text(encoding="utf-8"))
    assert record["import_declined"] is True
    assert record["layout_version"] == CURRENT_LAYOUT_VERSION


def test_nothing_is_recorded_as_declined_when_there_was_nothing_to_decline(
    tmp_path: Path,
) -> None:
    """A genuinely fresh installation did not refuse anything."""
    state_root = _legacy_tree(tmp_path)
    paths = AppPaths(state_root=state_root, asset_root=tmp_path / "assets")

    startup_migration(paths, decide=lambda found: found, probe_root=tmp_path)

    record = json.loads((state_root / "layout.json").read_text(encoding="utf-8"))
    assert "import_declined" not in record


def _migrated(tmp_path: Path) -> AppPaths:
    """A data directory already at the current layout, as Settings would find it."""
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    write_layout_version(state_root, CURRENT_LAYOUT_VERSION)
    return AppPaths(state_root=state_root, asset_root=tmp_path / "assets")


def test_importing_later_copies_the_state_in(tmp_path: Path) -> None:
    """Offered from Settings at any time, so it cannot depend on the version gate.

    `startup_migration` refuses an already-current tree, which is right for a
    hop and wrong for an import: routed through it, the Settings action would
    silently do nothing.
    """
    paths = _migrated(tmp_path)
    legacy = _legacy_with_cookies(tmp_path)

    import_legacy(paths, legacy)

    assert (paths.state_root / "cookies" / "a.txt").read_bytes() == b"c"


def test_importing_later_leaves_the_layout_version_alone(tmp_path: Path) -> None:
    """An import is not a hop, and must not claim to be one."""
    paths = _migrated(tmp_path)

    import_legacy(paths, _legacy_with_cookies(tmp_path))

    assert read_layout_version(paths.state_root) == CURRENT_LAYOUT_VERSION


def test_importing_later_is_added_to_the_trail(tmp_path: Path) -> None:
    """Where the data came from is the first question asked afterwards."""
    paths = _migrated(tmp_path)
    legacy = _legacy_with_cookies(tmp_path)

    import_legacy(paths, legacy)

    document = json.loads(
        (paths.state_root / "layout.json").read_text(encoding="utf-8")
    )
    assert document["imports"][0]["legacy_source"] == str(legacy.root)
    assert document["imports"][0]["copied"]


def test_importing_over_existing_work_diverts_rather_than_replacing_it(
    tmp_path: Path,
) -> None:
    """The case the whole diversion path exists for, reached the way a user does.

    Someone starts fresh, works for a while, then imports their old installation.
    Whatever they produced in the meantime stays exactly where it is, and the
    incoming copy goes somewhere they can look at it.
    """
    paths = _migrated(tmp_path)
    theirs = paths.state_root / "cookies" / "mine.txt"
    theirs.parent.mkdir(parents=True)
    theirs.write_bytes(b"kept")
    legacy = _legacy_with_cookies(tmp_path)

    outcome = import_legacy(paths, legacy)

    assert theirs.read_bytes() == b"kept"
    assert not (paths.state_root / "cookies" / "a.txt").exists()
    diverted = paths.state_root / "migration-conflicts" / "cookies" / "a.txt"
    assert diverted.read_bytes() == b"c"
    assert [one.planned for one in outcome.diverted] == [paths.state_root / "cookies"]
