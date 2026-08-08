"""Coverage for read-only discovery of config profiles' working directories."""

from dataclasses import replace
from pathlib import Path

import pytest

from src.config.paths import ConfigPaths
from src.config.profiles import (
    profile_working_dir,
    profile_working_dirs,
    unique_working_dirs,
)


@pytest.fixture
def paths(tmp_path: Path) -> ConfigPaths:
    user_configs = tmp_path / "user"
    user_configs.mkdir(parents=True)
    return replace(ConfigPaths(), user_configs=user_configs)


def _write_profile(paths: ConfigPaths, name: str, working_dir: str | None) -> Path:
    body = "[general]\n"
    if working_dir is not None:
        body += f'working_dir = "{working_dir}"\n'
    path = paths.user_configs / f"{name}.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_reads_the_declared_working_directory(paths: ConfigPaths) -> None:
    path = _write_profile(paths, "config", "D:/media/nfoforge")

    assert profile_working_dir(path) == Path("D:/media/nfoforge")


def test_every_profile_is_mapped(paths: ConfigPaths) -> None:
    _write_profile(paths, "config", "D:/one")
    _write_profile(paths, "anime", "D:/two")

    assert profile_working_dirs(paths) == {
        "config": Path("D:/one"),
        "anime": Path("D:/two"),
    }


def test_a_profile_without_a_working_dir_falls_back(paths: ConfigPaths) -> None:
    """Its jobs must still be findable rather than silently dropped."""
    _write_profile(paths, "config", None)

    assert profile_working_dirs(paths) == {"config": ConfigPaths.default_working_dir()}


def test_an_unparsable_profile_is_skipped_not_fatal(paths: ConfigPaths) -> None:
    """A profile the picker only wanted a path from must not take it down.

    Going through ConfigManager would validate and migrate, which a stale
    profile can legitimately fail; this reads one key and tolerates anything.
    """
    _write_profile(paths, "good", "D:/one")
    (paths.user_configs / "broken.toml").write_text(
        "not [ valid toml", encoding="utf-8"
    )

    discovered = profile_working_dirs(paths)

    assert discovered["good"] == Path("D:/one")
    # the broken profile still gets an entry, just the fallback path
    assert discovered["broken"] == ConfigPaths.default_working_dir()


def test_a_profile_with_no_general_section_falls_back(paths: ConfigPaths) -> None:
    (paths.user_configs / "odd.toml").write_text("[other]\nx = 1\n", encoding="utf-8")

    assert profile_working_dirs(paths)["odd"] == ConfigPaths.default_working_dir()


def test_shared_working_directories_are_deduplicated(paths: ConfigPaths) -> None:
    """Profiles commonly share one working dir; it must be scanned once."""
    _write_profile(paths, "config", "D:/shared")
    _write_profile(paths, "anime", "D:/shared")
    _write_profile(paths, "other", "D:/elsewhere")

    assert unique_working_dirs(paths) == [Path("D:/shared"), Path("D:/elsewhere")]


def test_a_missing_config_directory_yields_nothing(tmp_path: Path) -> None:
    paths = replace(ConfigPaths(), user_configs=tmp_path / "never-created")

    assert profile_working_dirs(paths) == {}
