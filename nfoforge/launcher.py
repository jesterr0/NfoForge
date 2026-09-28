"""The frozen build's one entry point.

A release ships the desktop app and the command line as separate executables,
because Windows fixes at build time whether a program gets a console. Both are
built from this script over one shared bundle, so a plugin the desktop app can
load, Qt and all, loads the same way from the command line. Each executable
picks what to run from its own file name.

From a source checkout, use the `nfoforge` and `nfoforge-gui` commands instead.
"""

from multiprocessing import freeze_support
from pathlib import Path
import sys

CLI_EXECUTABLE = "nfoforge-cli"
"""The command line's file name in a release, without its extension. Not
`nfoforge`: Windows file names ignore case, so it would collide with the
desktop app's `NfoForge.exe`."""


def is_cli(executable: str) -> bool:
    return Path(executable).stem.casefold() == CLI_EXECUTABLE


def main() -> None:
    # a multiprocessing child re-runs the executable; this is where it takes
    # over, before either interface starts
    freeze_support()
    if is_cli(sys.executable):
        from nfoforge.cli.main import main as cli_main

        sys.exit(cli_main())

    # the desktop app loads `.env` as it is imported, so nothing else may be
    # imported ahead of it
    from nfoforge.frontend.app import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
