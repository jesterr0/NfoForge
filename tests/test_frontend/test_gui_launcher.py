"""`nfoforge-gui` settles the data folder before the desktop app is imported."""

from pathlib import Path

import pytest

from nfoforge import launcher
from nfoforge.config.paths import default_paths
import nfoforge.frontend.app


def test_the_desktop_entry_chooses_the_data_dir_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The logger opens its file in the data folder as it is imported, so the
    folder has to be settled before the desktop app is."""
    seen: list[Path] = []
    monkeypatch.setattr("nfoforge.config.paths._chosen_data_dir", None)
    monkeypatch.setattr(launcher.sys, "argv", ["nfoforge", "--data-dir", str(tmp_path)])
    monkeypatch.setattr(
        nfoforge.frontend.app, "main", lambda: seen.append(default_paths().state_root)
    )

    launcher.gui()

    assert seen == [tmp_path.resolve()]
