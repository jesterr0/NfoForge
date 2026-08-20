"""Stage 1 of filename rendering: read claims out of the input filenames.

One detector, used by both the rename wizard and the settings preview, so
the two cannot disagree about what a filename claims. Pure: no Qt, no
config object, no filesystem access, no MediaInfo.

A claim here is something MediaInfo cannot verify -- an edition, an IMAX
framing, a REPACK marker. The six such claims are switchable. Streaming
service and release group are always parsed, because they are identity
fields a user always wants pre-filled rather than opinions about the
release.

Every claim is pack-wide: it is reported only when every file agrees. One
dissenting episode means the claim is not the pack's.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import re
from typing import Any

from guessit import guessit

from src.backend.utils.rename_normalizations import (
    EDITION_INFO,
    FRAME_SIZE_INFO,
    LOCALIZATION_INFO,
    RE_RELEASE_INFO,
)
from src.backend.utils.streaming_services import abbreviate_streaming_service
from src.config.models import ClaimSwitches
from src.packages.custom_types import RenameNormalization


@dataclass(frozen=True, slots=True)
class FilenameClaims:
    """What the input filenames claim. Empty string means no claim."""

    edition: str = ""
    frame_size: str = ""
    localization: str = ""
    re_release: str = ""
    remux: str = ""
    hybrid: str = ""
    streaming_service: str = ""
    release_group: str = ""

    def as_override_tokens(self) -> dict[str, str]:
        """The non-empty claims keyed by token name.

        Empty claims are omitted rather than sent as "": an override of ""
        is a decision ("this release has no edition"), and stage 1 is not
        entitled to make it. Only the user, in stage 2, is.
        """
        return {
            name: value
            for name, value in (
                ("edition", self.edition),
                ("frame_size", self.frame_size),
                ("localization", self.localization),
                ("re_release", self.re_release),
                ("remux", self.remux),
                ("hybrid", self.hybrid),
                ("streaming_service", self.streaming_service),
                ("release_group", self.release_group),
            )
            if value
        }


def _normalized_value(table: Sequence[RenameNormalization], stem: str) -> str:
    for item in table:
        if any(re.search(pattern, stem, flags=re.I) for pattern in item.re_gex):
            return item.normalized
    return ""


def _pack_wide(values: Sequence[str]) -> str:
    """A claim only counts when every file agrees on it."""
    unique = set(values)
    return next(iter(unique)) if len(unique) == 1 else ""


def detect_filename_claims(
    stems: Sequence[str], switches: ClaimSwitches
) -> FilenameClaims:
    """Detect every claim the pack's filenames agree on.

    ``stems`` are filename stems, not paths -- callers pass ``Path(p).stem``.
    A switched-off category comes back empty, as does a category the files
    disagree about.

    guessit is run once per file and shared between the streaming service
    and the release group. Both read the same fields the token engine reads,
    so what a rename page shows is what an untouched release would render.
    """
    if not stems:
        return FilenameClaims()

    parsed: list[dict[str, Any]] = [dict(guessit(stem)) for stem in stems]

    def switched(name: str, detect: Callable[[str], str]) -> str:
        if not switches.enabled or not getattr(switches, name):
            return ""
        return _pack_wide([detect(stem) for stem in stems])

    return FilenameClaims(
        edition=switched("edition", lambda stem: _normalized_value(EDITION_INFO, stem)),
        frame_size=switched(
            "frame_size", lambda stem: _normalized_value(FRAME_SIZE_INFO, stem)
        ),
        localization=switched(
            "localization",
            lambda stem: _normalized_value(LOCALIZATION_INFO, stem),
        ),
        re_release=switched(
            "re_release", lambda stem: _normalized_value(RE_RELEASE_INFO, stem)
        ),
        remux=switched(
            "remux", lambda stem: "REMUX" if "remux" in stem.lower() else ""
        ),
        hybrid=switched(
            "hybrid", lambda stem: "HYBRID" if "hybrid" in stem.lower() else ""
        ),
        # No switch: identity fields the user always wants pre-filled.
        streaming_service=_pack_wide(
            [
                abbreviate_streaming_service(
                    str(guess.get("streaming_service", "") or "")
                )
                for guess in parsed
            ]
        ),
        # `lstrip("-")` mirrors the token handler, which has always stripped
        # a leading dash guessit sometimes leaves on the value.
        release_group=_pack_wide(
            [str(guess.get("release_group", "") or "").lstrip("-") for guess in parsed]
        ),
    )
