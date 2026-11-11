"""Run a BDInfo scanner over one playlist of a Blu-ray.

The scanner is an external program the user points NfoForge at. It sits behind
`BDInfoScanner` so another one can be added without touching its callers.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import re
import subprocess
import threading
from typing import Protocol

from nfoforge.backend.utils.subprocess_flags import get_subprocess_creation_flags
from nfoforge.core.disc.bdinfo_report import (
    BDInfoReport,
    BDInfoReportError,
    parse_bdinfo_report,
)
from nfoforge.core.disc.model import Disc, DiscError

#: A 4K disc on a slow drive is the slow case; a run past this is stuck.
DEFAULT_TIMEOUT_SECONDS = 60 * 60

ProgressCallback = Callable[[float], None]
"""Called with the scan's progress, 0 to 100."""


class BDInfoError(DiscError):
    """The scanner is missing, failed, or produced no usable report."""


class BDInfoScanner(Protocol):
    def scan(
        self,
        disc: Disc,
        playlist_id: str,
        report_dir: Path,
        progress: ProgressCallback | None = None,
    ) -> BDInfoReport: ...


_PROGRESS = re.compile(rb"Scanning\s+(\d+)%")


class BdinfoRsScanner:
    """`bdinfo-rs` (https://github.com/agentjp/bdinfo-rs).

    `bdinfo-rs -m <playlist> <disc or .iso> <report dir>` scans one playlist and writes
    `BDINFO.<disc label>.txt` into the report folder. The report folder is
    always passed: left out, the report is written into the disc itself.
    Progress arrives on stderr as carriage-return-separated `Scanning NN%`.
    """

    def __init__(
        self, executable: Path, timeout: float = DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        self.executable = executable
        self.timeout = timeout

    def scan(
        self,
        disc: Disc,
        playlist_id: str,
        report_dir: Path,
        progress: ProgressCallback | None = None,
    ) -> BDInfoReport:
        if not self.executable.is_file():
            raise BDInfoError(f"BDInfo was not found at {self.executable}")
        report_dir.mkdir(parents=True, exist_ok=True)
        before = set(self._reports(report_dir))
        command = [
            str(self.executable),
            "--mpls",
            playlist_id,
            "--no-banner",
            # an image is read as it is, with no mount needed
            str(disc.image or disc.root),
            str(report_dir),
        ]
        try:
            process = subprocess.Popen(  # noqa: S603 - list argv, no shell; BDInfo path is the configured binary, return code checked below
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                cwd=report_dir,
                # no console window flashing up over the GUI on Windows
                creationflags=get_subprocess_creation_flags(),
            )
        except OSError as error:
            raise BDInfoError(f"BDInfo could not be started: {error}") from error

        messages = _ProgressReader(process, progress)
        messages.start()
        try:
            exit_code = process.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.wait()
            raise BDInfoError(
                f"BDInfo did not finish scanning {disc.label} "
                f"within {int(self.timeout)} seconds"
            ) from error
        finally:
            messages.join(timeout=5)

        if exit_code != 0:
            reason = messages.last_message() or "no reason given"
            raise BDInfoError(f"BDInfo failed on {disc.label} ({exit_code}): {reason}")

        written = [path for path in self._reports(report_dir) if path not in before]
        candidates = written or self._reports(report_dir)
        if not candidates:
            raise BDInfoError(f"BDInfo finished but wrote no report for {disc.label}")
        report_path = max(candidates, key=lambda path: path.stat().st_mtime)
        try:
            return parse_bdinfo_report(
                report_path.read_text(encoding="utf-8", errors="replace")
            )
        except BDInfoReportError as error:
            raise BDInfoError(f"{error} ({report_path.name})") from error

    @staticmethod
    def _reports(report_dir: Path) -> list[Path]:
        return [
            path
            for path in report_dir.iterdir()
            if path.is_file()
            and path.name.casefold().startswith("bdinfo")
            and path.suffix.casefold() == ".txt"
        ]


class _ProgressReader(threading.Thread):
    """Drain the scanner's stderr so it never blocks on a full pipe."""

    def __init__(
        self, process: subprocess.Popen[bytes], progress: ProgressCallback | None
    ) -> None:
        super().__init__(daemon=True)
        self._process = process
        self._progress = progress
        self._tail = b""

    def run(self) -> None:
        stream = self._process.stderr
        if stream is None:
            return
        last = -1
        # `read1` returns what has arrived instead of waiting for a full
        # buffer, which is what makes the progress live
        while chunk := stream.read1(4096):  # type: ignore[union-attr]
            self._tail = (self._tail + chunk)[-4096:]
            if self._progress is None:
                continue
            found = _PROGRESS.findall(chunk)
            if found and (percent := int(found[-1])) != last:
                last = percent
                self._progress(float(percent))

    def last_message(self) -> str:
        """The scanner's final line that is not a progress update."""
        text = self._tail.decode("utf-8", errors="replace")
        lines = [line.strip() for line in re.split(r"[\r\n]+", text)]
        lines = [line for line in lines if line and not line.startswith("Scanning")]
        return lines[-1].removeprefix("error:").strip() if lines else ""
