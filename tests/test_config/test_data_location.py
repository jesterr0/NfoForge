"""Moving the data folder and the plugins folder somewhere the user chooses.

Everything here works on trees under `tmp_path`. The checks run before anything
is copied, and the copy never removes the source, so the interesting failures
are the ones that would let data land somewhere it should not -- or arrive
with settings still pointing back at the folder it came from.
"""

from pathlib import Path

import pytest

from nfoforge.backend.utils.working_dir import asset_root
from nfoforge.config.data_location import (
    DataDestination,
    RelocationError,
    check_data_destination,
    check_plugins_destination,
    copy_data,
    repoint_settings,
)
from nfoforge.config.layout_version import LAYOUT_RECORD_NAME
from nfoforge.config.paths import LOCATION_FILE_NAME, AppPaths


def _paths(tmp_path: Path) -> AppPaths:
    state = tmp_path / "current"
    state.mkdir()
    return AppPaths(state_root=state, asset_root=tmp_path / "assets")


def _data_folder(root: Path) -> Path:
    """A data folder holding one profile that names paths inside itself."""
    profiles = root / "config" / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "main.toml").write_text(
        "# the user's own comment\n"
        "[general]\n"
        f"working_dir = '{root / 'workspace'}'\n"
        "ui_suffix = 'workspace'\n"
        "\n"
        "[dependencies]\n"
        f"ffmpeg = '{root / 'tools' / 'ffmpeg' / 'ffmpeg.exe'}'\n"
        "mkbrr = 'C:/Elsewhere/mkbrr.exe'\n"
        "\n"
        "[trackers.mtv]\n"
        f"extra = ['{root / 'templates' / 'a.txt'}', 'plain']\n",
        encoding="utf-8",
    )
    (root / "config" / "program.toml").write_text(
        f"last_dir = '{root / 'workspace' / 'jobs'}'\n", encoding="utf-8"
    )
    (root / LAYOUT_RECORD_NAME).write_text("{}", encoding="utf-8")
    (root / "workspace" / "jobs" / "job-1").mkdir(parents=True)
    (root / "workspace" / "jobs" / "job-1" / "job.json").write_text("{}")
    (root / "workspace" / "processing" / "run").mkdir(parents=True)
    (root / "workspace" / "processing" / "run" / "big.png").write_bytes(b"x")
    (root / LOCATION_FILE_NAME).write_text("data_dir = 'x'", encoding="utf-8")
    return root


def test_an_empty_folder_is_offered_a_copy(tmp_path: Path) -> None:
    destination = tmp_path / "new"
    destination.mkdir()

    kind = check_data_destination(_paths(tmp_path), destination)

    assert kind is DataDestination.EMPTY


def test_an_existing_data_folder_is_used_as_it_is(tmp_path: Path) -> None:
    """Pointing a second machine, or a reinstall, at data already there."""
    destination = tmp_path / "new"
    destination.mkdir()
    (destination / LAYOUT_RECORD_NAME).write_text("{}", encoding="utf-8")

    kind = check_data_destination(_paths(tmp_path), destination)

    assert kind is DataDestination.EXISTING_DATA


def test_a_folder_holding_other_files_is_refused(tmp_path: Path) -> None:
    """The migration moves folders it recognises by name at the data root.

    A `jobs` folder in someone's documents would be moved into the workspace
    the first time NfoForge started there.
    """
    destination = tmp_path / "documents"
    (destination / "jobs").mkdir(parents=True)

    with pytest.raises(RelocationError, match="already holds other files"):
        check_data_destination(_paths(tmp_path), destination)


@pytest.mark.parametrize("nested", ["inside", "outside"])
def test_the_data_folder_cannot_nest_with_itself(tmp_path: Path, nested: str) -> None:
    """Copying a folder into itself never finishes; into its parent, it merges."""
    paths = _paths(tmp_path)
    destination = paths.state_root / "sub" if nested == "inside" else tmp_path
    destination.mkdir(exist_ok=True)

    with pytest.raises(RelocationError, match="inside itself"):
        check_data_destination(paths, destination)


def test_the_installation_is_refused(tmp_path: Path) -> None:
    """User data left the installation so a release can be replaced; not back."""
    paths = _paths(tmp_path)
    destination = asset_root().parent / "data_here"

    with pytest.raises(RelocationError, match="installation"):
        check_data_destination(paths, destination)
    with pytest.raises(RelocationError, match="installation"):
        check_plugins_destination(paths, destination)


def test_a_plugins_folder_may_already_hold_files(tmp_path: Path) -> None:
    """A folder of plugin checkouts is what a plugin author points at."""
    destination = tmp_path / "checkouts"
    (destination / "some_plugin").mkdir(parents=True)

    check_plugins_destination(_paths(tmp_path), destination)


def test_the_plugins_folder_cannot_be_the_data_folder(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    with pytest.raises(RelocationError, match="data folder itself"):
        check_plugins_destination(paths, paths.state_root)


def test_copying_keeps_saved_work_and_leaves_run_output(tmp_path: Path) -> None:
    source = _data_folder(tmp_path / "old")
    destination = tmp_path / "new"
    destination.mkdir()

    copy_data(source, destination)

    assert (destination / "workspace" / "jobs" / "job-1" / "job.json").is_file()
    assert (destination / LAYOUT_RECORD_NAME).is_file()
    assert not (destination / "workspace" / "processing").exists()
    assert not (destination / LOCATION_FILE_NAME).exists()
    # copied, never moved: the running process still uses the source
    assert (source / "workspace" / "processing" / "run" / "big.png").is_file()


def test_copied_settings_point_at_the_new_folder(tmp_path: Path) -> None:
    """Profiles store the working directory and tools by absolute path.

    Left alone, the copy would keep using the old folder's saved jobs and tools
    until that folder was removed, and then fail.
    """
    source = _data_folder(tmp_path / "old")
    destination = tmp_path / "new"
    destination.mkdir()

    copy_data(source, destination)

    profile = (destination / "config" / "profiles" / "main.toml").read_text(
        encoding="utf-8"
    )
    program = (destination / "config" / "program.toml").read_text(encoding="utf-8")
    assert str(source) not in profile
    assert str(destination / "workspace") in profile
    assert str(destination / "tools" / "ffmpeg" / "ffmpeg.exe") in profile
    assert str(destination / "templates" / "a.txt") in profile
    assert str(destination / "workspace" / "jobs") in program


def test_repointing_changes_nothing_but_the_old_folder(tmp_path: Path) -> None:
    """The user's file, byte for byte, with only the old folder swapped out.

    Comments, quoting and every value not naming the old folder survive -- a
    string that merely reads like a folder name, a path somewhere else, and
    plain strings in arrays among them.
    """
    source = _data_folder(tmp_path / "old")
    original = (source / "config" / "profiles" / "main.toml").read_text(
        encoding="utf-8"
    )
    destination = tmp_path / "new"
    destination.mkdir()

    copy_data(source, destination)

    after = (destination / "config" / "profiles" / "main.toml").read_text(
        encoding="utf-8"
    )
    assert after == original.replace(str(source), str(destination))
    assert "ui_suffix = 'workspace'" in after
    assert "C:/Elsewhere/mkbrr.exe" in after


def test_settings_naming_no_old_path_are_not_rewritten(tmp_path: Path) -> None:
    """A file with nothing to change is not written at all."""
    source = _data_folder(tmp_path / "old")

    assert repoint_settings(source, old_root=tmp_path / "unrelated") == []


def test_an_unreadable_profile_stops_the_move(tmp_path: Path) -> None:
    """Better to stay put than arrive with a profile still naming the old folder."""
    root = tmp_path / "data"
    (root / "config" / "profiles").mkdir(parents=True)
    (root / "config" / "profiles" / "broken.toml").write_text("[unclosed")

    with pytest.raises(RelocationError, match="broken.toml"):
        repoint_settings(root, old_root=tmp_path / "old")
