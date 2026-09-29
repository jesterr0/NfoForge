"""Where every way of starting NfoForge begins.

The `nfoforge` and `nfoforge-gui` commands, `python -m nfoforge.cli` and
`python -m nfoforge.frontend`, and the frozen executables all start here, so
the data folder is chosen before anything else is imported. That order is the
point: the logger opens its file in the data folder as it is imported, so a
`--data-dir` read by an interface's own argument parser would come too late.

A release ships the desktop app and the command line as separate executables,
because Windows fixes at build time whether a program gets a console. Both are
built from this script over one shared bundle, so a plugin the desktop app can
load, Qt and all, loads the same way from the command line. Each executable
picks what to run from its own file name.
"""

from multiprocessing import freeze_support
from pathlib import Path
import sys

from nfoforge.config.paths import data_dir_from_argv, use_data_dir

CLI_EXECUTABLE = "nfoforge-cli"
"""The command line's file name in a release, without its extension. Not
`nfoforge`: Windows file names ignore case, so it would collide with the
desktop app's `NfoForge.exe`."""


def is_cli(executable: str) -> bool:
    return Path(executable).stem.casefold() == CLI_EXECUTABLE


def _choose_data_dir() -> None:
    use_data_dir(data_dir_from_argv(sys.argv[1:]))


def cli() -> None:
    """The command line."""
    _choose_data_dir()
    from nfoforge.cli.main import main as cli_main

    sys.exit(cli_main())


def gui() -> None:
    """The desktop app."""
    _choose_data_dir()
    # the desktop app loads `.env` as it is imported, so nothing else of
    # NfoForge may be imported ahead of it
    from nfoforge.frontend.app import main as gui_main

    gui_main()


def main() -> None:
    """The frozen executables: the interface is chosen by file name."""
    # a multiprocessing child re-runs the executable; this is where it takes
    # over, before either interface starts
    freeze_support()
    if is_cli(sys.executable):
        cli()
    else:
        gui()


if __name__ == "__main__":
    main()
