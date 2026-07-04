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
    def default_working_dir(ensure_exists: bool = False) -> Path:
        path = Path(user_data_dir(appname="nfoforge", appauthor=False))
        if ensure_exists:
            path.mkdir(parents=True, exist_ok=True)
        return path
