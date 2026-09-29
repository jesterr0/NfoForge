"""A release carries the command line beside the desktop app.

Both are built from `nfoforge.launcher` over one bundle, and each picks its
interface from its own file name. These hold both halves: the spec gains the
executables under the names the launcher expects, and the launcher runs the
right interface for each name.
"""

from pathlib import Path
import re

import pytest

from build import CONSOLE_EXECUTABLES, add_console_executables
from nfoforge import launcher
import nfoforge.cli.main
from nfoforge.config.paths import default_paths
import nfoforge.frontend.app

# the shape `pyi-makespec -w --name NfoForge` writes
GENERATED_SPEC = """\
a = Analysis(
    ['nfoforge/launcher.py'],
    hiddenimports=[],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NfoForge',
    console=False,
    contents_directory='bundle',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name='NfoForge',
)
"""


def test_the_spec_gains_the_debug_and_command_line_executables() -> None:
    spec = add_console_executables(GENERATED_SPEC)

    names = re.findall(r"name='([^']+)'", spec)
    assert names == ["NfoForge", "NfoForge-debug", launcher.CLI_EXECUTABLE, "NfoForge"]
    assert spec.count("console=False") == 1
    assert spec.count("console=True") == 2
    # one bundle: every executable is collected together
    collect = spec[spec.index("COLLECT(") :]
    for variable in ("exe", *CONSOLE_EXECUTABLES):
        assert f"    {variable},\n" in collect


def test_a_spec_without_collect_is_refused() -> None:
    spec = GENERATED_SPEC[: GENERATED_SPEC.index("coll =")]

    with pytest.raises(ValueError, match="COLLECT"):
        add_console_executables(spec)


@pytest.mark.parametrize(
    ("executable", "cli"),
    [
        ("C:/Program Files/NfoForge/nfoforge-cli.exe", True),
        ("/opt/NfoForge/nfoforge-cli", True),
        ("C:/Program Files/NfoForge/NfoForge.exe", False),
        ("C:/Program Files/NfoForge/NfoForge-debug.exe", False),
    ],
)
def test_the_launcher_tells_the_executables_apart(executable: str, cli: bool) -> None:
    assert launcher.is_cli(executable) is cli


@pytest.fixture(autouse=True)
def plain_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    """No `--data-dir` unless a test gives one, and none left behind after."""
    monkeypatch.setattr(launcher.sys, "argv", ["nfoforge"])
    monkeypatch.setattr("nfoforge.config.paths._chosen_data_dir", None)


def test_the_command_line_executable_runs_the_command_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launcher.sys, "executable", "C:/NfoForge/nfoforge-cli.exe")
    monkeypatch.setattr(nfoforge.cli.main, "main", lambda: 3)
    monkeypatch.setattr(
        nfoforge.frontend.app, "main", lambda: pytest.fail("started the GUI")
    )

    with pytest.raises(SystemExit) as exited:
        launcher.main()

    assert exited.value.code == 3


def test_any_other_executable_runs_the_desktop_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[bool] = []
    monkeypatch.setattr(launcher.sys, "executable", "C:/NfoForge/NfoForge.exe")
    monkeypatch.setattr(nfoforge.frontend.app, "main", lambda: started.append(True))

    launcher.main()

    assert started == [True]


@pytest.mark.parametrize("entry", ["cli", "gui"])
def test_the_data_dir_is_chosen_before_the_interface_is_imported(
    entry: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The logger opens its file in the data folder as it is imported, so the
    folder has to be settled before either interface is."""
    seen: list[Path] = []

    def record() -> int:
        seen.append(default_paths().state_root)
        return 0

    monkeypatch.setattr(launcher.sys, "argv", ["nfoforge", "--data-dir", str(tmp_path)])
    monkeypatch.setattr(nfoforge.cli.main, "main", record)
    monkeypatch.setattr(nfoforge.frontend.app, "main", record)

    try:
        getattr(launcher, entry)()
    except SystemExit:
        pass

    assert seen == [tmp_path.resolve()]
