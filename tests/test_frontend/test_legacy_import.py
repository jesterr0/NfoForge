"""Importing a previous installation on demand, from Settings.

The same copying the first-launch migration does, offered again so that declining
it once is not a decision a user is stuck with.
"""

from pathlib import Path

import pytest

from src.config.layout_apply import MigrationError
from src.config.layout_migration import LegacyInstall
from src.config.paths import AppPaths
import src.frontend.windows.legacy_import as legacy_import
from src.frontend.windows.legacy_import import (
    LegacyImportWorker,
    choose_legacy_install,
)


def _install(tmp_path: Path, name: str = "previous install") -> LegacyInstall:
    root = tmp_path / name
    state = root / "bundle" / "runtime"
    (state / "config" / "user").mkdir(parents=True)
    return LegacyInstall(root=root, state=state, plugins=root / "plugins")


def _pick(monkeypatch: pytest.MonkeyPatch, answer: str) -> None:
    monkeypatch.setattr(
        legacy_import.QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *_args, **_kwargs: answer),
    )


def test_a_folder_holding_settings_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install = _install(tmp_path)
    _pick(monkeypatch, str(install.root))

    found = choose_legacy_install(None)

    assert found is not None
    assert found.root == install.root


def test_a_folder_holding_nothing_is_refused_and_explained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Picking the wrong folder is the easy mistake, so it gets an answer.

    People choose the nested data folder, or the folder above the one they
    extracted. Accepting either would import nothing and report success.
    """
    empty = tmp_path / "not an installation"
    empty.mkdir()
    _pick(monkeypatch, str(empty))
    told: list[str] = []
    monkeypatch.setattr(
        legacy_import.QMessageBox,
        "information",
        staticmethod(lambda *args, **_kwargs: told.append(str(args[-1]))),
    )

    assert choose_legacy_install(None) is None
    assert told and str(empty) in told[0]


def test_backing_out_of_the_picker_says_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling is not a mistake, so it is not worth a message."""
    _pick(monkeypatch, "")
    told: list[object] = []
    monkeypatch.setattr(
        legacy_import.QMessageBox,
        "information",
        staticmethod(lambda *args, **_kwargs: told.append(args)),
    )

    assert choose_legacy_install(None) is None
    assert told == []


def test_the_worker_reports_the_run_it_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`run()` is called directly: the threading is Qt's, the work is ours."""
    paths = AppPaths(state_root=tmp_path / "data", asset_root=tmp_path / "assets")
    legacy = _install(tmp_path)
    sentinel = object()
    monkeypatch.setattr(
        legacy_import, "import_legacy", lambda *_args, **_kwargs: sentinel
    )
    worker = LegacyImportWorker(paths, legacy)
    completed: list[object] = []
    worker.completed.connect(completed.append)

    worker.run()

    assert completed == [sentinel]


def test_a_failed_import_says_nothing_was_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reassurance is the useful part of the message.

    Nothing in the migration deletes, so a failed import leaves both the data
    directory and the installation it was reading intact. Someone watching an
    import fail needs to know that before they start trying to repair anything.
    """
    paths = AppPaths(state_root=tmp_path / "data", asset_root=tmp_path / "assets")

    def explode(*_args: object, **_kwargs: object) -> None:
        raise MigrationError("a copy arrived short")

    monkeypatch.setattr(legacy_import, "import_legacy", explode)
    worker = LegacyImportWorker(paths, _install(tmp_path))
    failures: list[str] = []
    worker.failed.connect(failures.append)

    worker.run()

    assert failures
    assert "nothing was deleted" in failures[0].lower()
    assert "a copy arrived short" in failures[0]
