"""Everything outside the desktop frontend imports without Qt.

This is the boundary the command line, and any later server, depends on: they
drive the same backend the desktop application does, and must be able to run
where PySide6 is not installed at all.

The check runs in a fresh interpreter because this test session has already
imported Qt (`tests/conftest.py` builds a `QApplication`), so `sys.modules`
here cannot say what a headless import would pull in. The child blocks
PySide6 outright rather than checking afterwards, so a leak fails with the
chain of imports that reached it instead of a bare "PySide6 was loaded".
"""

import json
from pathlib import Path
import subprocess
import sys

from tests.repo_paths import REPO_ROOT

PACKAGE = REPO_ROOT / "nfoforge"

# Modules that are Qt by design and are not reachable from the headless code.
QT_BY_DESIGN = {
    "nfoforge.frontend",
    # Public plugin API: the base class a plugin's wizard page subclasses.
    "nfoforge.plugins.plugin_wizard_base",
}

_CHILD = r"""
import importlib, json, sys, traceback

class BlockQt:
    def find_spec(self, name, path=None, target=None):
        if name.partition(".")[0] in {"PySide6", "shiboken6", "qtawesome"}:
            raise ImportError(f"Qt import blocked: {name}")
        return None

sys.meta_path.insert(0, BlockQt())
failures = {}
for name in json.loads(sys.argv[1]):
    try:
        importlib.import_module(name)
    except Exception as error:
        chain = [
            f"{frame.filename}:{frame.lineno}"
            for frame in traceback.extract_tb(error.__traceback__)
            if "nfoforge" in frame.filename
        ]
        failures[name] = f"{error} via " + " <- ".join(reversed(chain))
print(json.dumps(failures))
"""


def _headless_modules() -> list[str]:
    names = []
    for path in sorted(PACKAGE.rglob("*.py")):
        parts = path.relative_to(REPO_ROOT).with_suffix("").parts
        name = ".".join(parts).removesuffix(".__init__")
        if any(name == q or name.startswith(q + ".") for q in QT_BY_DESIGN):
            continue
        names.append(name)
    return names


def test_headless_modules_are_found() -> None:
    modules = _headless_modules()

    assert "nfoforge.backend.process" in modules
    assert "nfoforge.config.config" in modules
    assert not any(name.startswith("nfoforge.frontend") for name in modules)


def test_headless_modules_import_without_qt() -> None:
    result = subprocess.run(  # noqa: S603 - fixed argv, this interpreter
        [sys.executable, "-c", _CHILD, json.dumps(_headless_modules())],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=50,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    failures: dict[str, str] = json.loads(result.stdout.splitlines()[-1])
    assert not failures, "\n".join(
        f"{name}: {reason}" for name, reason in sorted(failures.items())
    )


def test_qt_by_design_modules_exist() -> None:
    """Keep the exemption list from outliving what it exempts."""
    for name in QT_BY_DESIGN:
        relative = Path(*name.split("."))
        assert (REPO_ROOT / relative).is_dir() or (
            REPO_ROOT / relative.with_suffix(".py")
        ).is_file(), name
