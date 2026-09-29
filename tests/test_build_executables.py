"""A release is two bundles: the desktop app, and the command line without Qt.

These hold the build's half -- the desktop spec gains its debug executable,
the command line's leaves every Qt module out -- and the launcher's: each
entry point settles the data folder first, and the desktop app explains itself
when Qt is not installed.
"""

import io
from pathlib import Path
import re

import pytest

from build import (
    CONSOLE_EXECUTABLES,
    PLUGIN_API_MODULES,
    QT_MODULES,
    add_console_executables,
    spec_hiddenimports,
)
from nfoforge import launcher
import nfoforge.cli.main
from nfoforge.config.paths import default_paths

# the shape `pyi-makespec -w --name NfoForge` writes
GENERATED_SPEC = """\
a = Analysis(
    ['nfoforge/frontend/__main__.py'],
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


@pytest.fixture(autouse=True)
def plain_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    """No `--data-dir` unless a test gives one, and none left behind after."""
    monkeypatch.setattr(launcher.sys, "argv", ["nfoforge"])
    monkeypatch.setattr("nfoforge.config.paths._chosen_data_dir", None)


def test_the_desktop_spec_gains_the_debug_executable() -> None:
    spec = add_console_executables(GENERATED_SPEC)

    names = re.findall(r"name='([^']+)'", spec)
    assert names == ["NfoForge", "NfoForge-debug", "NfoForge"]
    assert spec.count("console=False") == 1
    assert spec.count("console=True") == 1
    # one bundle: every executable is collected together
    collect = spec[spec.index("COLLECT(") :]
    for variable in ("exe", *CONSOLE_EXECUTABLES):
        assert f"    {variable},\n" in collect


def test_a_spec_without_collect_is_refused() -> None:
    spec = GENERATED_SPEC[: GENERATED_SPEC.index("coll =")]

    with pytest.raises(ValueError, match="COLLECT"):
        add_console_executables(spec)


def test_the_command_line_bundle_takes_nothing_that_needs_qt() -> None:
    """Every plugin API module named for the bundle is Qt, and the command line
    bundle excludes Qt outright; naming one would pull Qt back in."""
    hidden = spec_hiddenimports(include_std_lib=False, gui=False)

    assert not set(PLUGIN_API_MODULES) & set(hidden)
    assert {"PySide6", "nfoforge.frontend"} <= set(QT_MODULES)


def test_the_command_line_entry_runs_the_command_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(nfoforge.cli.main, "main", lambda: 3)

    with pytest.raises(SystemExit) as exited:
        launcher.cli()

    assert exited.value.code == 3


def test_the_command_line_entry_chooses_the_data_dir_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The logger opens its file in the data folder as it is imported, so the
    folder has to be settled before the interface is."""
    seen: list[Path] = []

    def record() -> int:
        seen.append(default_paths().state_root)
        return 0

    monkeypatch.setattr(launcher.sys, "argv", ["nfoforge", "--data-dir", str(tmp_path)])
    monkeypatch.setattr(nfoforge.cli.main, "main", record)

    with pytest.raises(SystemExit):
        launcher.cli()

    assert seen == [tmp_path.resolve()]


def test_the_desktop_app_explains_itself_without_qt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    err = io.StringIO()
    monkeypatch.setattr(launcher, "find_spec", lambda _name: None)
    monkeypatch.setattr(launcher.sys, "stderr", err)

    with pytest.raises(SystemExit) as exited:
        launcher.gui()

    assert exited.value.code == 1
    assert "gui" in err.getvalue()
