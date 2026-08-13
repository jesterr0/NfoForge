"""Plugin-facing modules must be declared for the frozen build to collect them.

PyInstaller assembles its module list by walking imports from the entry script,
so a module nothing in NfoForge imports is never reached and does not enter the
bundle. Most of `src.plugins` rides along because the loader and manager import
it for their own work, but a module written purely for external plugins to
subclass or call has no internal importer by design. It drops out of every
release while continuing to work when NfoForge runs from source, and the plugin
that imports it then fails with `No module named ...` for the user alone.

The build cannot discover these for itself. Plugins are copied in after the
freeze, are not present on the build machine, and may be compiled, which puts
their imports beyond static analysis. `build.PLUGIN_API_MODULES` is the
declaration that stands in for the missing import edge, and this keeps it
honest: every module in the plugin package is either reached by host code or
named there, and none may be quietly neither.
"""

import ast
from pathlib import Path

from build import PLUGIN_API_MODULES, spec_hiddenimports
from tests.repo_paths import REPO_ROOT

HOST_SOURCE = REPO_ROOT / "src"
PLUGIN_PACKAGE = HOST_SOURCE / "plugins"


def dotted_name(module: Path) -> str:
    """The importable name of a source file, e.g. `src.plugins.api`."""
    return ".".join(module.relative_to(REPO_ROOT).with_suffix("").parts)


def imported_names(module: Path) -> set[str]:
    """Every dotted name a source file imports.

    `from x.y import z` contributes both `x.y` and `x.y.z`, because that syntax
    cannot be told apart from an attribute import without resolving it. The
    extra name is harmless: these are only ever looked up, never trusted to be
    modules.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        # a relative import addresses the importing package, not this one
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_every_plugin_module_is_either_imported_by_nfoforge_or_declared() -> None:
    imported_by_host: set[str] = set()
    for source in HOST_SOURCE.rglob("*.py"):
        imported_by_host |= imported_names(source)

    undeclared = sorted(
        name
        for module in PLUGIN_PACKAGE.glob("*.py")
        if (name := dotted_name(module)) not in imported_by_host
        and name not in PLUGIN_API_MODULES
    )

    assert not undeclared, (
        "these modules in src/plugins are imported by no NfoForge code, so "
        "PyInstaller will not collect them and any plugin importing one will "
        "fail to load in a release build. Add them to build.PLUGIN_API_MODULES "
        f"if they exist for plugins, or remove them if they are dead: {undeclared}"
    )


def test_declared_modules_are_collected_without_the_standard_library() -> None:
    # the stdlib is opt-in per build, and the plugin API must not be gated on
    # that unrelated choice
    hiddenimports = spec_hiddenimports(include_std_lib=False)

    assert set(PLUGIN_API_MODULES) <= set(hiddenimports)
