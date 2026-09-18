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
    CopyPolicy,
    Finding,
    FindingKind,
    LegacyInstall,
    PlannedAction,
    missing_active_profile,
    plan_migration,
    read_legacy_settings,
    recognise_legacy_install,
    render_plan,
)
from src.config.paths import AppPaths


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


def test_a_run_folder_at_the_root_is_planned_into_the_processing_folder(
    tmp_path: Path,
) -> None:
    """Run output landed at the root too, for the same reason saved jobs did.

    The name is the tell: `generate_unique_date_name` stamps a truncated release
    name with a date and time, so a folder carrying that suffix is one this
    application created. Matching on shape is what lets the plan leave anything
    it does not recognise alone.

    It lands under `processing/` rather than loose in the workspace, because
    that is what a run folder is -- the old equivalent of what now goes there --
    and because clean up empties `processing/` and nothing else. Loose in the
    workspace it would be stranded: reclaimable before the migration and
    unreachable after it.
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
            destination=state_root / "workspace" / "processing" / run_folder.name,
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


def test_the_index_cache_is_planned_into_the_workspace(tmp_path: Path) -> None:
    """The cache is relocated rather than discarded, and into the workspace.

    A rename costs the same as a delete on one volume, so deleting it would only
    buy the user a re-index.

    It lands in the workspace because that is where the code looks for it:
    `FrameForgeIndexCache` resolves its cache as `<working directory>` plus its
    own name, and the workspace is the old working directory relocated. Putting
    it anywhere else leaves a cache nothing reads, which is the same outcome as
    deleting it with extra steps.
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
            destination=state_root / "workspace" / "frameforge_indexes",
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


def _write_plugin(directory: Path, plugin_id: str) -> Path:
    """A plugin directory with a manifest the loader would accept."""
    directory.mkdir(parents=True)
    (directory / "nfoforge-plugin.toml").write_text(
        f'schema_version = 1\nid = "{plugin_id}"\nmodule = "whatever"\n',
        encoding="utf-8",
    )
    return directory


def test_legacy_plugins_are_planned_one_directory_at_a_time(tmp_path: Path) -> None:
    """The plugin directory is the one thing not under the legacy state root.

    It sat beside the executable, which is also why it cannot be found by
    walking the state tree, and why `LegacyInstall` carries its location.

    Planned per plugin rather than as one directory, because which plugins are
    imported is a decision the next test depends on being able to make.
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
            source=legacy.plugins / "a_plugin",
            destination=state_root / "plugins" / "a_plugin",
            size=6,
            copy_policy=CopyPolicy.PLUGIN,
        )
        in plan.actions
    )


def test_a_plugin_plan_counts_only_files_the_import_will_copy(tmp_path: Path) -> None:
    """The size shown before an import must describe the filtered tree.

    Repositories are valid plugin roots, but their environments, VCS data,
    caches and generated build output are neither plugin code nor user data.
    Tests, documentation and arbitrary resources remain because a plugin can
    read any of them at runtime and the manifest has no resource allowlist.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    legacy = _frozen_install(tmp_path)
    plugin = _write_plugin(legacy.plugins / "repository", "their.plugin")

    def write(relative: str) -> Path:
        path = plugin / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        return path

    kept = [
        plugin / "nfoforge-plugin.toml",
        write("plugin_package/__init__.py"),
        write("plugin_package/native.pyd"),
        write("plugin_package/build/runtime.json"),
        write("tests/test_plugin.py"),
        write("docs/usage.md"),
        write("scripts/helper.py"),
        write("manual_tools/tool.bin"),
    ]
    for directory in (
        ".cache",
        ".git",
        ".hg",
        ".hypothesis",
        ".mypy_cache",
        ".nox",
        ".pyright",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "__pypackages__",
        "node_modules",
        "venv",
        "build",
        "dist",
        "htmlcov",
    ):
        write(f"{directory}/discarded.bin")
    write("named-anything/pyvenv.cfg")
    write("named-anything/lib/discarded.bin")
    for filename in (
        ".coverage",
        ".coverage.worker",
        ".DS_Store",
        "desktop.ini",
        "Thumbs.db",
        "stale.pyc",
        "stale.pyo",
    ):
        write(filename)

    plan = plan_migration(state_root, legacy=legacy)
    action = next(one for one in plan.actions if one.source == plugin)

    assert action.copy_policy is CopyPolicy.PLUGIN
    assert action.size == sum(path.stat().st_size for path in kept)


def test_a_shipped_example_plugin_is_not_imported(tmp_path: Path) -> None:
    """Importing one would break plugin loading on every subsequent start.

    The examples used to live in the user's plugin directory and now ship in the
    release, so a legacy directory holds a copy of each. Import them and both
    copies get scanned, the second registration is rejected as a duplicate ID,
    and the user gets load failures for plugins they never installed.

    Matched on the manifest ID rather than the directory name, because the
    directory is the user's to rename and the ID is what collides.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    legacy = _frozen_install(tmp_path)
    shipped = tmp_path / "assets" / "plugin_examples"
    _write_plugin(shipped / "an_example", "example.one")
    _write_plugin(legacy.plugins / "renamed_by_the_user", "example.one")
    _write_plugin(legacy.plugins / "their_own_plugin", "something.else")

    plan = plan_migration(state_root, legacy=legacy, shipped_plugins=shipped)

    copied = [
        action.source.name
        for action in plan.actions
        if action.kind is ActionKind.COPY and action.source.parent == legacy.plugins
    ]
    assert copied == ["their_own_plugin"]


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
        state_root,
        legacy=legacy,
        configured_paths=[("main", "example setting", script)],
    )

    assert (
        Finding(
            kind=FindingKind.PATH_INSIDE_LEGACY_INSTALL,
            path=script,
            detail="main: example setting",
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
        state_root,
        legacy=legacy,
        configured_paths=[("main", "example setting", elsewhere)],
    )

    assert plan.findings == ()


def test_a_working_directory_inside_the_legacy_install_is_reported(
    tmp_path: Path,
) -> None:
    """The summary invites deleting the old installation. Jobs may be in it.

    A working directory the user pointed inside their installation holds their
    saved jobs, and nothing imports it: it is not part of the layout being
    copied. Unreported, the setting survives the migration still naming a folder
    the user is being told they can now remove.

    Reported rather than rewritten, like any other path into the old
    installation. Where the user wants their jobs kept is not derivable, and
    moving them somewhere chosen here would be the migration deciding that.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    legacy = _frozen_install(tmp_path)
    working_dir = legacy.root / "work"
    working_dir.mkdir(parents=True)

    plan = plan_migration(
        state_root,
        legacy=legacy,
        working_dirs=[("portable: working directory", working_dir)],
    )

    assert (
        Finding(
            kind=FindingKind.PATH_INSIDE_LEGACY_INSTALL,
            path=working_dir,
            detail="portable: working directory",
        )
        in plan.findings
    )


def test_a_working_directory_in_the_legacy_install_is_not_reported_twice(
    tmp_path: Path,
) -> None:
    """Its run folders are not also offered up as space to reclaim.

    Both statements are true and they pull against each other: one says there is
    space to be had here, the other says this folder is about to stop existing.
    The second is the one that matters, so it is the only one made.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    legacy = _frozen_install(tmp_path)
    working_dir = legacy.root / "work"
    run_folder = working_dir / "Example.Release.Name.2024_09.11.2026_10.09.39"
    run_folder.mkdir(parents=True)
    (run_folder / "screenshot.png").write_bytes(b"y" * 4)

    plan = plan_migration(
        state_root,
        legacy=legacy,
        working_dirs=[("portable: working directory", working_dir)],
    )

    assert [finding.kind for finding in plan.findings] == [
        FindingKind.PATH_INSIDE_LEGACY_INSTALL
    ]


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

    plan = plan_migration(
        state_root, working_dirs=[("main: working directory", working_dir)]
    )

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

    plan = plan_migration(
        state_root, working_dirs=[("main: working directory", state_root)]
    )

    moved = [action.source for action in plan.actions if action.kind is ActionKind.MOVE]
    assert moved == [run_folder]
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
        state_root,
        legacy=legacy,
        configured_paths=[("main", "dependency example_tool", tool)],
    )

    assert (
        PlannedAction(
            kind=ActionKind.REWRITE,
            source=tool,
            destination=state_root / "tools" / "example_tool" / "example_tool.exe",
            size=0,
            detail="dependency example_tool",
        )
        in plan.actions
    )
    assert [finding.kind for finding in plan.findings] == []


def test_profiles_sharing_a_dependency_yield_one_rewrite_named_for_the_setting(
    tmp_path: Path,
) -> None:
    """A rewrite is about a value, not about the profile it was spotted in.

    Applying one walks every profile and repoints any document holding that
    value, so a profile name on the action is wrong twice over: it claims the
    change belongs to one profile when it belongs to all of them, and the
    report then prefixes the profile actually written, naming a different one
    beside it.

    Naming the setting alone also collapses what is really one operation. Two
    profiles pointing at the same tool produced two identical actions that
    differed only in a label neither of them owned.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    legacy = _frozen_install(tmp_path)
    tool = legacy.state / "apps" / "example_tool" / "example_tool.exe"
    tool.parent.mkdir(parents=True)
    tool.write_bytes(b"t")

    plan = plan_migration(
        state_root,
        legacy=legacy,
        configured_paths=[
            ("alpha", "dependency example_tool", tool),
            ("beta", "dependency example_tool", tool),
        ],
    )

    assert [action for action in plan.actions if action.kind is ActionKind.REWRITE] == [
        PlannedAction(
            kind=ActionKind.REWRITE,
            source=tool,
            destination=state_root / "tools" / "example_tool" / "example_tool.exe",
            size=0,
            detail="dependency example_tool",
        )
    ]


def test_a_plan_renders_as_text_grouped_by_what_it_does(tmp_path: Path) -> None:
    """The dry run has to be readable by the person deciding whether to run it.

    Grouped by what happens, because "copied from an installation you keep" and
    "moved within your own data" carry different risk, and sized, because the
    cost of a step is most of what someone wants to know before agreeing to it.
    """
    state_root = tmp_path / "user_data"
    (state_root / "jobs").mkdir(parents=True)
    (state_root / "jobs" / "saved").write_bytes(b"j" * 2048)

    rendered = render_plan(plan_migration(state_root))

    assert "Move within the data directory" in rendered
    assert str(state_root / "jobs") in rendered
    assert str(state_root / "workspace" / "jobs") in rendered
    assert "2.00 KB" in rendered


def test_findings_are_grouped_by_what_they_ask_of_the_user(tmp_path: Path) -> None:
    """One heading per kind, because the three kinds want different things.

    A leftover folder asks to be looked at, run output asks whether the space is
    wanted back, and a setting pointing into the old installation is a warning
    about deleting it. Under a single heading the reader has to work out which
    line is which, and the one that carries a consequence reads like the other
    two.
    """
    state_root = tmp_path / "user_data"
    theirs = state_root / "notes"
    theirs.mkdir(parents=True)
    legacy = _frozen_install(tmp_path)
    script = legacy.root / "extras" / "custom.py"
    script.parent.mkdir(parents=True)
    script.write_bytes(b"s")
    working_dir = tmp_path / "media work"
    run_folder = working_dir / "Example.Release.Name.2024_09.11.2026_10.09.39"
    run_folder.mkdir(parents=True)
    (run_folder / "screenshot.png").write_bytes(b"y" * 4)

    rendered = render_plan(
        plan_migration(
            state_root,
            legacy=legacy,
            working_dirs=[("main: working directory", working_dir)],
            configured_paths=[("main", "example setting", script)],
        )
    )

    headings = [line for line in rendered.splitlines() if not line.startswith(" ")]

    assert "Left in place, not part of the layout:" in headings
    assert "Run output you can delete (4.00 B):" in headings
    assert "Settings pointing into the previous installation:" in headings
    assert str(theirs) in rendered
    assert str(run_folder) in rendered
    assert str(script) in rendered


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
            state_root,
            legacy=legacy,
            configured_paths=[("main", "a setting", tool)],
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


def test_a_working_directory_that_is_the_data_directory_is_repointed(
    tmp_path: Path,
) -> None:
    """Otherwise the migration hides every saved job it just moved.

    Saved jobs are found at `<working directory>/jobs`, and the old default
    working directory was the root of the data directory. Move `jobs/` into the
    workspace and leave the setting alone, and the application looks in a
    directory that no longer exists: the jobs are intact and invisible, which is
    indistinguishable from having lost them.

    Derivable rather than guessed, which is what makes repointing it right: the
    directory it named has not gone away, it has become the workspace inside it.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()

    plan = plan_migration(
        state_root, working_dirs=[("main: working directory", state_root)]
    )

    assert (
        PlannedAction(
            kind=ActionKind.REWRITE,
            source=state_root,
            destination=state_root / "workspace",
            size=0,
            detail="working directory",
        )
        in plan.actions
    )


def test_a_working_directory_elsewhere_is_left_pointing_where_it_is(
    tmp_path: Path,
) -> None:
    """A directory the migration never touched needs no correction.

    Jobs kept outside the data directory stay exactly where they were, so the
    setting is still right and changing it would be the migration moving
    someone's work for no reason.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    elsewhere = tmp_path / "media work"
    elsewhere.mkdir()

    plan = plan_migration(
        state_root, working_dirs=[("main: working directory", elsewhere)]
    )

    assert [a for a in plan.actions if a.kind is ActionKind.REWRITE] == []


def test_profiles_sharing_a_working_directory_yield_one_rewrite(
    tmp_path: Path,
) -> None:
    """Profiles commonly share one, and the setting has one correct new value."""
    state_root = tmp_path / "user_data"
    state_root.mkdir()

    plan = plan_migration(
        state_root,
        working_dirs=[
            ("alpha: working directory", state_root),
            ("beta: working directory", state_root),
        ],
    )

    assert len([a for a in plan.actions if a.kind is ActionKind.REWRITE]) == 1


def test_migration_destinations_agree_with_where_the_application_reads(
    tmp_path: Path,
) -> None:
    """The two sides name these directories independently, so they can drift.

    A migration that puts plugins, templates, cookies, tools or configuration
    somewhere the application does not read produces the worst kind of success:
    it reports having moved everything, and the user starts with nothing. Each
    pairing below has already been wrong once during this work.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    legacy = _frozen_install(tmp_path)
    for parts in (
        ("cookies",),
        ("templates",),
        ("config", "plugins"),
        ("config", "user"),
        ("apps",),
    ):
        legacy.state.joinpath(*parts).mkdir(parents=True)
    (legacy.state / "config" / "program").mkdir(parents=True, exist_ok=True)
    (legacy.state / "config" / "program" / "conf.toml").write_text("", encoding="utf-8")
    _write_plugin(legacy.plugins / "a_plugin", "theirs")

    plan = plan_migration(state_root, legacy=legacy)
    destinations = {action.destination for action in plan.actions}
    paths = AppPaths(state_root=state_root, asset_root=tmp_path / "assets")

    for expected in (
        paths.tracker_cookies,
        paths.templates,
        paths.plugin_configs,
        paths.user_configs,
        paths.program,
        paths.tools,
        paths.plugins / "a_plugin",
    ):
        assert expected in destinations, (
            f"the migration writes nothing to {expected}, which is where the "
            "application reads it from"
        )


def test_configured_paths_are_read_from_a_previous_installation(
    tmp_path: Path,
) -> None:
    """Planning needs these before any configuration has been loaded.

    The rewrites a migration plans come from settings, and settings live in the
    installation being migrated from. Reading them through the configuration
    layer is not available yet: that layer reads from the data directory, which
    is the thing the migration is still assembling.

    Boolean flags share the dependencies section with paths, so only the
    path-valued settings are returned -- a flag handed on as a path would be
    reported as a setting pointing somewhere impossible.
    """
    legacy = _frozen_install(tmp_path)
    profiles = legacy.state / "config" / "user"
    profiles.mkdir(parents=True)
    (profiles / "main.toml").write_text(
        "[general]\n"
        'working_dir = "C:/user data"\n'
        "[dependencies]\n"
        'ffmpeg = "C:/tools/ffmpeg.exe"\n'
        'frame_forge = ""\n'
        "enable_mkbrr = true\n",
        encoding="utf-8",
    )

    settings = read_legacy_settings(legacy)

    assert settings.working_dirs == (("main: working directory", Path("C:/user data")),)
    assert settings.configured_paths == (
        ("main", "dependency ffmpeg", Path("C:/tools/ffmpeg.exe")),
    )


def test_settings_are_read_from_every_profile(tmp_path: Path) -> None:
    """Profiles are independent, and each can point somewhere of its own.

    A shared working directory is reported once, because the plan that follows
    needs the set of directories rather than one entry per profile.
    """
    legacy = _frozen_install(tmp_path)
    profiles = legacy.state / "config" / "user"
    profiles.mkdir(parents=True)
    for name in ("alpha", "beta"):
        (profiles / f"{name}.toml").write_text(
            f'[general]\nworking_dir = "C:/shared"\n[dependencies]\nmkbrr = "C:/{name}.exe"\n',
            encoding="utf-8",
        )

    settings = read_legacy_settings(legacy)

    assert settings.working_dirs == (
        ("alpha, beta: working directory", Path("C:/shared")),
    )
    assert sorted(
        (profile, setting) for profile, setting, _ in settings.configured_paths
    ) == [
        ("alpha", "dependency mkbrr"),
        ("beta", "dependency mkbrr"),
    ]


def test_an_unreadable_profile_does_not_stop_the_others(tmp_path: Path) -> None:
    """One damaged document must not cost the user every other profile's plan."""
    legacy = _frozen_install(tmp_path)
    profiles = legacy.state / "config" / "user"
    profiles.mkdir(parents=True)
    (profiles / "broken.toml").write_text("[general\nnot valid", encoding="utf-8")
    (profiles / "fine.toml").write_text(
        '[general]\nworking_dir = "C:/fine"\n', encoding="utf-8"
    )

    settings = read_legacy_settings(legacy)

    assert settings.working_dirs == (("fine: working directory", Path("C:/fine")),)


def _program_config(paths: AppPaths, active: str) -> None:
    paths.program.parent.mkdir(parents=True, exist_ok=True)
    paths.program.write_text(f'current_config = "{active}"\n', encoding="utf-8")


def _profile(paths: AppPaths, name: str) -> None:
    paths.user_configs.mkdir(parents=True, exist_ok=True)
    (paths.user_configs / f"{name}.toml").write_text("", encoding="utf-8")


def test_an_active_profile_that_did_not_arrive_is_named(tmp_path: Path) -> None:
    """Otherwise the application starts on a profile it invented, saying nothing.

    A program configuration names the profile that was in use. If that profile is
    not among the ones imported, NfoForge generates a fresh one under the same
    name and starts with default settings -- plugins off, trackers unconfigured.
    The migration reports complete success throughout, so the user sees settings
    that look wrong with nothing anywhere explaining why.

    Reachable without anyone doing something unusual: import into a data folder
    that already holds profiles, and the incoming ones divert to the conflicts
    folder while the program configuration naming them lands.
    """
    paths = AppPaths(state_root=tmp_path / "state", asset_root=tmp_path / "assets")
    _program_config(paths, "the one they were using")
    _profile(paths, "a different one")

    assert missing_active_profile(paths) == "the one they were using"


def test_nothing_is_reported_when_the_active_profile_is_there(tmp_path: Path) -> None:
    paths = AppPaths(state_root=tmp_path / "state", asset_root=tmp_path / "assets")
    _program_config(paths, "theirs")
    _profile(paths, "theirs")

    assert missing_active_profile(paths) == ""


def test_nothing_is_reported_without_a_program_configuration(tmp_path: Path) -> None:
    """A fresh start has no program configuration and no profile to miss."""
    paths = AppPaths(state_root=tmp_path / "state", asset_root=tmp_path / "assets")

    assert missing_active_profile(paths) == ""


def test_an_unreadable_program_configuration_reports_nothing(tmp_path: Path) -> None:
    """It is already its own error, handled elsewhere with its own recovery.

    Reporting a second, vaguer complaint about it here would send the user
    looking for a missing profile when the actual problem is the file naming it.
    """
    paths = AppPaths(state_root=tmp_path / "state", asset_root=tmp_path / "assets")
    paths.program.parent.mkdir(parents=True, exist_ok=True)
    paths.program.write_text('current_config = "unterminated', encoding="utf-8")

    assert missing_active_profile(paths) == ""


def test_a_dependency_naming_something_that_is_not_there_is_reported(
    tmp_path: Path,
) -> None:
    """The one case the folder-relative checks cannot see.

    Both existing checks ask where a path sits relative to the installation
    being imported from. A setting naming a *different* installation -- one
    renamed before upgrading, or moved, or simply never picked -- is inside
    neither, so it is repointed by nothing and reported by nothing, and survives
    the migration still naming a file that is not there.

    Renaming the old folder before extracting the new release is enough to reach
    it, which is a reasonable thing for someone to do unprompted.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    legacy = _frozen_install(tmp_path)
    legacy.root.mkdir(parents=True)
    stale = tmp_path / "renamed_install" / "bundle" / "runtime" / "apps" / "tool.exe"

    plan = plan_migration(
        state_root,
        legacy=legacy,
        configured_paths=[("main", "dependency example_tool", stale)],
    )

    assert (
        Finding(
            kind=FindingKind.MISSING_CONFIGURED_PATH,
            path=stale,
            detail="main: dependency example_tool",
        )
        in plan.findings
    )


def test_a_dependency_that_resolves_outside_the_installation_stays_quiet(
    tmp_path: Path,
) -> None:
    """A tool kept elsewhere on purpose is not a problem to report.

    The check is whether the path names something, not where it names it.
    Reporting every path outside the installation would bury the one that is
    actually broken under the ones that are fine.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    legacy = _frozen_install(tmp_path)
    legacy.root.mkdir(parents=True)
    elsewhere = tmp_path / "tools" / "tool.exe"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_bytes(b"t")

    plan = plan_migration(
        state_root,
        legacy=legacy,
        configured_paths=[("main", "dependency example_tool", elsewhere)],
    )

    assert plan.findings == ()


def test_a_working_directory_is_returned_as_the_document_wrote_it(
    tmp_path: Path,
) -> None:
    """Read back, not resolved. The value is shown to the user.

    Resolving anchors anything that is not already absolute to wherever the
    process happened to start, so a relative setting would be reported as a path
    that is neither in the user's file nor on their disk. It also makes the
    result depend on the platform: a Windows path carries no drive letter
    meaning on Linux, so `C:/somewhere` resolves to the working directory with
    `C:/somewhere` stuck on the end.

    Comparison still normalises both sides, so nothing about matching depends on
    the stored form.
    """
    legacy = _frozen_install(tmp_path)
    profiles = legacy.state / "config" / "user"
    profiles.mkdir(parents=True)
    (profiles / "main.toml").write_text(
        '[general]\nworking_dir = "somewhere/relative"\n', encoding="utf-8"
    )

    settings = read_legacy_settings(legacy)

    assert settings.working_dirs == (
        ("main: working directory", Path("somewhere/relative")),
    )
