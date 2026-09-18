"""The windows that ask what to export, and what an import would do.

`QDialog.exec` is refused by `conftest`, so anything that opens a modal is
driven by patching the statics it calls. What is being checked here is the
asking, not the copying: `tests/test_config/test_transfer.py` owns the rules.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox, QWidget
import pytest
import tomlkit

from src.config.config import ConfigManager
from src.config.transfer import (
    Disposition,
    EntryKind,
    NameConflict,
    export_bundle,
    read_bundle,
)
from src.frontend.windows.config_transfer import (
    ConfigExportDialog,
    ConfigImportDialog,
    TransferSummaryDialog,
    export_configuration,
    import_configuration,
)
from tests.repo_paths import build_app_paths


@pytest.fixture(autouse=True)
def _no_dependency_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )


def _manager(tmp_path: Path, name: str = "mysetup") -> ConfigManager:
    return ConfigManager(name, build_app_paths(tmp_path))


def _use_template(manager: ConfigManager, profile: str, stem: str) -> None:
    path = manager.paths.user_configs / f"{profile}.toml"
    document = tomlkit.parse(path.read_text(encoding="utf-8"))
    document["tracker"]["aither"]["nfo_template"] = stem  # type: ignore[index]
    path.write_text(tomlkit.dumps(document), encoding="utf-8")


def _template(manager: ConfigManager, stem: str, text: str = "hello") -> None:
    manager.paths.templates.mkdir(parents=True, exist_ok=True)
    (manager.paths.templates / f"{stem}.txt").write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# export dialog


def test_the_export_dialog_ticks_the_profile_in_use(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.save_as(manager.paths.user_configs / "other.toml")
    manager.program.current_config = "mysetup"

    dialog = ConfigExportDialog(manager.paths, "mysetup")

    assert dialog.profile_list.count() == 2
    assert dialog.selected_profiles() == ("mysetup",)


def test_the_template_list_follows_the_ticked_profiles(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _template(manager, "movie")
    _use_template(manager, "mysetup", "movie")

    dialog = ConfigExportDialog(manager.paths, None)
    assert dialog.template_list.count() == 0

    item = dialog.profile_list.item(0)
    assert item is not None
    item.setCheckState(Qt.CheckState.Checked)

    assert dialog.template_list.count() == 1
    assert dialog.template_list.item(0).text() == "movie"  # type: ignore[union-attr]


def test_a_template_that_is_gone_is_shown_as_missing(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _use_template(manager, "mysetup", "movie")

    dialog = ConfigExportDialog(manager.paths, "mysetup")

    assert dialog.template_list.item(0).text() == "movie (missing)"  # type: ignore[union-attr]


def test_credentials_are_not_included_unless_the_box_is_ticked(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    dialog = ConfigExportDialog(manager.paths, "mysetup")

    assert dialog.include_credentials.isChecked() is False
    assert "Credentials are removed" in dialog.warning.text()

    dialog.include_credentials.setChecked(True)
    assert "plain text" in dialog.warning.text()


def test_export_is_refused_until_a_profile_is_ticked(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    dialog = ConfigExportDialog(manager.paths, None)

    assert dialog.export_button.isEnabled() is False

    item = dialog.profile_list.item(0)
    assert item is not None
    item.setCheckState(Qt.CheckState.Checked)
    assert dialog.export_button.isEnabled() is True


# ---------------------------------------------------------------------------
# import dialog


def _bundle(tmp_path: Path) -> Path:
    source = _manager(tmp_path / "a")
    _template(source, "movie")
    _use_template(source, "mysetup", "movie")
    return export_bundle(source.paths, ["mysetup"], tmp_path / "bundle").archive


def test_the_import_dialog_shows_what_would_happen(tmp_path: Path) -> None:
    target = _manager(tmp_path / "b", "config")
    contents = read_bundle(_bundle(tmp_path))

    dialog = ConfigImportDialog(target.paths, contents)

    assert dialog.plan_tree.topLevelItemCount() == 2
    assert dialog.plan().for_kind(EntryKind.PROFILE)[0].disposition is Disposition.NEW
    assert "exported without credentials" in dialog.note.text()


def test_changing_the_conflict_policy_replans(tmp_path: Path) -> None:
    target = _manager(tmp_path / "b", "mysetup")
    contents = read_bundle(_bundle(tmp_path))

    dialog = ConfigImportDialog(target.paths, contents)
    assert dialog.plan().entries[0].destination_name == "mysetup (2)"

    index = dialog.policy_combo.findData(NameConflict.SKIP)
    dialog.policy_combo.setCurrentIndex(index)
    dialog.policy_combo.activated.emit(index)

    assert dialog.plan().entries[0].disposition is Disposition.SKIPPED
    assert dialog.plan_tree.topLevelItem(0).text(2) == "--"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# the two entry points


def test_export_writes_the_file_the_save_dialog_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    destination = tmp_path / "out" / "shared.zip"
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(destination), "")),
    )

    export_configuration(QWidget(), manager)

    assert destination.is_file()


def test_export_says_so_when_there_is_nothing_to_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    for profile in manager.paths.user_configs.glob("*.toml"):
        profile.unlink()
    seen: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda parent, title, text, *a, **k: seen.append(text)),
    )

    export_configuration(QWidget(), manager)

    assert seen and "no profiles to export" in seen[0]


def test_import_reports_a_file_that_is_not_a_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    junk = tmp_path / "junk.zip"
    junk.write_text("not a zip", encoding="utf-8")
    seen: list[str] = []
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(junk), "")),
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda parent, title, text, *a, **k: seen.append(text)),
    )

    assert import_configuration(QWidget(), manager) is False
    assert seen and "not a readable zip" in seen[0]


def test_import_writes_the_bundle_and_reports_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _bundle(tmp_path)
    target = _manager(tmp_path / "b", "config")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(bundle), "")),
    )
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)

    assert import_configuration(QWidget(), target) is True
    assert (target.paths.user_configs / "mysetup.toml").is_file()
    assert (target.paths.templates / "movie.txt").is_file()


def test_cancelling_the_import_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _bundle(tmp_path)
    target = _manager(tmp_path / "b", "config")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(bundle), "")),
    )
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Rejected)

    assert import_configuration(QWidget(), target) is False
    assert not (target.paths.user_configs / "mysetup.toml").exists()


def test_the_summary_window_shows_the_text_it_was_given(tmp_path: Path) -> None:
    dialog = TransferSummaryDialog("Title", "Intro", "Body text", tmp_path)
    assert dialog.detail_view.toPlainText() == "Body text"
