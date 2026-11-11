"""Where on a disc each screenshot is taken.

A disc's feature is not one file: a Blu-ray playlist plays a run of `.m2ts`
clips, a DVD title set a run of `.VOB` files. Screenshots are spread over the
whole feature, then each one is mapped to the clip that holds it and an
offset into that clip, which is what FFmpeg seeks with.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random

from nfoforge.core.disc.model import Disc, DiscType, PlaylistItem, is_menu_vob

#: Never seek into a clip's last seconds: a seek that lands past the final
#: keyframe returns no frame at all.
_CLIP_TAIL_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class FrameTarget:
    """One screenshot: which clip, and how far into it."""

    path: Path
    seconds: float


def disc_frame_targets(
    disc: Disc,
    count: int,
    trim: tuple[int, int],
    feature_seconds: float | None = None,
    rng: random.Random | None = None,
) -> list[FrameTarget]:
    """`count` screenshots spread evenly over the disc's selected feature.

    `trim` is the percentage left out at the start and the end, as for a file.
    `feature_seconds` is the feature's runtime when the disc does not know it
    (a DVD whose IFO could not be read): MediaInfo's for the whole title set.
    Raises `ValueError` when the feature's length cannot be worked out.
    """
    selected = disc.selected_playlists() or disc.main_playlists()
    if not selected or count < 1:
        return []
    playlist = selected[0]
    spans = _clip_spans(disc, playlist.items, playlist.duration or feature_seconds)
    total = sum(seconds for _path, seconds in spans)
    if total <= 0:
        raise ValueError(f"The length of the feature on {disc.label} is not known")

    start_trim, end_trim = trim
    if start_trim + end_trim > 60:
        start_trim = end_trim = 30
    start = total * start_trim / 100
    usable = total * (1 - (start_trim + end_trim) / 100)
    # the same jitter files get, so two runs do not shoot identical frames
    jitter = (rng or random.Random()).uniform(0, min(10.0, usable / max(count, 1)))  # noqa: S311 - screenshot jitter, not security sensitive

    targets = []
    for index in range(count):
        position = index / (count - 1) if count > 1 else 0.5
        targets.append(_locate(spans, start + position * usable + jitter))
    return targets


def _clip_spans(
    disc: Disc, items: list[PlaylistItem], feature_seconds: float | None
) -> list[tuple[Path, float]]:
    """Each clip of the feature with the seconds the feature spends in it.

    A Blu-ray playlist states every clip's span. A DVD's VOBs are one stream
    cut every gigabyte, so the runtime is shared out by size.
    """
    if disc.disc_type is DiscType.BDMV and all(item.duration for item in items):
        return [(item.path, float(item.duration or 0)) for item in items]
    feature = [item for item in items if not is_menu_vob(item.path)]
    size = sum(item.size for item in feature)
    if not feature_seconds or size <= 0:
        return []
    return [(item.path, feature_seconds * item.size / size) for item in feature]


def _locate(spans: list[tuple[Path, float]], seconds: float) -> FrameTarget:
    """The clip that plays at `seconds` into the feature, and the offset in it."""
    for path, length in spans:
        if seconds < length or path == spans[-1][0]:
            limit = max(0.0, length - _CLIP_TAIL_SECONDS)
            return FrameTarget(path, round(min(max(seconds, 0.0), limit), 3))
        seconds -= length
    raise AssertionError("unreachable: the last span always matches")
