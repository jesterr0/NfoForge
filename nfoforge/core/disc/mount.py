"""Mount a disc image read-only, and always unmount it again.

An `.iso` holds the same `BDMV` or `VIDEO_TS` tree as a disc folder, but
MediaInfo and ffmpeg can only read inside it once it is mounted. BDInfo reads
the image directly and the torrent is the image file itself, so a mount is only
needed while the disc is read: detection, MediaInfo and screenshots.

`MOUNTS` keeps one mount per image for as long as the process needs it and
unmounts every image it mounted when the process exits. An image someone else
already mounted is used where it is and never unmounted here.
"""

from __future__ import annotations

import atexit
from dataclasses import dataclass
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import threading
import time
from typing import Protocol

from nfoforge.backend.utils.subprocess_flags import get_subprocess_creation_flags
from nfoforge.core.disc.model import DiscError
from nfoforge.logger.nfo_forge_logger import LOG

#: A mount is a few seconds; a mounter still running after this is stuck.
_TIMEOUT_SECONDS = 120

DISC_IMAGE_SUFFIXES = frozenset({".iso"})


class MountError(DiscError):
    """A disc image could not be mounted."""


def is_disc_image(path: Path) -> bool:
    return path.suffix.casefold() in DISC_IMAGE_SUFFIXES and path.is_file()


@dataclass(frozen=True, slots=True)
class Mount:
    root: Path
    # False when the image was already mounted: it is left mounted afterwards
    owned: bool
    # what the mounter needs to unmount it: a device, or a mount point
    handle: str = ""


class ImageMounter(Protocol):
    def attach(self, image: Path) -> Mount: ...

    def detach(self, image: Path, mount: Mount) -> None: ...


class MountRegistry:
    """Each image mounted once, and unmounted when it is released."""

    def __init__(self, mounter: ImageMounter | None = None) -> None:
        self._mounter = mounter
        self._mounts: dict[str, Mount] = {}
        self._lock = threading.Lock()

    def mount(self, image: Path) -> Path:
        """Where `image` is mounted, mounting it first when it is not."""
        key = _key(image)
        with self._lock:
            found = self._mounts.get(key)
            if found is not None and found.root.is_dir():
                return found.root
            mount = self._get_mounter().attach(Path(os.path.abspath(image)))
            self._mounts[key] = mount
            return mount.root

    def release(self, image: Path) -> None:
        """Unmount `image` if it was mounted here; a failure is only logged."""
        with self._lock:
            mount = self._mounts.pop(_key(image), None)
        if mount is not None and mount.owned:
            try:
                self._get_mounter().detach(Path(os.path.abspath(image)), mount)
            except (MountError, OSError) as error:
                LOG.warning(
                    LOG.LOG_SOURCE.BE, f"Could not unmount {image.name}: {error}"
                )

    def release_all(self) -> None:
        with self._lock:
            images = list(self._mounts)
        for image in images:
            self.release(Path(image))

    def is_mounted(self, image: Path) -> bool:
        with self._lock:
            return _key(image) in self._mounts

    def _get_mounter(self) -> ImageMounter:
        if self._mounter is None:
            self._mounter = platform_mounter()
        return self._mounter


def _key(image: Path) -> str:
    return os.path.normcase(os.path.abspath(image))


def platform_mounter() -> ImageMounter:
    if sys.platform == "win32":
        return WindowsMounter()
    if sys.platform == "darwin":
        return MacMounter()
    return LinuxMounter()


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 - list argv, no shell; fixed system tools
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=_TIMEOUT_SECONDS,
            creationflags=get_subprocess_creation_flags(),
            check=False,
        )
    except FileNotFoundError as error:
        raise MountError(f"{command[0]} was not found: {error}") from error
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MountError(f"{command[0]} failed: {error}") from error


def _reason(result: subprocess.CompletedProcess[str]) -> str:
    lines = [line.strip() for line in (result.stderr or result.stdout).splitlines()]
    lines = [line for line in lines if line]
    return lines[0] if lines else f"exit code {result.returncode}"


class WindowsMounter:
    """`Mount-DiskImage -Access ReadOnly`, which needs no administrator rights."""

    _ATTACH = """
$ErrorActionPreference = 'Stop'
$path = '{path}'
$owned = $false
if (-not (Get-DiskImage -ImagePath $path).Attached) {{
    Mount-DiskImage -ImagePath $path -Access ReadOnly -StorageType ISO | Out-Null
    $owned = $true
}}
$letter = $null
for ($i = 0; $i -lt 50 -and -not $letter; $i++) {{
    $letter = (Get-DiskImage -ImagePath $path | Get-Volume -ErrorAction SilentlyContinue).DriveLetter
    if (-not $letter) {{ Start-Sleep -Milliseconds 200 }}
}}
if (-not $letter) {{
    if ($owned) {{ Dismount-DiskImage -ImagePath $path | Out-Null }}
    throw 'The image has no drive letter once mounted'
}}
Write-Output "$owned|$letter"
"""
    _DETACH = """
$ErrorActionPreference = 'Stop'
Dismount-DiskImage -ImagePath '{path}' | Out-Null
"""

    def attach(self, image: Path) -> Mount:
        result = self._powershell(self._ATTACH.format(path=_ps_quote(image)))
        lines = [line.strip() for line in result.stdout.splitlines() if "|" in line]
        if result.returncode != 0 or not lines:
            raise MountError(f"Could not mount {image.name}: {_reason(result)}")
        owned, letter = lines[-1].split("|", 1)
        return Mount(root=Path(f"{letter}:\\"), owned=owned.casefold() == "true")

    def detach(self, image: Path, mount: Mount) -> None:
        result = self._powershell(self._DETACH.format(path=_ps_quote(image)))
        if result.returncode != 0:
            raise MountError(_reason(result))

    @staticmethod
    def _powershell(script: str) -> subprocess.CompletedProcess[str]:
        return _run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script]
        )


def _ps_quote(path: Path) -> str:
    """`path` for a single-quoted PowerShell string."""
    return str(path).replace("'", "''")


class MacMounter:
    """`hdiutil attach -readonly -nobrowse`: mounted, but not shown in Finder."""

    def attach(self, image: Path) -> Mount:
        result = _run(
            ["hdiutil", "attach", "-readonly", "-nobrowse", "-plist", str(image)]
        )
        if result.returncode != 0:
            raise MountError(f"Could not mount {image.name}: {_reason(result)}")
        try:
            document = plistlib.loads(result.stdout.encode("utf-8"))
        except plistlib.InvalidFileException as error:
            raise MountError(f"hdiutil gave no mount point for {image.name}") from error
        for entity in document.get("system-entities", ()):
            point = entity.get("mount-point")
            if point:
                return Mount(root=Path(point), owned=True, handle=str(point))
        raise MountError(f"hdiutil gave no mount point for {image.name}")

    def detach(self, image: Path, mount: Mount) -> None:
        result = _run(["hdiutil", "detach", mount.handle or str(mount.root)])
        if result.returncode != 0:
            raise MountError(_reason(result))


_LOOP_DEVICE = re.compile(r"\bas (/dev/\S+?)\.?\s*$", re.MULTILINE)


class LinuxMounter:
    """udisks: a read-only loop device, mounted without root."""

    def attach(self, image: Path) -> Mount:
        result = _run(
            [
                "udisksctl",
                "loop-setup",
                "--read-only",
                "--no-user-interaction",
                "--file",
                str(image),
            ]
        )
        found = _LOOP_DEVICE.search(result.stdout)
        if result.returncode != 0 or found is None:
            raise MountError(f"Could not mount {image.name}: {_reason(result)}")
        device = found.group(1)
        # a desktop may mount the new device on its own; either way it is
        # mounted once this returns, and `findmnt` says where
        mounted = _run(
            ["udisksctl", "mount", "--no-user-interaction", "--block-device", device]
        )
        for _ in range(25):
            point = _run(["findmnt", "-n", "-o", "TARGET", "--source", device])
            target = point.stdout.strip().splitlines()
            if point.returncode == 0 and target:
                return Mount(root=Path(target[0]), owned=True, handle=device)
            time.sleep(0.2)
        self._delete_loop(device)
        raise MountError(f"Could not mount {image.name}: {_reason(mounted)}")

    def detach(self, image: Path, mount: Mount) -> None:
        _run(
            [
                "udisksctl",
                "unmount",
                "--no-user-interaction",
                "--block-device",
                mount.handle,
            ]
        )
        self._delete_loop(mount.handle)

    @staticmethod
    def _delete_loop(device: str) -> None:
        result = _run(
            [
                "udisksctl",
                "loop-delete",
                "--no-user-interaction",
                "--block-device",
                device,
            ]
        )
        if result.returncode != 0:
            raise MountError(_reason(result))


MOUNTS = MountRegistry()
atexit.register(MOUNTS.release_all)
