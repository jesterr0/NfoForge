"""Where every way of starting NfoForge begins.

The `nfoforge` and `nfoforge-gui` commands, `python -m nfoforge.cli` and
`python -m nfoforge.frontend`, and the two frozen releases all start here, so
the data folder is chosen before anything else is imported. That order is the
point: the logger opens its file in the data folder as it is imported, so a
`--data-dir` read by an interface's own argument parser would come too late.

The desktop app needs Qt, which is an optional install (the `gui` extra); the
command line never does. So the two are released as separate bundles, and the
command line's carries no Qt at all.
"""

from importlib.util import find_spec
from multiprocessing import freeze_support
import sys

from nfoforge.config.paths import data_dir_from_argv, use_data_dir

CLI_EXECUTABLE = "nfoforge-cli"
"""The command line's file name in a release, without its extension. Not
`nfoforge`: Windows file names ignore case, so beside the desktop app's
`NfoForge.exe` it would collide."""

GUI_MISSING = (
    "The desktop app needs Qt, which is not installed. Install it with the "
    "`gui` extra (for example `pip install 'nfoforge[gui]'`, or "
    "`uv sync --extra gui` from a checkout), or use the command line: nfoforge"
)


def _report(message: str) -> None:
    """Say `message` without Qt, which is what is missing.

    `nfoforge-gui` is a windowed launcher on Windows, which has no console, so
    `sys.stderr` is None there and a native message box is the only way to be
    seen.
    """
    if sys.stderr is not None:
        sys.stderr.write(f"{message}\n")
    elif sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "NfoForge", 0x10)


def _start() -> None:
    # a multiprocessing child re-runs the executable; this is where it takes
    # over, before either interface starts
    freeze_support()
    use_data_dir(data_dir_from_argv(sys.argv[1:]))


def cli() -> None:
    """The command line."""
    _start()
    from nfoforge.cli.main import main as cli_main

    sys.exit(cli_main())


def gui() -> None:
    """The desktop app."""
    _start()
    if find_spec("PySide6") is None:
        _report(GUI_MISSING)
        sys.exit(1)
    # the desktop app loads `.env` as it is imported, so nothing else of
    # NfoForge may be imported ahead of it
    from nfoforge.frontend.app import main as gui_main

    gui_main()
