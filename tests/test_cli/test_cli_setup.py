"""`nfoforge setup`: the desktop app's first launch, from a terminal."""

import io
from pathlib import Path
import shutil

import pytest
import tomlkit

from nfoforge.cli.app import CliError
from nfoforge.cli.exit_codes import ExitCode
from nfoforge.cli.main import main
from nfoforge.cli.setup import SetupOptions, run_setup
from nfoforge.config.codec import TomlConfigCodec
from nfoforge.config.layout_version import migration_pending
from nfoforge.config.migrations import document_version
from nfoforge.config.paths import AppPaths, default_paths

FIXTURES = Path(__file__).parents[1] / "test_config" / "fixtures"


@pytest.fixture(autouse=True)
def quiet_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "nfoforge.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    # nothing is found beside the "executable" unless a test puts it there;
    # the repository itself looks like an old source install
    beside = tmp_path / "beside_the_executable"
    beside.mkdir()
    monkeypatch.setattr("nfoforge.config.layout_apply.CURRENT_DIR", beside)


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    return AppPaths(state_root=tmp_path / "data", asset_root=default_paths().asset_root)


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    """A source-layout installation from before the data folder existed, whose
    one profile is several schema versions old."""
    root = tmp_path / "old_nfoforge"
    profiles = root / "runtime" / "config" / "user"
    profiles.mkdir(parents=True)
    shutil.copy(FIXTURES / "schema2_config.toml", profiles / "main.toml")
    return root


def _setup(
    paths: AppPaths, options: SetupOptions, answers: list[str] | None = None
) -> str:
    out = io.StringIO()
    ask = None if answers is None else (lambda _prompt: answers.pop(0))
    run_setup(options, paths, out, ask)
    return out.getvalue()


def _version(profile: Path) -> int:
    return document_version(tomlkit.parse(profile.read_text(encoding="utf-8")))


def test_a_fresh_start_is_refused_when_nobody_can_say_what_to_import(
    paths: AppPaths,
) -> None:
    with pytest.raises(CliError, match="--no-import"):
        _setup(paths, SetupOptions())

    assert migration_pending(paths.state_root)
    assert not paths.user_configs.exists()


def test_starting_fresh_creates_a_profile_and_is_safe_to_repeat(
    paths: AppPaths,
) -> None:
    first = _setup(paths, SetupOptions(no_import=True))

    assert not migration_pending(paths.state_root)
    assert [path.name for path in paths.user_configs.glob("*.toml")] == ["config.toml"]
    assert "Created profile 'config'" in first
    assert "Setup is complete" in first

    again = _setup(paths, SetupOptions(no_import=True))
    assert "up to date" in again
    assert "Created profile" not in again


def test_importing_brings_the_profile_across_and_upgrades_it(
    paths: AppPaths, legacy: Path
) -> None:
    output = _setup(paths, SetupOptions(import_from=legacy))

    profile = paths.user_configs / "main.toml"
    assert profile.is_file()
    assert _version(profile) == TomlConfigCodec.SCHEMA_VERSION
    assert "Upgraded profile 'main'" in output
    assert (paths.logs / "migration.log").is_file()


def test_importing_into_a_folder_already_set_up_keeps_what_is_there(
    paths: AppPaths, legacy: Path
) -> None:
    """As the desktop app's Settings import does: set aside, never overwrite."""
    _setup(paths, SetupOptions(no_import=True))
    before = (paths.user_configs / "config.toml").read_bytes()

    _setup(paths, SetupOptions(import_from=legacy))

    # the profiles folder was already in use, so the incoming one is set aside
    assert (paths.user_configs / "config.toml").read_bytes() == before
    assert not (paths.user_configs / "main.toml").exists()
    assert list((paths.state_root / "migration-conflicts").rglob("main.toml"))


def test_upgrading_does_not_change_which_profile_is_active(
    paths: AppPaths, legacy: Path
) -> None:
    _setup(paths, SetupOptions(no_import=True))
    before = paths.program.read_bytes()
    shutil.copy(FIXTURES / "schema2_config.toml", paths.user_configs / "old.toml")

    output = _setup(paths, SetupOptions(no_import=True))

    assert "Upgraded profile 'old'" in output
    assert _version(paths.user_configs / "old.toml") == TomlConfigCodec.SCHEMA_VERSION
    assert paths.program.read_bytes() == before


def test_a_folder_holding_no_installation_is_refused_before_anything_is_done(
    paths: AppPaths, tmp_path: Path
) -> None:
    with pytest.raises(CliError, match="No previous NfoForge installation"):
        _setup(paths, SetupOptions(import_from=tmp_path / "nothing_here"))

    assert migration_pending(paths.state_root)


def test_at_a_terminal_a_wrong_folder_is_asked_about_again(
    paths: AppPaths, legacy: Path, tmp_path: Path
) -> None:
    output = _setup(
        paths, SetupOptions(), answers=[str(tmp_path / "wrong"), str(legacy)]
    )

    assert "No NfoForge installation was found in" in output
    assert (paths.user_configs / "main.toml").is_file()


def test_at_a_terminal_an_empty_answer_starts_fresh(paths: AppPaths) -> None:
    output = _setup(paths, SetupOptions(), answers=[""])

    assert "No previous installation was found" in output
    assert (paths.user_configs / "config.toml").is_file()


def test_templates_with_renamed_tokens_are_updated_only_when_asked(
    paths: AppPaths,
) -> None:
    paths.templates.mkdir(parents=True)
    template = paths.templates / "movie.txt"
    template.write_text("Title: {{ movie_title }}", encoding="utf-8")

    left = _setup(paths, SetupOptions(no_import=True))
    assert "movie.txt" in left
    assert "--update-templates" in left
    assert "movie_title" in template.read_text(encoding="utf-8")

    _setup(paths, SetupOptions(no_import=True, update_templates=True))
    assert "movie_title" not in template.read_text(encoding="utf-8")


def test_setup_runs_from_the_command_line_without_a_profile() -> None:
    out, err = io.StringIO(), io.StringIO()

    refused = main(["--no-input", "setup"], out, err)
    assert refused == ExitCode.FAILED
    assert "--no-import" in err.getvalue()

    done = main(["--no-input", "setup", "--no-import"], out, err)
    assert done == ExitCode.OK
    assert "Setup is complete" in out.getvalue()


def test_other_commands_point_to_setup() -> None:
    err = io.StringIO()

    code = main(["--no-input", "jobs", "list"], io.StringIO(), err)

    assert code == ExitCode.FAILED
    assert "setup" in err.getvalue()
