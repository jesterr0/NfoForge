"""Coverage for the path object every other module asks for its locations.

Two roots go in and every path comes out of one of them. The old form bound
its paths as class attributes computed from `Path.cwd()` at import, which is
why a test that wanted a throwaway tree had to name five paths by hand and why
nothing could be reconfigured afterwards.
"""

from pathlib import Path
import sys

import pytest

from src.config.paths import DATA_DIR_ENV_VAR, AppPaths, ConfigPaths, default_paths


def test_config_paths_is_the_same_class(tmp_path: Path) -> None:
    """Plugins read `config.paths.user_configs`, and tests construct the class.

    Both are public surface held by code this release cannot patch, so the old
    name stays bound to the new class and the attribute names do not move. An
    alias that kept a name while changing what it pointed at would be worse
    than a rename, because nothing would fail loudly.
    """
    assert ConfigPaths is AppPaths


def test_state_paths_derive_from_the_state_root(tmp_path: Path) -> None:
    state = tmp_path / "state"
    paths = AppPaths(state_root=state, asset_root=tmp_path / "assets")

    assert paths.program == state / "config" / "program" / "conf.toml"
    assert paths.user_configs == state / "config" / "user"
    assert paths.tracker_cookies == state / "cookies"


def test_packaged_defaults_derive_from_the_asset_root(tmp_path: Path) -> None:
    """The packaged defaults are shipped files, so they come from the assets.

    This is the split the whole refactor turns on: the defaults a release reads
    are read-only and travel with the build, while everything the user edits
    lives somewhere a release can be replaced without touching it.
    """
    assets = tmp_path / "assets"
    paths = AppPaths(state_root=tmp_path / "state", asset_root=assets)

    assert (
        paths.default_config == assets / "config" / "defaults" / "default_config.toml"
    )
    assert (
        paths.default_program
        == assets / "config" / "defaults" / "default_program_conf.toml"
    )


def test_every_path_sits_under_one_of_the_two_roots(tmp_path: Path) -> None:
    """No path may be left bound to somewhere neither root names.

    Walks the object rather than listing paths, so a property added later is
    covered without anyone remembering to extend this test.
    """
    state = tmp_path / "state"
    assets = tmp_path / "assets"
    paths = AppPaths(state_root=state, asset_root=assets)

    found = {
        name: value
        for name in dir(paths)
        if not name.startswith("_")
        and isinstance(value := getattr(paths, name, None), Path)
    }

    assert found, "no paths were discovered, so this test proves nothing"
    for name, value in found.items():
        assert value.is_relative_to(state) or value.is_relative_to(assets), (
            f"{name} resolves to {value}, which is under neither root"
        )


def test_state_root_defaults_to_the_mutable_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree = Path("/somewhere/runtime")
    monkeypatch.setattr("src.config.paths.RUNTIME_DIR", tree)
    monkeypatch.delenv(DATA_DIR_ENV_VAR, raising=False)

    assert default_paths().state_root == tree


def test_the_data_directory_override_is_honoured_from_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The override exists so a real migration can be rehearsed.

    Running from source has to honour it, or development after the state move
    reads and writes the same per-user directory as an installed copy, and a
    dev run would offer to migrate a working tree into it.
    """
    monkeypatch.setattr("src.config.paths.IS_FROZEN", False)
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path / "rehearsal"))

    assert default_paths().state_root == tmp_path / "rehearsal"


def test_the_override_is_refused_by_a_released_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A shipped executable must not let the environment move user data.

    Otherwise anything that can set a variable in the process environment
    decides where profiles, cookies and credentials are read from.
    """
    mutable = Path("/installed/runtime")
    monkeypatch.setattr("src.config.paths.IS_FROZEN", True)
    monkeypatch.setattr("src.config.paths.RUNTIME_DIR", mutable)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "NfoForge.exe"))
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path / "rehearsal"))

    assert default_paths().state_root == mutable


def test_the_override_is_honoured_by_the_debug_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A release ships a debug executable beside the main one.

    That is the one a rehearsal runs, so the migration can be exercised on the
    artefact that actually ships rather than only from source.
    """
    monkeypatch.setattr("src.config.paths.IS_FROZEN", True)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "NfoForge-debug.exe"))
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path / "rehearsal"))

    assert default_paths().state_root == tmp_path / "rehearsal"


def test_a_blank_override_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty or whitespace value is an unset variable, not the filesystem root."""
    tree = Path("/somewhere/runtime")
    monkeypatch.setattr("src.config.paths.RUNTIME_DIR", tree)
    monkeypatch.setattr("src.config.paths.IS_FROZEN", False)
    monkeypatch.setenv(DATA_DIR_ENV_VAR, "   ")

    assert default_paths().state_root == tree
