import sys
from typing import Tuple
from pathlib import Path


def _get_working_directories() -> Tuple[Path, Path]:
    """
    Used to determine the correct working directory automatically.
    This way we can utilize files/relative paths easily.

    Returns:
        (Path, Path): Current working directory, runtime directory
    """
    # we're in a pyinstaller bundle
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        path = Path(sys.executable).parent
        return path, path / "bundle" / "runtime"

    # we're running from a *.py file
    else:
        path = Path.cwd()
        return path, path / "runtime"


CURRENT_DIR, RUNTIME_DIR = _get_working_directories()
