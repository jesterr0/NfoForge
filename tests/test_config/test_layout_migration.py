"""What the layout migration would do, before it is able to do anything.

Every test here builds a synthesised tree under `tmp_path` and asks for a plan.
Nothing in this module may write, move or delete: the point of planning as a
separate step is that it can be run against a real installation and shown to
someone before any of it happens.
"""

from pathlib import Path

import pytest

from src.config.layout_migration import (
    ActionKind,
    LegacyInstall,
    PlannedAction,
    plan_migration,
)


def _frozen_install(tmp_path: Path) -> LegacyInstall:
    """A pre-migration installation as a release lays one out.

    State lives under `bundle/runtime`, but the plugin directory sits beside the
    executable, a level above it. The two legacy layouts differ in exactly that
    way -- a source tree has `runtime/` and `plugins/` as siblings -- which is
    why planning is handed the resolved locations rather than deriving them.
    """
    root = tmp_path / "install"
    return LegacyInstall(
        root=root, state=root / "bundle" / "runtime", plugins=root / "plugins"
    )


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


def test_a_legacy_cookie_store_is_planned_as_a_copy(tmp_path: Path) -> None:
    """Anything from outside the data directory is copied, never moved.

    The source is an installation the user still has, and which they are told to
    review before deleting. A migration that emptied it would take that choice
    away, and would have nothing to fall back to if the import went wrong.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    legacy = _frozen_install(tmp_path)
    (legacy.state / "cookies").mkdir(parents=True)
    (legacy.state / "cookies" / "tracker.txt").write_bytes(b"c" * 5)

    plan = plan_migration(state_root, legacy=legacy)

    assert (
        PlannedAction(
            kind=ActionKind.COPY,
            source=legacy.state / "cookies",
            destination=state_root / "cookies",
            size=5,
        )
        in plan.actions
    )


@pytest.mark.parametrize(
    ("source_parts", "destination_parts"),
    [
        (("templates",), ("templates",)),
        (("config", "plugins"), ("config", "plugins")),
        (("config", "user"), ("config", "profiles")),
        (("apps",), ("tools",)),
    ],
)
def test_legacy_state_directories_map_to_their_new_homes(
    tmp_path: Path, source_parts: tuple[str, ...], destination_parts: tuple[str, ...]
) -> None:
    """Two of these are renames, and both have to be deliberate.

    `config/user` becomes `config/profiles` because the new layout says what the
    directory holds, and `apps` becomes `tools`. Copying a directory wholesale
    also carries what is nested inside it, which is how a profile's `old_configs`
    backups arrive without an entry of their own.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    legacy = _frozen_install(tmp_path)
    source = legacy.state.joinpath(*source_parts)
    source.mkdir(parents=True)
    (source / "payload").write_bytes(b"p" * 3)

    plan = plan_migration(state_root, legacy=legacy)

    assert (
        PlannedAction(
            kind=ActionKind.COPY,
            source=source,
            destination=state_root.joinpath(*destination_parts),
            size=3,
        )
        in plan.actions
    )


def test_legacy_plugins_are_planned_from_beside_the_executable(tmp_path: Path) -> None:
    """The plugin directory is the one thing not under the legacy state root.

    It sat beside the executable, which is also why it cannot be found by
    walking the state tree, and why `LegacyInstall` carries its location.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    legacy = _frozen_install(tmp_path)
    (legacy.plugins / "a_plugin").mkdir(parents=True)
    (legacy.plugins / "a_plugin" / "plugin.py").write_bytes(b"q" * 6)

    plan = plan_migration(state_root, legacy=legacy)

    assert (
        PlannedAction(
            kind=ActionKind.COPY,
            source=legacy.plugins,
            destination=state_root / "plugins",
            size=6,
        )
        in plan.actions
    )


def test_the_legacy_program_configuration_is_planned_as_a_file(tmp_path: Path) -> None:
    """Program preferences are one file, and they change name on the way.

    `config/program/conf.toml` becomes `config/program.toml`: the old nesting
    existed to give one file a directory of its own. It is the only entry that
    is not a directory, which is why size cannot assume one.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    legacy = _frozen_install(tmp_path)
    conf = legacy.state / "config" / "program" / "conf.toml"
    conf.parent.mkdir(parents=True)
    conf.write_bytes(b"k" * 9)

    plan = plan_migration(state_root, legacy=legacy)

    assert (
        PlannedAction(
            kind=ActionKind.COPY,
            source=conf,
            destination=state_root / "config" / "program.toml",
            size=9,
        )
        in plan.actions
    )
