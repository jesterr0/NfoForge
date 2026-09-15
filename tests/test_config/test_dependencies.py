"""Coverage for how optional external tools are located.

The middle rung of the search is a directory the user puts executables in
themselves -- documented, and in real use. It moves with the rest of the user's
state, so discovery has to follow it there rather than keep looking beside the
installed application, which is about to become a folder people are told they
can empty.
"""

from pathlib import Path
import shutil

import pytest

from src.backend.utils.get_os_executable_ext import get_executable_string_by_os
from src.config.dependencies import FindDependencies
from src.config.models import DependencySettings
from src.enums.dependencies import Dependencies

OS_EXE = get_executable_string_by_os()


def _settings(**configured: Path | None) -> DependencySettings:
    """Dependency settings with nothing configured unless a test says otherwise."""
    fields: dict[str, Path | None | bool] = {
        "ffmpeg": None,
        "ffprobe": None,
        "frame_forge": None,
        "mkbrr": None,
        "enable_mkbrr": False,
    }
    fields.update(configured)
    return DependencySettings(**fields)  # type: ignore[arg-type]


def _tool(tools_root: Path, dependency: Dependencies) -> Path:
    """A stand-in executable where discovery is expected to look for it.

    The folder and the executable are named separately because they do not
    always match -- one tool's directory does not share its binary's name, and
    a helper that assumed otherwise would make that tool's test pass for the
    wrong reason.
    """
    mapping = dependency.dep_map()
    path = tools_root / mapping["app_folder"] / f"{mapping['executable']}{OS_EXE}"
    path.parent.mkdir(parents=True)
    path.touch()
    return path


@pytest.fixture(autouse=True)
def _no_system_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the build machine's own PATH out of these assertions.

    Without this, a machine with ffmpeg installed passes tests about the other
    two rungs for the wrong reason.
    """
    monkeypatch.setattr(shutil, "which", lambda _name: None)


def test_a_configured_path_wins(tmp_path: Path) -> None:
    """A path the user set is never second-guessed while it still resolves."""
    tools_root = tmp_path / "tools"
    _tool(tools_root, Dependencies.FFMPEG)
    chosen = tmp_path / "elsewhere" / f"ffmpeg{OS_EXE}"
    chosen.parent.mkdir(parents=True)
    chosen.touch()
    settings = _settings(ffmpeg=chosen)

    FindDependencies(tools_root).update_dependencies(settings)

    assert settings.ffmpeg == chosen


def test_the_tools_directory_is_searched_when_nothing_is_configured(
    tmp_path: Path,
) -> None:
    tools_root = tmp_path / "tools"
    expected = _tool(tools_root, Dependencies.FFMPEG)
    settings = _settings()

    FindDependencies(tools_root).update_dependencies(settings)

    assert settings.ffmpeg == expected


def test_the_system_path_is_the_last_resort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    on_path = tmp_path / "bin" / f"ffmpeg{OS_EXE}"
    on_path.parent.mkdir(parents=True)
    on_path.touch()
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: str(on_path) if name.startswith("ffmpeg") else None,
    )
    settings = _settings()

    FindDependencies(tmp_path / "empty-tools").update_dependencies(settings)

    assert settings.ffmpeg == on_path


def test_an_absent_tool_leaves_the_setting_alone(tmp_path: Path) -> None:
    """Nothing found anywhere must not invent a path that does not exist."""
    settings = _settings()

    FindDependencies(tmp_path / "empty-tools").update_dependencies(settings)

    assert settings.ffmpeg is None


def test_every_dependency_is_discovered_from_the_tools_directory(
    tmp_path: Path,
) -> None:
    """Covers the whole enum, so a tool added later is not quietly left out."""
    tools_root = tmp_path / "tools"
    expected = {
        dependency: _tool(tools_root, dependency) for dependency in Dependencies
    }
    settings = _settings()

    FindDependencies(tools_root).update_dependencies(settings)

    for dependency, path in expected.items():
        assert getattr(settings, dependency.dep_map()["cfg_var"]) == path
