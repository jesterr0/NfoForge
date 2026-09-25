"""A read-only ConfigManager never writes the program config or a profile.

Headless runs share the profile with a desktop application that may be open at
the same time, and nothing locks the files.
"""

from pathlib import Path

import pytest
import tomlkit

from nfoforge.config.config import ConfigManager
from nfoforge.config.paths import ConfigPaths
from nfoforge.exceptions import ConfigError
from tests.test_config.config_tree import build_config_paths


@pytest.fixture(autouse=True)
def _no_dependency_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nfoforge.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )


@pytest.fixture
def paths(tmp_path: Path) -> ConfigPaths:
    paths = build_config_paths(tmp_path)
    # Two profiles, "main" left current, as a GUI user would have.
    ConfigManager("other", paths)
    ConfigManager("main", paths)
    return paths


def _snapshot(paths: ConfigPaths) -> dict[Path, bytes]:
    files = [paths.program, *paths.user_configs.glob("*.toml")]
    return {path: path.read_bytes() for path in files}


def test_loading_writes_nothing(paths: ConfigPaths) -> None:
    before = _snapshot(paths)

    manager = ConfigManager("other", paths, read_only=True)

    assert manager.settings.general.timeout == 60
    assert _snapshot(paths) == before


def test_loading_does_not_change_the_current_profile(paths: ConfigPaths) -> None:
    ConfigManager("other", paths, read_only=True)

    assert ConfigManager(None, paths).program.current_config == "main"


def test_save_is_refused(paths: ConfigPaths) -> None:
    manager = ConfigManager("other", paths, read_only=True)
    before = _snapshot(paths)

    with pytest.raises(ConfigError, match="read-only"):
        manager.save()
    with pytest.raises(ConfigError, match="read-only"):
        manager.save_program()

    assert _snapshot(paths) == before


def test_missing_profile_is_refused_rather_than_created(paths: ConfigPaths) -> None:
    with pytest.raises(ConfigError, match="does not exist"):
        ConfigManager("nope", paths, read_only=True)

    assert not (paths.user_configs / "nope.toml").exists()


def test_profile_needing_migration_is_refused_and_left_alone(
    paths: ConfigPaths,
) -> None:
    profile = paths.user_configs / "other.toml"
    document = tomlkit.parse(profile.read_text(encoding="utf-8"))
    document["schema_version"] = 1
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")
    before = _snapshot(paths)

    with pytest.raises(ConfigError, match="needs migrating"):
        ConfigManager("other", paths, read_only=True)

    assert _snapshot(paths) == before
