"""The migration as one chain, from a profile on disk to the record written.

Every other test in this area supplies its own input to one stage: a plan built
by hand, a settings tuple written out literally, a rewrite with a detail string
of the test's choosing. That is the right shape for testing a stage, and it is
why a defect living *between* two stages survived the whole suite -- the label a
rewrite carried was produced by one module and consumed by another, and no test
ever passed one to the other.

So this module supplies nothing but a directory tree, and asserts only what a
user could see afterwards: the files on disk and the record kept beside them.
"""

from pathlib import Path

import tomllib

from src.config.layout_apply import import_legacy
from src.config.layout_migration import FindingKind, LegacyInstall
from src.config.paths import AppPaths


def _install(tmp_path: Path) -> LegacyInstall:
    """A previous installation laid out as a release, with a tool and profiles.

    Two profiles sharing one dependency, because that is the shape that made the
    labelling wrong: one rewrite, applied to both documents, reported once per
    document actually changed.
    """
    root = tmp_path / "install"
    state = root / "bundle" / "runtime"
    tool = state / "apps" / "frame_forge" / "FrameForge.exe"
    tool.parent.mkdir(parents=True)
    tool.write_bytes(b"tool")

    profiles = state / "config" / "user"
    profiles.mkdir(parents=True)
    # Names the data directory, which is the pre-migration default and becomes
    # the workspace inside it.
    (profiles / "alpha.toml").write_text(
        "# a comment the user wrote\n"
        "[general]\n"
        f'working_dir = "{(tmp_path / "user_data").as_posix()}"\n'
        "\n"
        "[dependencies]\n"
        f'frame_forge = "{tool.as_posix()}"\n'
        'ffmpeg = "D:/elsewhere/ffmpeg.exe"\n'
        "enable_mkbrr = true\n",
        encoding="utf-8",
    )
    # Keeps its working directory inside the installation, which nothing imports.
    (profiles / "beta.toml").write_text(
        "[general]\n"
        f'working_dir = "{(root / "work").as_posix()}"\n'
        "\n"
        "[dependencies]\n"
        f'frame_forge = "{tool.as_posix()}"\n',
        encoding="utf-8",
    )

    program = state / "config" / "program"
    program.mkdir(parents=True)
    (program / "conf.toml").write_text('current_config = "alpha"\n', encoding="utf-8")

    return LegacyInstall(root=root, state=state, plugins=root / "plugins")


def _paths(tmp_path: Path) -> AppPaths:
    return AppPaths(state_root=tmp_path / "user_data", asset_root=tmp_path / "assets")


def test_a_shared_dependency_is_repointed_once_and_reported_per_profile(
    tmp_path: Path,
) -> None:
    """One rewrite, both documents changed, each named once.

    The label a rewrite carries is built where the setting is read and consumed
    where the document is written. Naming the profile in both places produced a
    doubled name on one profile and, beside it, a line crediting one profile's
    change to another -- in the record kept on disk, not only in a dialog.
    """
    legacy = _install(tmp_path)
    paths = _paths(tmp_path)

    run = import_legacy(paths, legacy)

    assert sorted(run.outcome.rewritten) == [
        "alpha: dependency frame_forge",
        "alpha: working directory",
        "beta: dependency frame_forge",
    ]


def test_the_repointed_dependency_resolves_to_the_tool_that_was_copied(
    tmp_path: Path,
) -> None:
    """A repointed path that names nothing is the failure being prevented.

    Asserting the string would pass just as well against a plausible path that
    happens to be wrong, which is the whole failure mode: the setting keeps
    working until the user deletes the installation it still names.
    """
    legacy = _install(tmp_path)
    paths = _paths(tmp_path)

    import_legacy(paths, legacy)

    for name in ("alpha", "beta"):
        document = tomllib.loads(
            (paths.user_configs / f"{name}.toml").read_text(encoding="utf-8")
        )
        repointed = Path(document["dependencies"]["frame_forge"])
        assert (
            repointed == paths.state_root / "tools" / "frame_forge" / "FrameForge.exe"
        )
        assert repointed.is_file()


def test_a_working_directory_naming_the_data_directory_becomes_the_workspace(
    tmp_path: Path,
) -> None:
    """Saved jobs are found under the working directory, so this one matters.

    The pre-migration default working directory was the data directory itself.
    Leave the setting naming it and the application looks at the root of a tree
    whose contents have moved into the workspace inside it.
    """
    legacy = _install(tmp_path)
    paths = _paths(tmp_path)

    import_legacy(paths, legacy)

    document = tomllib.loads(
        (paths.user_configs / "alpha.toml").read_text(encoding="utf-8")
    )
    assert Path(document["general"]["working_dir"]) == paths.state_root / "workspace"


def test_a_working_directory_inside_the_installation_is_reported_not_repointed(
    tmp_path: Path,
) -> None:
    """Nothing imports it, so the setting outlives the folder it names.

    Reported against the profile holding it, because a user told that a setting
    is wrong without being told where it lives has the harder half of the
    problem left to them.
    """
    legacy = _install(tmp_path)
    paths = _paths(tmp_path)

    run = import_legacy(paths, legacy)

    assert [
        (finding.detail, finding.path)
        for finding in run.plan.findings
        if finding.kind is FindingKind.PATH_INSIDE_LEGACY_INSTALL
    ] == [("beta: working directory", legacy.root / "work")]

    document = tomllib.loads(
        (paths.user_configs / "beta.toml").read_text(encoding="utf-8")
    )
    assert Path(document["general"]["working_dir"]) == legacy.root / "work"


def test_the_profile_that_was_in_use_is_reported_when_it_did_not_arrive(
    tmp_path: Path,
) -> None:
    """The program configuration names a profile; a fresh default hides its loss."""
    legacy = _install(tmp_path)
    (legacy.state / "config" / "program" / "conf.toml").write_text(
        'current_config = "gamma"\n', encoding="utf-8"
    )
    paths = _paths(tmp_path)

    run = import_legacy(paths, legacy)

    assert run.missing_profile == "gamma"


def test_importing_over_an_existing_directory_reports_no_missing_profile(
    tmp_path: Path,
) -> None:
    """A collision leaves the occupant's configuration consistent with itself.

    Pins a claim that turned out to be wrong. The guard's reasoning once said
    this was its everyday case: incoming profiles set aside while the program
    configuration naming them lands beside them. It cannot happen, because the
    program configuration collides too and is set aside with them, so what stays
    behind is the pair that was already there.
    """
    legacy = _install(tmp_path)
    paths = _paths(tmp_path)
    import_legacy(paths, legacy)

    second = import_legacy(paths, legacy)

    assert {diversion.planned for diversion in second.outcome.diverted} >= {
        paths.user_configs,
        paths.program,
    }
    assert second.missing_profile == ""


def test_the_user_document_keeps_its_comments_and_untouched_settings(
    tmp_path: Path,
) -> None:
    """Only the values a rewrite names may change. The file is the user's."""
    legacy = _install(tmp_path)
    paths = _paths(tmp_path)

    import_legacy(paths, legacy)

    body = (paths.user_configs / "alpha.toml").read_text(encoding="utf-8")
    assert "# a comment the user wrote" in body
    document = tomllib.loads(body)
    assert document["dependencies"]["ffmpeg"] == "D:/elsewhere/ffmpeg.exe"
    assert document["dependencies"]["enable_mkbrr"] is True


def test_the_installation_it_read_from_is_left_exactly_as_it_was(
    tmp_path: Path,
) -> None:
    """The one guarantee the whole design rests on: the source is never written.

    Asserted here rather than only against the copying code, because a rewrite
    resolving to the wrong tree would land on the original -- and it is applied
    after the copies, where the state root and the installation both exist and
    hold documents of the same shape.
    """
    legacy = _install(tmp_path)
    before = {
        path: path.read_bytes()
        for path in sorted(legacy.root.rglob("*"))
        if path.is_file()
    }

    import_legacy(_paths(tmp_path), legacy)

    assert {
        path: path.read_bytes()
        for path in sorted(legacy.root.rglob("*"))
        if path.is_file()
    } == before
