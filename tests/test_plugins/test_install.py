"""Installing a plugin from a folder or an archive.

The checks worth locking down are the ones whose absence is only discovered on
the next launch: a manifest that does not describe a plugin, an id something
else already declares, and a module the loader will not find. Plus the two that
matter because an archive came from someone else -- nothing escapes the
destination, and nothing is imported on the way in.
"""

from pathlib import Path
import sys
import zipfile

import pytest

from src.plugins.install import (
    ARCHIVE_DIR_NAME,
    PluginInstallError,
    extracted_archive,
    inspect_folder,
    install,
    resolve_conflict,
)
from src.plugins.loader import PluginLoader
from src.plugins.manager import PluginManager
from tests.repo_paths import build_app_paths

MANIFEST = """\
schema_version = 1
id = "example.my-plugin"
module = "plugin_my_plugin"
"""


def _plugin(root: Path, manifest: str = MANIFEST, module: str = "plugin_my_plugin"):
    root.mkdir(parents=True, exist_ok=True)
    (root / "nfoforge-plugin.toml").write_text(manifest, encoding="utf-8")
    package = root / module
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("plugin = object()\n", encoding="utf-8")
    return root


def _archive(source: Path, destination: Path, prefix: str = "") -> Path:
    with zipfile.ZipFile(destination, "w") as opened:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                arcname = str(Path(prefix) / path.relative_to(source)).replace(
                    "\\", "/"
                )
                opened.write(path, arcname)
    return destination


# ---------------------------------------------------------------------------
# finding the plugin


def test_a_plugin_folder_is_described_from_its_manifest(tmp_path: Path) -> None:
    candidate = inspect_folder(_plugin(tmp_path / "my-plugin"))

    assert candidate.plugin_id == "example.my-plugin"
    assert candidate.module == "plugin_my_plugin"
    assert candidate.object_name == "plugin"
    assert candidate.directory_name == "my-plugin"


def test_a_folder_holding_the_plugin_folder_is_accepted(tmp_path: Path) -> None:
    """The shape a downloaded repository unpacks into."""
    wrapper = tmp_path / "downloads"
    _plugin(wrapper / "my-plugin-main")

    candidate = inspect_folder(wrapper)

    assert candidate.plugin_id == "example.my-plugin"
    assert candidate.directory_name == "my-plugin-main"


def test_a_folder_holding_several_plugins_is_refused(tmp_path: Path) -> None:
    wrapper = tmp_path / "plugins"
    _plugin(wrapper / "one")
    _plugin(
        wrapper / "two",
        MANIFEST.replace("example.my-plugin", "example.other").replace(
            "plugin_my_plugin", "plugin_other"
        ),
        "plugin_other",
    )

    with pytest.raises(PluginInstallError, match="more than one plugin"):
        inspect_folder(wrapper)


def test_a_folder_with_no_manifest_is_refused(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(PluginInstallError, match="nfoforge-plugin.toml"):
        inspect_folder(tmp_path / "empty")


@pytest.mark.parametrize(
    "manifest",
    (
        'schema_version = 2\nid = "a.b"\nmodule = "m"\n',
        'schema_version = 1\nid = ""\nmodule = "m"\n',
        'schema_version = 1\nid = "a.b"\nmodule = ""\n',
        'schema_version = 1\nid = "a.b"\nmodule = "not an identifier"\n',
        'schema_version = 1\nid = "a.b"\nmodule = "m"\nobject = "1nope"\n',
        "this is not toml",
    ),
)
def test_a_manifest_the_loader_would_reject_is_refused(
    tmp_path: Path, manifest: str
) -> None:
    root = tmp_path / "my-plugin"
    root.mkdir()
    (root / "nfoforge-plugin.toml").write_text(manifest, encoding="utf-8")

    with pytest.raises(PluginInstallError):
        inspect_folder(root)


def test_an_id_the_registry_would_reject_is_refused(tmp_path: Path) -> None:
    """Checked here so it is not first reported on the next launch."""
    root = _plugin(
        tmp_path / "my-plugin", MANIFEST.replace("example.my-plugin", "Example Plugin")
    )
    with pytest.raises(PluginInstallError, match="lowercase"):
        inspect_folder(root)


def test_a_module_that_is_not_in_the_folder_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "my-plugin"
    root.mkdir()
    (root / "nfoforge-plugin.toml").write_text(MANIFEST, encoding="utf-8")

    with pytest.raises(PluginInstallError, match="not in the folder"):
        inspect_folder(root)


def test_a_single_module_file_is_accepted(tmp_path: Path) -> None:
    root = tmp_path / "my-plugin"
    root.mkdir()
    (root / "nfoforge-plugin.toml").write_text(MANIFEST, encoding="utf-8")
    (root / "plugin_my_plugin.py").write_text("plugin = object()\n", encoding="utf-8")

    assert inspect_folder(root).module == "plugin_my_plugin"


# ---------------------------------------------------------------------------
# archives


def test_a_plugin_is_found_inside_an_archive(tmp_path: Path) -> None:
    source = _plugin(tmp_path / "my-plugin")
    archive = _archive(source, tmp_path / "plugin.zip")

    with extracted_archive(archive) as candidate:
        assert candidate.plugin_id == "example.my-plugin"
        # Nothing to take a repository name from, so the id names the folder.
        assert candidate.directory_name == "example.my-plugin"


def test_an_archive_with_a_single_wrapper_folder_keeps_that_name(
    tmp_path: Path,
) -> None:
    source = _plugin(tmp_path / "my-plugin")
    archive = _archive(source, tmp_path / "plugin.zip", prefix="my-plugin-main")

    with extracted_archive(archive) as candidate:
        assert candidate.directory_name == "my-plugin-main"


def test_an_archive_entry_that_escapes_the_destination_is_refused(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as opened:
        opened.writestr("../evil.py", "import os")

    with pytest.raises(PluginInstallError, match="points outside"):
        with extracted_archive(archive):
            pass
    assert not (tmp_path / "evil.py").exists()


def test_an_empty_archive_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive, "w"):
        pass

    with pytest.raises(PluginInstallError, match="empty"):
        with extracted_archive(archive):
            pass


def test_something_that_is_not_a_zip_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "not.zip"
    archive.write_text("hello", encoding="utf-8")

    with pytest.raises(PluginInstallError, match="not a readable zip"):
        with extracted_archive(archive):
            pass


def test_the_temporary_tree_is_gone_afterwards(tmp_path: Path) -> None:
    source = _plugin(tmp_path / "my-plugin")
    archive = _archive(source, tmp_path / "plugin.zip")

    with extracted_archive(archive) as candidate:
        workspace = candidate.root
        assert workspace.is_dir()
    assert not workspace.exists()


# ---------------------------------------------------------------------------
# installing


def test_installing_copies_the_plugin_into_the_data_folder(tmp_path: Path) -> None:
    paths = build_app_paths(tmp_path / "data")
    source = _plugin(tmp_path / "my-plugin")

    outcome = install(inspect_folder(source), paths)

    assert outcome.destination == paths.plugins / "my-plugin"
    assert outcome.replaced is None
    assert (outcome.destination / "nfoforge-plugin.toml").is_file()
    assert (outcome.destination / "plugin_my_plugin" / "__init__.py").is_file()


def test_development_clutter_is_left_behind(tmp_path: Path) -> None:
    paths = build_app_paths(tmp_path / "data")
    source = _plugin(tmp_path / "my-plugin")
    (source / ".venv" / "Lib").mkdir(parents=True)
    (source / ".venv" / "pyvenv.cfg").write_text("home = x", encoding="utf-8")
    (source / ".git").mkdir()
    (source / ".git" / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
    (source / "plugin_my_plugin" / "__pycache__").mkdir()
    (source / "plugin_my_plugin" / "example.pyc").write_text("x", encoding="utf-8")
    (source / "tests").mkdir()
    (source / "tests" / "test_example.py").write_text("", encoding="utf-8")

    destination = install(inspect_folder(source), paths).destination

    assert not (destination / ".venv").exists()
    assert not (destination / ".git").exists()
    assert not (destination / "plugin_my_plugin" / "__pycache__").exists()
    assert not (destination / "plugin_my_plugin" / "example.pyc").exists()
    # Tests and docs are part of the plugin, not clutter.
    assert (destination / "tests" / "test_example.py").is_file()


def test_an_id_already_installed_is_an_update(tmp_path: Path) -> None:
    """The ordinary case: v1 is here, v2 arrives. Refusing it would leave
    deleting the folder by hand as the only route."""
    paths = build_app_paths(tmp_path / "data")
    source = _plugin(tmp_path / "my-plugin")
    install(inspect_folder(source), paths)
    (source / "plugin_my_plugin" / "__init__.py").write_text(
        "plugin = 'v2'", encoding="utf-8"
    )

    outcome = install(inspect_folder(source), paths)

    assert outcome.destination == paths.plugins / "my-plugin"
    assert (outcome.destination / "plugin_my_plugin" / "__init__.py").read_text(
        encoding="utf-8"
    ) == "plugin = 'v2'"


def test_an_id_that_ships_with_nfoforge_is_refused(tmp_path: Path) -> None:
    paths = build_app_paths(tmp_path / "data")
    _plugin(paths.plugin_examples / "shipped")
    source = _plugin(tmp_path / "my-plugin")

    with pytest.raises(PluginInstallError, match="ships with NfoForge"):
        resolve_conflict(inspect_folder(source), paths)


def test_a_folder_name_already_in_use_is_suffixed(tmp_path: Path) -> None:
    """The id is what has to be unique; the folder name is incidental."""
    paths = build_app_paths(tmp_path / "data")
    install(inspect_folder(_plugin(tmp_path / "a" / "my-plugin")), paths)
    other = _plugin(
        tmp_path / "b" / "my-plugin",
        MANIFEST.replace("example.my-plugin", "example.other").replace(
            "plugin_my_plugin", "plugin_other"
        ),
        "plugin_other",
    )

    destination = install(inspect_folder(other), paths).destination

    assert destination == paths.plugins / "my-plugin (2)"


def test_nothing_is_imported_while_installing(tmp_path: Path) -> None:
    """Validation is manifest-only: a restart is required regardless, and a
    dialog must not be able to run code the user has not accepted yet."""
    paths = build_app_paths(tmp_path / "data")
    source = _plugin(tmp_path / "my-plugin")
    (source / "plugin_my_plugin" / "__init__.py").write_text(
        "raise RuntimeError('this plugin must not be imported')\n", encoding="utf-8"
    )
    before = set(sys.modules)

    install(inspect_folder(source), paths)

    assert set(sys.modules) - before == set()


def test_a_module_name_already_in_use_is_refused(tmp_path: Path) -> None:
    """The loader resolves a module by name and refuses a second one from a
    different location, so this installs cleanly and then fails to load."""
    paths = build_app_paths(tmp_path / "data")
    install(inspect_folder(_plugin(tmp_path / "a" / "my-plugin")), paths)
    other = _plugin(
        tmp_path / "b" / "other-plugin",
        MANIFEST.replace("example.my-plugin", "example.other"),
    )

    with pytest.raises(PluginInstallError, match="module 'plugin_my_plugin'"):
        install(inspect_folder(other), paths)


def test_a_module_shared_with_a_shipped_example_is_refused(tmp_path: Path) -> None:
    paths = build_app_paths(tmp_path / "data")
    _plugin(paths.plugin_examples / "shipped")
    other = _plugin(
        tmp_path / "my-plugin", MANIFEST.replace("example.my-plugin", "example.other")
    )

    with pytest.raises(PluginInstallError, match="ships with NfoForge"):
        resolve_conflict(inspect_folder(other), paths)


def test_a_neighbour_with_an_unreadable_manifest_does_not_block_an_install(
    tmp_path: Path,
) -> None:
    """A broken plugin claims no id, so it cannot collide with one."""
    paths = build_app_paths(tmp_path / "data")
    broken = paths.plugins / "broken"
    broken.mkdir(parents=True)
    (broken / "nfoforge-plugin.toml").write_text("not toml", encoding="utf-8")

    outcome = install(inspect_folder(_plugin(tmp_path / "my-plugin")), paths)

    assert outcome.destination.is_dir()


def test_an_update_keeps_the_copy_it_replaced(tmp_path: Path) -> None:
    """Moved aside, never written over: a plugin repository can hold work the
    user did in place, and an update may turn out worse than what it replaced."""
    paths = build_app_paths(tmp_path / "data")
    source = _plugin(tmp_path / "my-plugin")
    (source / "notes.txt").write_text("version one", encoding="utf-8")
    install(inspect_folder(source), paths)
    (source / "notes.txt").write_text("version two", encoding="utf-8")

    outcome = install(inspect_folder(source), paths)

    assert outcome.replaced is not None
    assert outcome.replaced.parent.name == ARCHIVE_DIR_NAME
    assert (outcome.replaced / "notes.txt").read_text(encoding="utf-8") == "version one"
    assert (outcome.destination / "notes.txt").read_text(
        encoding="utf-8"
    ) == "version two"


def test_an_update_keeps_the_folder_name_rather_than_suffixing_it(
    tmp_path: Path,
) -> None:
    """The old copy has moved out of the way, so the natural name is free."""
    paths = build_app_paths(tmp_path / "data")
    source = _plugin(tmp_path / "my-plugin")
    install(inspect_folder(source), paths)

    outcome = install(inspect_folder(source), paths)

    assert outcome.destination == paths.plugins / "my-plugin"
    assert not (paths.plugins / "my-plugin (2)").exists()


LOADABLE_MODULE = """\
from src.plugins.api import PluginDefinition, TokenReplaceRequest


def _replace(request: TokenReplaceRequest) -> str:
    return request.text


plugin = PluginDefinition(
    display_name="My Plugin", version="1.0.0", token_replacer=_replace
)
"""


def test_the_loader_sees_only_the_new_copy_after_an_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Archived copies live one level too deep for the loader to find, which is
    what makes keeping them inside `plugins/` safe.

    Uses a module that really exports a `PluginDefinition`, because the point
    is that the loader gets all the way to a successful registration -- a stub
    would fail for its own reasons and prove nothing about where the archive
    went. The module name is unique to this test, the convention in
    `test_loader.py`, because a real import stays in `sys.modules` and would
    otherwise resolve another test's plugin to this one's directory.
    """
    module = "nfoforge_test_update_module"
    paths = build_app_paths(tmp_path / "data")
    source = _plugin(
        tmp_path / "my-plugin",
        MANIFEST.replace("plugin_my_plugin", module),
        module,
    )
    (source / module / "__init__.py").write_text(LOADABLE_MODULE, encoding="utf-8")
    install(inspect_folder(source), paths)
    install(inspect_folder(source), paths)
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))

    report = PluginLoader(
        PluginManager(), plugin_dir=paths.plugins, shipped_dir=paths.plugin_examples
    ).load_plugins()

    assert [record.plugin_id for record in report.loaded] == ["example.my-plugin"]
    assert report.failures == ()


def test_a_shipped_example_is_never_treated_as_an_update(tmp_path: Path) -> None:
    """A release's example cannot be replaced -- the user's copy would register
    first and the example would be reported broken on every launch."""
    paths = build_app_paths(tmp_path / "data")
    _plugin(paths.plugin_examples / "shipped")

    with pytest.raises(PluginInstallError, match="ships with NfoForge"):
        resolve_conflict(inspect_folder(_plugin(tmp_path / "my-plugin")), paths)


def test_resolve_conflict_reports_nothing_to_replace_for_a_fresh_install(
    tmp_path: Path,
) -> None:
    paths = build_app_paths(tmp_path / "data")
    assert (
        resolve_conflict(inspect_folder(_plugin(tmp_path / "my-plugin")), paths) is None
    )
