from pathlib import Path
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
import pytest

from nfoforge.config.paths import default_paths, use_data_dir
from nfoforge.frontend.windows import data_location


@pytest.mark.parametrize("change", ["change_data_folder", "change_plugins_folder"])
def test_launch_override_refuses_relocation_before_copying(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    monkeypatch.setattr("nfoforge.config.paths._chosen_data_dir", None)
    use_data_dir(tmp_path / "isolated")
    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda parent, title, text: messages.append(text)
    )
    monkeypatch.setattr(
        data_location.QFileDialog,
        "getExistingDirectory",
        lambda *args: pytest.fail("An overridden launch must not offer relocation"),
    )

    getattr(data_location, change)(QWidget(), default_paths(), MagicMock())

    assert len(messages) == 1
    assert "Restart without" in messages[0]
    assert not (tmp_path / "isolated").exists()
