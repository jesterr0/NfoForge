"""Coverage for how the application locates its own files.

Resolution must not consult the process working directory, and when frozen it
must ask PyInstaller where the bundle is rather than guessing from the
executable's location. The second point is not theoretical: a macOS `.app`
puts the executable in `Contents/MacOS` while collected data lands elsewhere
under `Contents/`, so an exe-relative path does not exist there at all.
"""

from pathlib import Path
import sys

import pytest

from nfoforge.backend.utils.working_dir import asset_root


def test_asset_root_comes_from_the_bundle_when_frozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Frozen builds read `sys._MEIPASS`, never a path built from `sys.executable`.

    The executable is deliberately pointed somewhere unrelated: if resolution
    reaches for it, the assertion fails rather than passing by coincidence on a
    platform where the two happen to coincide.
    """
    bundle = tmp_path / "bundle"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "elsewhere" / "NfoForge.exe"))

    assert asset_root() == bundle / "assets"


def test_asset_root_is_found_from_source_without_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running from source resolves against the project, not against `cwd`.

    The old behaviour built every runtime path from `Path.cwd()`, so launching
    from anywhere but the project root silently produced a tree of paths that
    did not exist.
    """
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    from_project_root = asset_root()

    monkeypatch.chdir(tmp_path)

    assert asset_root() == from_project_root
    assert from_project_root.name == "assets"
