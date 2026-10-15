"""`nfoforge config path` and `nfoforge config check`."""

import io
from pathlib import Path

import pytest

from nfoforge.cli.exit_codes import ExitCode
from nfoforge.cli.main import main
from nfoforge.config.paths import default_paths


@pytest.fixture(autouse=True)
def quiet_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "nfoforge.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    beside = tmp_path / "beside_the_executable"
    beside.mkdir()
    monkeypatch.setattr("nfoforge.config.layout_apply.CURRENT_DIR", beside)


def _run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = main(["--no-input", *argv], out, err)
    return code, out.getvalue(), err.getvalue()


def test_config_path_works_before_anything_is_set_up() -> None:
    code, out, _err = _run("config", "path")

    assert code == ExitCode.OK
    assert f"Data folder: {default_paths().state_root}" in out
    assert "No config profile exists yet" in out


def test_config_path_names_the_profile_file_once_there_is_one() -> None:
    _run("setup", "--no-import")

    _code, out, _err = _run("config", "path")

    assert str(default_paths().user_configs / "config.toml") in out


def test_config_check_fails_and_lists_every_problem() -> None:
    _run("setup", "--no-import")

    code, out, _err = _run("config", "check", "--trackers", "aither,nope")

    assert code == ExitCode.FAILED
    assert "problem: TMDB" in out
    assert "nope" in out
    assert "no NFO template is assigned" in out
    assert "problem(s)" in out


def test_config_check_needs_setup_first() -> None:
    code, _out, err = _run("config", "check")

    assert code == ExitCode.FAILED
    assert "setup" in err
