from os import PathLike
from pathlib import Path
import shutil
from typing import TYPE_CHECKING

from src.backend.utils.get_os_executable_ext import get_executable_string_by_os
from src.backend.utils.working_dir import RUNTIME_DIR
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
    """A utility class for finding and verifying dependencies required by a program"""

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
        Finds a single dependency, first the user-defined location, then beside the
        program and finally on the system PATH.
        """
        # user-defined path
        if user_defined:
            user_path = Path(user_defined)
            if user_path.exists():
                return user_path

        # beside the program
        beside_program = self._locate_beside_program(app_folder_name, executable)
        if beside_program:
            return beside_program

        # system PATH
        return self._locate_on_system_path(executable)

    def _locate_beside_program(
        self, app_folder_name: str, executable: str
    ) -> Path | None:
        """Checks if the dependency exists beside the program in a predefined structure"""
        path = Path(RUNTIME_DIR / "apps" / app_folder_name / f"{executable}{OS_EXE}")
        return path if path.exists() and path.is_file() else None

    def _locate_on_system_path(self, executable: str) -> Path | None:
        """Checks if the dependency exists on the system PATH"""
        path = shutil.which(f"{executable}{OS_EXE}")
        return Path(path) if path else None
