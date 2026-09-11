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
    Finding,
    FindingKind,
    LegacyInstall,
    PlannedAction,
    plan_migration,
    recognise_legacy_install,
    render_plan,
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


def test_an_unrecognised_entry_is_reported_for_review(tmp_path: Path) -> None:
    """Left alone is not the same as left unmentioned.

    The data directory was the default working directory, so whatever a user put
    there is still there after the migration, sitting beside a layout that does
    not account for it. Reporting it is what lets them decide; the alternative is
    a tidy-looking directory with their files quietly stranded in it.
    """
    state_root = tmp_path / "user_data"
    theirs = state_root / "notes and scratch files"
    theirs.mkdir(parents=True)
    (theirs / "thoughts.txt").write_text("keep me", encoding="utf-8")

    plan = plan_migration(state_root)

    assert plan.findings == (
        Finding(kind=FindingKind.UNRECOGNISED_ENTRY, path=theirs, size=7),
    )


def test_the_layout_itself_is_not_reported_as_a_leftover(tmp_path: Path) -> None:
    """A report that names every directory is one nobody reads.

    The point of the leftover list is that it is short and every line on it
    wants a decision. Both the layout's own directories and the entries that
    have a planned action belong off it.
    """
    state_root = tmp_path / "user_data"
    for name in ("config", "logs", "templates", "cookies", "workspace", "jobs"):
        (state_root / name).mkdir(parents=True)
    (state_root / "frameforge_indexes").mkdir()
    (state_root / "Example.Release.Name.2024_09.11.2026_10.09.39").mkdir()

    plan = plan_migration(state_root)

    assert plan.findings == ()


def test_a_configured_path_inside_the_legacy_install_is_reported(
    tmp_path: Path,
) -> None:
    """Reported and named, never silently rewritten.

    A path the user pointed at something inside their old installation keeps
    working right up until they delete that folder, which the summary tells them
    to consider doing. Guessing a new location for it would be this code
    inventing an answer; naming the setting lets them give one.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    legacy = _frozen_install(tmp_path)
    script = legacy.root / "extras" / "custom.py"
    script.parent.mkdir(parents=True)
    script.write_bytes(b"s")

    plan = plan_migration(
        state_root, legacy=legacy, configured_paths=[("example setting", script)]
    )

    assert (
        Finding(
            kind=FindingKind.PATH_INSIDE_LEGACY_INSTALL,
            path=script,
            detail="example setting",
        )
        in plan.findings
    )


def test_a_configured_path_outside_the_legacy_install_is_not_reported(
    tmp_path: Path,
) -> None:
    """Somewhere else on the disk is not the migration's business.

    A tool or working directory the user keeps elsewhere survives replacing the
    release untouched, which is the whole point of configuring one.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    legacy = _frozen_install(tmp_path)
    legacy.root.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere" / "custom.py"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_bytes(b"s")

    plan = plan_migration(
        state_root, legacy=legacy, configured_paths=[("example setting", elsewhere)]
    )

    assert plan.findings == ()


def test_run_folders_in_a_configured_working_directory_are_reported(
    tmp_path: Path,
) -> None:
    """Reported with their size, and not swept.

    A configured working directory is somewhere the user chose, often on another
    disk and often large. Reclaiming space there is worth telling them about;
    deciding to is theirs, and a sweep that reached outside the data directory
    would be the cleanup bug this work exists to fix, at a larger scale.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    working_dir = tmp_path / "media work"
    run_folder = working_dir / "Example.Release.Name.2024_09.11.2026_10.09.39"
    run_folder.mkdir(parents=True)
    (run_folder / "screenshot.png").write_bytes(b"y" * 4)

    plan = plan_migration(state_root, working_dirs=[working_dir])

    assert plan.actions == ()
    assert (
        Finding(kind=FindingKind.RUN_FOLDER_IN_WORKING_DIR, path=run_folder, size=4)
        in plan.findings
    )


def test_a_working_directory_that_is_the_data_directory_is_not_reported_twice(
    tmp_path: Path,
) -> None:
    """The old default working directory was the data directory itself.

    So the common case is a configured working directory that is exactly the
    tree already being relocated. Its run folders have planned moves; listing
    them as leftovers as well would tell the user to review files the migration
    has already dealt with.
    """
    state_root = tmp_path / "user_data"
    run_folder = state_root / "Example.Release.Name.2024_09.11.2026_10.09.39"
    run_folder.mkdir(parents=True)

    plan = plan_migration(state_root, working_dirs=[state_root])

    assert [action.source for action in plan.actions] == [run_folder]
    assert plan.findings == ()


def test_a_dependency_under_the_legacy_tools_directory_is_rewritten(
    tmp_path: Path,
) -> None:
    """This is the one configured path with an answer worth guessing.

    The old tools directory is itself being copied to a known new location, so
    the setting's replacement is derivable rather than invented. Leaving it
    would point the setting at a folder the user is being told they may delete,
    and rediscovery would find nothing: the next run would fail on a missing
    dependency that is sitting right there under its new name.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    legacy = _frozen_install(tmp_path)
    tool = legacy.state / "apps" / "example_tool" / "example_tool.exe"
    tool.parent.mkdir(parents=True)
    tool.write_bytes(b"t")

    plan = plan_migration(
        state_root, legacy=legacy, configured_paths=[("dependency: example tool", tool)]
    )

    assert (
        PlannedAction(
            kind=ActionKind.REWRITE,
            source=tool,
            destination=state_root / "tools" / "example_tool" / "example_tool.exe",
            size=0,
            detail="dependency: example tool",
        )
        in plan.actions
    )
    assert [finding.kind for finding in plan.findings] == []


def test_a_plan_renders_as_text_grouped_by_what_it_does(tmp_path: Path) -> None:
    """The dry run has to be readable by the person deciding whether to run it.

    Grouped by what happens, because "copied from an installation you keep" and
    "moved within your own data" carry different risk, and sized, because the
    cost of a step is most of what someone wants to know before agreeing to it.
    """
    state_root = tmp_path / "user_data"
    (state_root / "jobs").mkdir(parents=True)
    (state_root / "jobs" / "saved").write_bytes(b"j" * 2048)
    theirs = state_root / "notes"
    theirs.mkdir()

    rendered = render_plan(plan_migration(state_root))

    assert "Move within the data directory" in rendered
    assert str(state_root / "jobs") in rendered
    assert str(state_root / "workspace" / "jobs") in rendered
    assert "2.00 KB" in rendered
    assert "Review these yourself" in rendered
    assert str(theirs) in rendered


def test_rendering_a_plan_with_nothing_to_do_says_so(tmp_path: Path) -> None:
    """Silence would read as a failure rather than as a clean result."""
    state_root = tmp_path / "user_data"
    state_root.mkdir()

    assert "Nothing to migrate" in render_plan(plan_migration(state_root))


def test_a_repointed_setting_is_rendered_without_a_size(tmp_path: Path) -> None:
    """A rewrite moves no bytes, so a size on it is noise that invites doubt.

    Rendering one anyway produced a heading reading "Repoint these settings
    (0.00 B)", which says nothing except that something might be wrong.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    legacy = _frozen_install(tmp_path)
    tool = legacy.state / "apps" / "example_tool" / "example_tool.exe"
    tool.parent.mkdir(parents=True)
    tool.write_bytes(b"t")

    rendered = render_plan(
        plan_migration(
            state_root, legacy=legacy, configured_paths=[("a setting", tool)]
        )
    )

    assert "Repoint these settings:" in rendered
    assert "0.00 B" not in rendered


def test_a_release_installation_is_recognised_by_its_state_tree(tmp_path: Path) -> None:
    """A folder is a previous installation if it has configuration in it.

    Not by its name, which the user chose when they extracted the release, and
    not by the executable, which tells us nothing about whether there is
    anything worth importing. Configuration is the thing being looked for, so
    configuration is what identifies it.
    """
    install = tmp_path / "some folder the user named"
    state = install / "bundle" / "runtime"
    (state / "config" / "user").mkdir(parents=True)

    found = recognise_legacy_install(install)

    assert found == LegacyInstall(
        root=install, state=state, plugins=install / "plugins"
    )


def test_a_source_checkout_is_recognised_too(tmp_path: Path) -> None:
    """The other legacy layout, and the one a developer upgrades from.

    `runtime/` and `plugins/` sit side by side rather than nested in a bundle.
    """
    install = tmp_path / "checkout"
    state = install / "runtime"
    (state / "config" / "program").mkdir(parents=True)
    (state / "config" / "program" / "conf.toml").write_text("", encoding="utf-8")

    found = recognise_legacy_install(install)

    assert found == LegacyInstall(
        root=install, state=state, plugins=install / "plugins"
    )


def test_a_folder_with_no_configuration_is_not_an_installation(tmp_path: Path) -> None:
    """Refusing is the useful answer when there is nothing to import.

    An empty folder, or one holding an unpacked release nobody has run yet, has
    nothing worth migrating, and accepting it would produce a migration that
    reports success having moved nothing.
    """
    install = tmp_path / "empty"
    (install / "bundle" / "runtime").mkdir(parents=True)

    assert recognise_legacy_install(install) is None


def test_an_installation_nested_below_the_chosen_folder_is_found(
    tmp_path: Path,
) -> None:
    """People pick the folder they extracted into, not the one they extracted.

    A picker that refused the obvious choice would send the user back to try
    again with no idea what was wrong, so a choice is probed downwards before it
    is rejected.
    """
    chosen = tmp_path / "downloads"
    install = chosen / "extracted release"
    (install / "bundle" / "runtime" / "config" / "user").mkdir(parents=True)

    found = recognise_legacy_install(chosen)

    assert found is not None
    assert found.root == install


def test_the_search_below_a_chosen_folder_is_bounded(tmp_path: Path) -> None:
    """Two levels, because a user's home directory is a plausible choice.

    Walking a whole drive to find a configuration file is not a folder picker,
    it is a filesystem scan the user did not ask for and cannot interrupt.
    """
    chosen = tmp_path / "downloads"
    buried = chosen / "one" / "two" / "three"
    (buried / "bundle" / "runtime" / "config" / "user").mkdir(parents=True)

    assert recognise_legacy_install(chosen) is None
