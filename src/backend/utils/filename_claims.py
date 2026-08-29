"""Stage 1 of filename rendering: read claims out of the input filenames.

One detector, used by both the rename wizard and the settings preview, so
the two cannot disagree about what a filename claims. Pure: no Qt, no
config object, no filesystem access, no MediaInfo.

A claim here is something MediaInfo cannot verify -- an edition, an IMAX
framing, a REPACK marker, the group that made the input file. All seven
such claims are switchable.

Streaming service is the one identity field still parsed unconditionally,
and it stays that way because nothing competes with it: there is no "my
streaming service" for a user to configure, and the two trackers that
require the abbreviation scope it to web sources. The source group left
this class when it gained a competing user-owned value -- the group tag in
`[general]` -- which gave "do not read this from the filename" a meaning it
did not have before.

Every claim is pack-wide: it is reported only when every file agrees. One
dissenting episode means the claim is not the pack's.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import re

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


def detect_file_claims(
    stem: str,
    switches: ClaimSwitches,
    custom_edition_info: Sequence[RenameNormalization] = (),
) -> FilenameClaims:
    """Claims a single filename carries.

    ``custom_edition_info`` carries plugin-contributed edition entries
    (src.plugins.api.CustomEditionContribution). They are recognised
    alongside the built-in table, because detection happens here now -- a
    plugin's edition would otherwise be invisible to every caller.
    """
    all_edition_info = (*EDITION_INFO, *custom_edition_info)
    guess = dict(guessit(stem))

    def switched(name: str, detect: Callable[[str], str]) -> str:
        if not switches.enabled or not getattr(switches, name):
            return ""
        return detect(stem)

    return FilenameClaims(
        edition=switched("edition", lambda s: _normalized_value(all_edition_info, s)),
        frame_size=switched(
            "frame_size", lambda s: _normalized_value(FRAME_SIZE_INFO, s)
        ),
        localization=switched(
            "localization", lambda s: _normalized_value(LOCALIZATION_INFO, s)
        ),
        re_release=switched(
            "re_release", lambda s: _normalized_value(RE_RELEASE_INFO, s)
        ),
        remux=switched("remux", lambda s: "REMUX" if "remux" in s.lower() else ""),
        hybrid=switched("hybrid", lambda s: "HYBRID" if "hybrid" in s.lower() else ""),
        # `lstrip("-")` strips a leading dash guessit sometimes leaves on the
        # value. This is now the only place a source group is read: the
        # renderer has no filename parse of its own to disagree with.
        release_group=switched(
            "release_group",
            lambda _: str(guess.get("release_group", "") or "").lstrip("-"),
        ),
        # No switch: nothing competes with it, so "off" would mean nothing.
        streaming_service=abbreviate_streaming_service(
            str(guess.get("streaming_service", "") or "")
        ),
    )


def detect_filename_claims(
    stems: Sequence[str],
    switches: ClaimSwitches,
    custom_edition_info: Sequence[RenameNormalization] = (),
) -> FilenameClaims:
    """Every claim the pack's files agree on.

    ``stems`` are filename stems, not paths -- callers pass ``Path(p).stem``.
    A switched-off category comes back empty, as does a category the files
    disagree about.

    This is what a control shows, because a control holds one value for the
    whole pack. It is *not* what each file should render: see
    `detect_file_claims`, which is per file. A pack where one episode is a
    REPACK agrees on nothing, and that episode still deserves its marker.
    """
    if not stems:
        return FilenameClaims()

    per_file = [
        detect_file_claims(stem, switches, custom_edition_info) for stem in stems
    ]

    def agreed(name: str) -> str:
        values = {getattr(claims, name) for claims in per_file}
        return next(iter(values)) if len(values) == 1 else ""

    return FilenameClaims(
        **{field: agreed(field) for field in FilenameClaims.__dataclass_fields__}
    )
