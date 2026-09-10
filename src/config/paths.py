from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

from src.backend.utils.working_dir import RUNTIME_DIR


@dataclass(frozen=True, slots=True)
class ConfigPaths:
    default_config: Path = RUNTIME_DIR / "config" / "defaults" / "default_config.toml"
    default_program: Path = (
        RUNTIME_DIR / "config" / "defaults" / "default_program_conf.toml"
    )
    program: Path = RUNTIME_DIR / "config" / "program" / "conf.toml"
    user_configs: Path = RUNTIME_DIR / "config" / "user"
    tracker_cookies: Path = RUNTIME_DIR / "cookies"

    @staticmethod
    def data_root() -> Path:
        """NfoForge's own per-user directory, and nothing above it.

        Named separately from `default_working_dir` because the two are the
        same path only for as long as the working directory defaults to the
        root of this directory. Cleanup asks for this one: it needs to know
        what it must never be able to delete, which is not the same question
        as where a run's output goes.
        """
        return Path(user_data_dir(appname="nfoforge", appauthor=False))

    @staticmethod
    def default_working_dir(ensure_exists: bool = False) -> Path:
        path = ConfigPaths.data_root()
        if ensure_exists:
            path.mkdir(parents=True, exist_ok=True)
        return path
