from os import PathLike
from pathlib import Path
import shutil
from typing import TYPE_CHECKING

from src.backend.utils.get_os_executable_ext import get_executable_string_by_os
from src.enums.dependencies import Dependencies
from src.enums.screen_shot_mode import ScreenShotMode

if TYPE_CHECKING:
    from src.config.models import DependencySettings

# determine os exe
OS_EXE = get_executable_string_by_os()


def unavailable_screenshot_dependency(
    mode: ScreenShotMode,
    ffmpeg_path: Path | None,
    frame_forge_path: Path | None,
) -> Dependencies | None:
    """Return the executable missing for ``mode``, if one is required.

    Callers can pass either persisted paths or paths from an unsaved settings
    draft. Keeping this check independent of the UI prevents the two paths
    from applying different availability rules.
    """
    dependency: Dependencies
    path: Path | None
    if mode in (
        ScreenShotMode.BASIC_SS_GEN,
        ScreenShotMode.SIMPLE_SS_COMP,
    ):
        dependency = Dependencies.FFMPEG
        path = ffmpeg_path
    elif mode == ScreenShotMode.ADV_SS_COMP:
        dependency = Dependencies.FRAME_FORGE
        path = frame_forge_path
    else:
        return None

    return dependency if path is None or not path.is_file() else None


class FindDependencies:
    """A utility class for finding and verifying dependencies required by a program

    `tools_root` is where the user may place optional executables themselves,
    one directory per tool. It travels with the rest of their state rather than
    sitting beside the installed application, so replacing a release does not
    take a hand-assembled toolchain with it.
    """

    def __init__(self, tools_root: Path) -> None:
        self.tools_root = tools_root

    def update_dependencies(self, dependencies: "DependencySettings") -> None:
        for dependency in Dependencies:
            current_path = getattr(dependencies, dependency.name.lower())
            if current_path and Path(current_path).exists():
                continue

            dep_map = dependency.dep_map()

            find_dep = self._find_dependency(
                dep_map["app_folder"], dep_map["executable"], current_path
            )
            if find_dep:
                setattr(dependencies, dep_map["cfg_var"], find_dep)

    def _find_dependency(
        self, app_folder_name: str, executable: str, user_defined: PathLike[str] | None
    ) -> Path | None:
        """
        Finds a single dependency, first the user-defined location, then the user's
        own tools directory and finally on the system PATH.
        """
        # user-defined path
        if user_defined:
            user_path = Path(user_defined)
            if user_path.exists():
                return user_path

        # the user's own tools directory
        in_tools = self._locate_in_tools(app_folder_name, executable)
        if in_tools:
            return in_tools

        # system PATH
        return self._locate_on_system_path(executable)

    def _locate_in_tools(self, app_folder_name: str, executable: str) -> Path | None:
        """Checks the user's tools directory for the dependency's own folder."""
        path = self.tools_root / app_folder_name / f"{executable}{OS_EXE}"
        return path if path.is_file() else None

    def _locate_on_system_path(self, executable: str) -> Path | None:
        """Checks if the dependency exists on the system PATH"""
        path = shutil.which(f"{executable}{OS_EXE}")
        return Path(path) if path else None
