"""Asking before a plugin is installed, and not installing when told not to."""

from pathlib import Path

from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox, QWidget
import pytest

from src.frontend.windows.plugin_install import (
    PluginTrustDialog,
    install_from_archive,
    install_from_folder,
)
from src.plugins.install import inspect_folder
from tests.repo_paths import build_app_paths

MANIFEST = """\
schema_version = 1
id = "example.my-plugin"
module = "plugin_my_plugin"
"""


def _plugin(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "nfoforge-plugin.toml").write_text(MANIFEST, encoding="utf-8")
    package = root / "plugin_my_plugin"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("plugin = object()\n", encoding="utf-8")
    return root


def _silence_message_boxes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    for name in ("information", "critical", "warning"):
        monkeypatch.setattr(
            QMessageBox,
            name,
            staticmethod(lambda parent, title, text, *a, **k: seen.append(text)),
        )
    return seen


def test_the_trust_dialog_names_what_is_being_installed(tmp_path: Path) -> None:
    source = _plugin(tmp_path / "my-plugin")
    candidate = inspect_folder(source)

    dialog = PluginTrustDialog(candidate, source)

    assert dialog.candidate.plugin_id == "example.my-plugin"
    # Declining is the default answer; nothing is lost by it.
    assert dialog.cancel_button.isDefault() is True
    assert dialog.install_button.isDefault() is False


def test_declining_installs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = build_app_paths(tmp_path / "data")
    source = _plugin(tmp_path / "my-plugin")
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(source)),
    )
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    _silence_message_boxes(monkeypatch)

    assert install_from_folder(QWidget(), paths) is None
    assert not (paths.plugins / "my-plugin").exists()


def test_accepting_installs_from_a_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = build_app_paths(tmp_path / "data")
    source = _plugin(tmp_path / "my-plugin")
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(source)),
    )
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    seen = _silence_message_boxes(monkeypatch)

    destination = install_from_folder(QWidget(), paths)

    assert destination == paths.plugins / "my-plugin"
    assert (destination / "nfoforge-plugin.toml").is_file()
    assert seen and "restarted" in seen[0]


def test_accepting_installs_from_an_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zipfile

    source = _plugin(tmp_path / "my-plugin")
    archive = tmp_path / "plugin.zip"
    with zipfile.ZipFile(archive, "w") as opened:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                opened.write(
                    path,
                    str(Path("my-plugin") / path.relative_to(source)).replace(
                        "\\", "/"
                    ),
                )

    paths = build_app_paths(tmp_path / "data")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(archive), "")),
    )
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    _silence_message_boxes(monkeypatch)

    destination = install_from_archive(QWidget(), paths)

    assert destination == paths.plugins / "my-plugin"


def test_an_unresolvable_clash_is_reported_before_anything_is_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refused up front, so the user is not asked to trust something that could
    not be loaded even if they said yes.

    A shared *module* name, not a shared id: a shared id is an update and is
    offered rather than refused. Nothing can be done about this one, because
    the loader resolves a module by name and would reject whichever came
    second.
    """
    paths = build_app_paths(tmp_path / "data")
    _plugin(paths.plugins / "already-here")
    source = _plugin(tmp_path / "my-plugin")
    (source / "nfoforge-plugin.toml").write_text(
        MANIFEST.replace("example.my-plugin", "example.other"), encoding="utf-8"
    )

    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(source)),
    )

    def refuse_dialog(self: object) -> int:
        raise AssertionError("the trust dialog should not have been shown")

    monkeypatch.setattr(QDialog, "exec", refuse_dialog)
    seen = _silence_message_boxes(monkeypatch)

    assert install_from_folder(QWidget(), paths) is None
    assert seen and "module 'plugin_my_plugin'" in seen[0]


def test_choosing_nothing_does_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = build_app_paths(tmp_path / "data")
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: "")
    )
    assert install_from_folder(QWidget(), paths) is None


def test_the_trust_dialog_asks_to_update_when_something_is_being_replaced(
    tmp_path: Path,
) -> None:
    source = _plugin(tmp_path / "my-plugin")
    candidate = inspect_folder(source)
    existing = tmp_path / "installed" / "my-plugin"

    dialog = PluginTrustDialog(candidate, source, existing)

    assert dialog.windowTitle() == "Update plugin"
    assert dialog.install_button.text() == "Update"
    assert dialog.replaces == existing
    # Declining stays the default answer even when updating.
    assert dialog.cancel_button.isDefault() is True


def test_updating_reports_where_the_previous_copy_was_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = build_app_paths(tmp_path / "data")
    source = _plugin(tmp_path / "my-plugin")
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(source)),
    )
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    seen = _silence_message_boxes(monkeypatch)

    install_from_folder(QWidget(), paths)
    install_from_folder(QWidget(), paths)

    assert len(seen) == 2
    assert "installed to" in seen[0]
    assert "updated at" in seen[1]
    assert "was kept at" in seen[1]


def test_declining_an_update_leaves_the_installed_copy_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = build_app_paths(tmp_path / "data")
    source = _plugin(tmp_path / "my-plugin")
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(source)),
    )
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    _silence_message_boxes(monkeypatch)
    install_from_folder(QWidget(), paths)
    (source / "marker.txt").write_text("second", encoding="utf-8")

    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    assert install_from_folder(QWidget(), paths) is None

    assert not (paths.plugins / "my-plugin" / "marker.txt").exists()
    assert not (paths.plugins / "old_plugins").exists()
