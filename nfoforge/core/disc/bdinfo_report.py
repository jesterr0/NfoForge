"""Read a BDInfo report.

The report is text laid out for people. Its QUICK SUMMARY block is what
trackers ask for, and it is also the one part with a stable shape: one
`Label: value` line per fact, a stream's details joined by " / ". Everything
structured is read from there, by label and by what each detail looks like,
never by its position in the line, which moves whenever a stream has an extra
detail (a 3D eye, an Atmos core, a dialnorm offset).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re


class BDInfoReportError(Exception):
    """Text that is not a usable BDInfo report."""


@dataclass(frozen=True, slots=True)
class BDVideoStream:
    codec: str
    description: str
    bitrate_kbps: int | None = None
    resolution: str | None = None
    frame_rate: str | None = None
    aspect_ratio: str | None = None
    # the HDR formats named on the stream: "HDR10", "HDR10+", "Dolby Vision"
    hdr: tuple[str, ...] = ()
    is_3d: bool = False


@dataclass(frozen=True, slots=True)
class BDAudioStream:
    language: str
    codec: str
    description: str
    channels: str | None = None
    bitrate_kbps: int | None = None
    is_atmos: bool = False


@dataclass(frozen=True, slots=True)
class BDSubtitleStream:
    language: str
    description: str


@dataclass(frozen=True, slots=True)
class BDInfoReport:
    full: str
    """The whole report, as the scanner wrote it."""

    quick_summary: str
    """The QUICK SUMMARY block: what a tracker's BDInfo field takes."""

    disc_label: str = ""
    disc_size: int | None = None
    playlist: str = ""
    size: int | None = None
    length: str = ""
    total_bitrate: str = ""
    video: tuple[BDVideoStream, ...] = field(default_factory=tuple)
    audio: tuple[BDAudioStream, ...] = field(default_factory=tuple)
    subtitles: tuple[BDSubtitleStream, ...] = field(default_factory=tuple)

    @property
    def duration_seconds(self) -> float | None:
        match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})(?:\.(\d+))?", self.length)
        if not match:
            return None
        hours, minutes, seconds = (int(match.group(i)) for i in (1, 2, 3))
        fraction = float(f"0.{match.group(4)}") if match.group(4) else 0.0
        return hours * 3600 + minutes * 60 + seconds + fraction


_SUMMARY_HEADER = re.compile(r"^QUICK SUMMARY:\s*$", re.MULTILINE)
_SECTION_BREAK = re.compile(r"^\*{5,}\s*$", re.MULTILINE)
_HDR_NAMES = ("Dolby Vision", "HDR10+", "HDR10", "HLG")


def parse_bdinfo_report(text: str) -> BDInfoReport:
    """A report for one playlist. Raises `BDInfoReportError` without a summary."""
    header = _SUMMARY_HEADER.search(text)
    if not header:
        raise BDInfoReportError("The BDInfo report has no QUICK SUMMARY section")
    body = text[header.end() :]
    # a multi-playlist report starts the next playlist with a starred banner
    end = _SECTION_BREAK.search(body)
    summary = (body[: end.start()] if end else body).strip()
    if not summary:
        raise BDInfoReportError("The BDInfo report's QUICK SUMMARY is empty")

    facts: dict[str, str] = {}
    video: list[BDVideoStream] = []
    audio: list[BDAudioStream] = []
    subtitles: list[BDSubtitleStream] = []
    for line in summary.splitlines():
        label, separator, value = line.partition(":")
        if not separator:
            continue
        label, value = label.strip().casefold(), value.strip()
        details = [part.strip() for part in value.split(" / ") if part.strip()]
        if label == "video" and details:
            video.append(_video(details, value))
        elif label == "audio" and len(details) >= 2:
            audio.append(_audio(details, value))
        elif label == "subtitle" and details:
            subtitles.append(BDSubtitleStream(details[0], value))
        elif label.startswith("*"):
            # hidden streams are listed with a leading "* "
            continue
        else:
            facts.setdefault(label, value)

    return BDInfoReport(
        full=text,
        quick_summary=summary,
        disc_label=facts.get("disc label", ""),
        disc_size=_bytes(facts.get("disc size")),
        playlist=facts.get("playlist", ""),
        size=_bytes(facts.get("size")),
        length=facts.get("length", ""),
        total_bitrate=facts.get("total bitrate", ""),
        video=tuple(video),
        audio=tuple(audio),
        subtitles=tuple(subtitles),
    )


def _video(details: list[str], description: str) -> BDVideoStream:
    rest = details[1:]
    return BDVideoStream(
        codec=details[0],
        description=description,
        bitrate_kbps=_kbps(rest),
        resolution=_first(rest, r"\d{3,4}[pi]"),
        frame_rate=_first(rest, r"[\d.]+ fps"),
        aspect_ratio=_first(rest, r"\d+(?:\.\d+)?:\d+"),
        hdr=tuple(
            name
            for name in _HDR_NAMES
            if any(part.casefold() == name.casefold() for part in rest)
        ),
        is_3d=any("eye" in part.casefold() for part in rest),
    )


def _audio(details: list[str], description: str) -> BDAudioStream:
    rest = details[2:]
    return BDAudioStream(
        language=details[0],
        codec=details[1],
        description=description,
        channels=_first(rest, r"\d\.\d(?:-\w+)?(?:\+\d+ objects)?"),
        bitrate_kbps=_kbps(rest),
        is_atmos="atmos" in description.casefold(),
    )


def _first(parts: list[str], pattern: str) -> str | None:
    for part in parts:
        if re.fullmatch(pattern, part, flags=re.IGNORECASE):
            return part
    return None


def _kbps(parts: list[str]) -> int | None:
    for part in parts:
        match = re.fullmatch(r"([\d,]+)\s*kbps", part, flags=re.IGNORECASE)
        if match:
            return int(match.group(1).replace(",", ""))
    return None


def _bytes(value: str | None) -> int | None:
    match = re.match(r"([\d,]+)\s*bytes", value or "")
    return int(match.group(1).replace(",", "")) if match else None
