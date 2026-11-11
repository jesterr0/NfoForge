"""A disc image (`.iso`): mounted to be read, uploaded as the one file it is."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import plistlib
import shutil
import subprocess
from typing import Any, cast

import pytest

from nfoforge.backend.rename_files import RenameExecutor
from nfoforge.backend.trackers.media_support import (
    TRACKER_SUPPORTED_IMAGES,
    supports_disc,
    unsupported_trackers,
)
from nfoforge.backend.trackers.passthepopcorn import PTPUploader
from nfoforge.core.disc import (
    DiscError,
    DiscType,
    Mount,
    MountRegistry,
    choose_playlist,
    detect as detect_module,
    detect_disc,
    disc_from_dict,
    disc_release,
    disc_to_dict,
    mount as mount_module,
)
from nfoforge.core.rename.movie import disc_rename_plan
from nfoforge.core.workflow.steps import collect_input
from nfoforge.enums.media_type import MediaType
from nfoforge.enums.tracker_selection import TrackerSelection
from nfoforge.payloads import media_inputs
from nfoforge.payloads.media_inputs import MediaInputPayload
from tests.disc_helpers import make_bluray

FEATURE = [("00001", 0, 7200)]


class FakeMounter:
    """Mounts an image at the next of `roots`, as a system would, and counts."""

    def __init__(self, *roots: Path, owned: bool = True) -> None:
        self.roots = list(roots)
        self.owned = owned
        self.attached: list[Path] = []
        self.detached: list[Path] = []

    def attach(self, image: Path) -> Mount:
        self.attached.append(image)
        root = self.roots[min(len(self.attached), len(self.roots)) - 1]
        return Mount(root=root, owned=self.owned)

    def detach(self, image: Path, mount: Mount) -> None:
        self.detached.append(image)


def _image(tmp_path: Path, name: str = "Movie.2020.1080p.Blu-ray.AVC-GRP.iso") -> Path:
    image = tmp_path / name
    image.write_bytes(b"\0" * 2048)
    return image


def _mounted_tree(path: Path) -> Path:
    return make_bluray(path, {"00800": FEATURE}, {"00001": 900})


@pytest.fixture
def registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[MountRegistry, FakeMounter]]:
    mounter = FakeMounter(_mounted_tree(tmp_path / "mnt" / "E"))
    found = MountRegistry(mounter)
    for module in (detect_module, media_inputs, mount_module):
        monkeypatch.setattr(module, "MOUNTS", found)
    yield found, mounter


# --------------------------------------------------------------------------
# the registry
# --------------------------------------------------------------------------
def test_an_image_is_mounted_once_and_unmounted_on_release(tmp_path: Path) -> None:
    image = _image(tmp_path)
    mounter = FakeMounter(tmp_path)
    mounts = MountRegistry(mounter)

    assert mounts.mount(image) == tmp_path
    assert mounts.mount(image) == tmp_path
    assert mounter.attached == [image]
    mounts.release(image)
    mounts.release(image)  # a second release is a no-op
    assert mounter.detached == [image]
    assert not mounts.is_mounted(image)


def test_an_image_mounted_by_someone_else_is_left_mounted(tmp_path: Path) -> None:
    image = _image(tmp_path)
    mounter = FakeMounter(tmp_path, owned=False)
    mounts = MountRegistry(mounter)

    mounts.mount(image)
    mounts.release_all()
    assert mounter.detached == []


def test_a_vanished_mount_is_mounted_again(tmp_path: Path) -> None:
    image = _image(tmp_path)
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    mounter = FakeMounter(first, second)
    mounts = MountRegistry(mounter)

    assert mounts.mount(image) == first
    first.rmdir()  # ejected by the user
    assert mounts.mount(image) == second


# --------------------------------------------------------------------------
# detection
# --------------------------------------------------------------------------
def test_an_iso_is_read_as_the_disc_inside_it(
    tmp_path: Path, registry: tuple[MountRegistry, FakeMounter]
) -> None:
    mounts, _ = registry
    image = _image(tmp_path)

    disc = detect_disc(image)

    assert disc is not None
    assert disc.disc_type is DiscType.BDMV
    assert disc.is_image and disc.image == image
    # named and sized by the file that gets uploaded, not the mount
    assert disc.label == "Movie.2020.1080p.Blu-ray.AVC-GRP"
    assert disc.size == 2048
    assert disc.root == tmp_path / "mnt" / "E"
    assert disc.has_certificate is True
    assert mounts.is_mounted(image)


def test_an_iso_with_no_disc_inside_is_refused_and_unmounted(tmp_path: Path) -> None:
    image = _image(tmp_path, "data.iso")
    empty = tmp_path / "empty"
    empty.mkdir()
    mounter = FakeMounter(empty)
    mounts = MountRegistry(mounter)

    with pytest.raises(DiscError, match="no BDMV or VIDEO_TS"):
        detect_disc(image, mounts=mounts)
    assert mounter.detached == [image]


def test_collect_input_takes_an_iso_as_a_disc(
    tmp_path: Path, registry: tuple[MountRegistry, FakeMounter]
) -> None:
    files, disc = collect_input(_image(tmp_path))

    assert disc is not None and disc.is_image
    assert files == [tmp_path / "mnt" / "E" / "BDMV" / "STREAM" / "00001.m2ts"]


# --------------------------------------------------------------------------
# the release
# --------------------------------------------------------------------------
def _payload(image: Path) -> MediaInputPayload:
    disc = detect_disc(image)
    assert disc is not None
    choose_playlist(disc)
    primary = disc.primary_media_file()
    assert primary is not None
    return MediaInputPayload(
        input_path=image,
        file_list=[primary],
        file_list_mediainfo={primary: cast(Any, object())},
        input_kind="file",
        content_size=disc.size,
        discs=[disc],
    )


def test_an_image_is_named_without_its_extension(
    tmp_path: Path, registry: tuple[MountRegistry, FakeMounter]
) -> None:
    payload = _payload(_image(tmp_path))
    assert payload.release_name() == "Movie.2020.1080p.Blu-ray.AVC-GRP"
    assert not payload.input_is_directory()


def test_an_image_mounted_somewhere_new_moves_every_path(
    tmp_path: Path, registry: tuple[MountRegistry, FakeMounter]
) -> None:
    mounts, mounter = registry
    image = _image(tmp_path)
    payload = _payload(image)
    disc = payload.discs[0]
    # a saved job resumed later, or an image let go for its rename
    moved = shutil.copytree(tmp_path / "mnt" / "E", tmp_path / "mnt" / "F")
    mounter.roots.append(moved)
    payload.unmount_disc_images()

    payload.require_existing_media_paths(include_comparison=False)

    clip = moved / "BDMV" / "STREAM" / "00001.m2ts"
    assert disc.root == moved
    assert payload.file_list == [clip]
    assert list(payload.file_list_mediainfo) == [clip]
    assert disc.playlists[0].path == moved / "BDMV" / "PLAYLIST" / "00800.mpls"
    assert disc.image == image
    assert mounts.is_mounted(image)


def test_a_reset_unmounts_the_image(
    tmp_path: Path, registry: tuple[MountRegistry, FakeMounter]
) -> None:
    mounts, mounter = registry
    image = _image(tmp_path)
    payload = _payload(image)

    payload.reset()

    assert mounter.detached == [image]
    assert not mounts.is_mounted(image)


def test_renaming_an_image_renames_the_file_and_keeps_iso(
    tmp_path: Path, registry: tuple[MountRegistry, FakeMounter]
) -> None:
    mounts, _ = registry
    image = _image(tmp_path, "old name.iso")
    payload = _payload(image)
    new_image = tmp_path / "Movie.2020.1080p.Blu-ray.AVC-GRP.iso"

    plan = disc_rename_plan(payload, new_image.stem)
    assert plan is not None
    assert plan.file_targets == {image: new_image}
    assert plan.directory_targets == {}
    payload.unmount_disc_images()
    result = RenameExecutor.execute(plan)
    assert result.success, result.message
    payload.apply_rename_mapping(result.path_mapping, result.updated_input_path)
    payload.require_existing_media_paths(include_comparison=False)

    assert new_image.is_file() and not image.exists()
    assert payload.input_path == new_image
    assert payload.discs[0].image == new_image
    assert mounts.is_mounted(new_image) and not mounts.is_mounted(image)
    assert payload.release_name() == new_image.stem


def test_an_image_survives_a_saved_job(
    tmp_path: Path, registry: tuple[MountRegistry, FakeMounter]
) -> None:
    image = _image(tmp_path)
    disc = detect_disc(image)
    assert disc is not None

    restored = disc_from_dict(disc_to_dict(disc))

    assert restored is not None
    assert restored.image == image
    assert restored.root == disc.root


# --------------------------------------------------------------------------
# trackers
# --------------------------------------------------------------------------
def test_only_trackers_that_take_an_iso_are_offered_one() -> None:
    assert TrackerSelection.PASS_THE_POPCORN in TRACKER_SUPPORTED_IMAGES
    assert supports_disc(TrackerSelection.PASS_THE_POPCORN, DiscType.BDMV, image=True)
    assert supports_disc(TrackerSelection.BEYOND_HD, DiscType.BDMV)
    assert not supports_disc(TrackerSelection.BEYOND_HD, DiscType.BDMV, image=True)

    reasons = unsupported_trackers(MediaType.MOVIE, DiscType.BDMV, image=True)
    assert TrackerSelection.PASS_THE_POPCORN not in reasons
    assert ".iso" in reasons[TrackerSelection.BEYOND_HD]
    # a tracker that takes no disc at all says that, not something about images
    assert "not been checked" in reasons[TrackerSelection.AITHER]
    assert "full Blu-ray" in reasons[TrackerSelection.ONLY_ENCODES]


def test_ptp_is_told_the_container_is_iso(
    tmp_path: Path, registry: tuple[MountRegistry, FakeMounter]
) -> None:
    disc = detect_disc(_image(tmp_path))
    assert disc is not None
    release = disc_release(disc, None)

    assert release.image
    container = PTPUploader._get_container(cast(Any, None), tmp_path, release)
    assert container == "ISO"


# --------------------------------------------------------------------------
# the system mounters, from what each tool prints
# --------------------------------------------------------------------------
def _completed(stdout: str = "", returncode: int = 0, stderr: str = "") -> Any:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_windows_reads_the_drive_letter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str]) -> Any:
        calls.append(command)
        return _completed("\r\nTrue|E\r\n")

    monkeypatch.setattr(mount_module, "_run", run)
    image = tmp_path / "it's.iso"

    mount = mount_module.WindowsMounter().attach(image)

    assert mount == Mount(root=Path("E:\\"), owned=True)
    # a quote in the path is doubled for PowerShell
    assert "it''s.iso" in calls[0][-1]
    assert "-Access ReadOnly" in calls[0][-1]


def test_windows_reports_why_a_mount_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        mount_module,
        "_run",
        lambda _command: _completed(returncode=1, stderr="The file is corrupt.\n"),
    )
    with pytest.raises(mount_module.MountError, match="corrupt"):
        mount_module.WindowsMounter().attach(tmp_path / "x.iso")


def test_mac_reads_the_mount_point_from_the_plist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = {
        "system-entities": [
            {"dev-entry": "/dev/disk4"},
            {"dev-entry": "/dev/disk4s1", "mount-point": "/Volumes/MOVIE"},
        ]
    }
    monkeypatch.setattr(
        mount_module,
        "_run",
        lambda _command: _completed(plistlib.dumps(document).decode("utf-8")),
    )

    mount = mount_module.MacMounter().attach(tmp_path / "x.iso")

    assert mount.root == Path("/Volumes/MOVIE")
    assert mount.handle == "/Volumes/MOVIE"


def test_linux_sets_up_a_loop_device_and_finds_its_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str]) -> Any:
        calls.append(command)
        if command[1] == "loop-setup":
            return _completed(f"Mapped file {tmp_path}/x.iso as /dev/loop7.\n")
        if command[0] == "findmnt":
            return _completed("/media/user/MOVIE\n")
        return _completed("Mounted /dev/loop7 at /media/user/MOVIE\n")

    monkeypatch.setattr(mount_module, "_run", run)

    mount = mount_module.LinuxMounter().attach(tmp_path / "x.iso")

    assert mount == Mount(
        root=Path("/media/user/MOVIE"), owned=True, handle="/dev/loop7"
    )
    assert "--read-only" in calls[0]
