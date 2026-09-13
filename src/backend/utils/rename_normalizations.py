from collections.abc import Sequence
import re

from src.packages.custom_types import RenameNormalization

IMAX_REGEX = r"(?<![A-Za-z0-9])imax(?![A-Za-z0-9])"


def is_imax(value: object) -> bool:
    """Return whether a value contains IMAX as a standalone release token."""
    return (
        isinstance(value, str)
        and re.search(IMAX_REGEX, value, re.IGNORECASE) is not None
    )


EDITION_INFO: Sequence[RenameNormalization] = (
    RenameNormalization(
        "Alternative Cut",
        (r"alternative(?:[\s\.\-_]*cut)?",),
    ),
    RenameNormalization(
        "Collectors Edition",
        (r"collector'?s?([\s\.\-_]*edition)?",),
    ),
    RenameNormalization(
        "Criterion Edition",
        (r"criterion(?:[\s\.\-_]*edition)?",),
    ),
    RenameNormalization(
        "Deluxe Edition",
        (r"deluxe(?:[\s\.\-_]*edition)?",),
    ),
    RenameNormalization(
        "Directors Cut",
        (r"(?:director's|directors)[\s\.\-_]*cut",),
    ),
    RenameNormalization(
        "Extended Cut",
        (r"extended(?:[\s\.\-_]*cut)?",),
    ),
    RenameNormalization(
        "Limited Edition",
        (r"limited(?:[\s\.\-_]*edition)?",),
    ),
    RenameNormalization(
        "Remastered",
        (r"remastered",),
    ),
    RenameNormalization(
        "Special Edition",
        (r"special(?:[\s\.\-_]*edition)?",),
    ),
    RenameNormalization(
        "Theatrical Cut",
        (r"theatrical(?:[\s\.\-_]*cut)?",),
    ),
    RenameNormalization("Uncensored", (r"uncensored",)),
    RenameNormalization(
        "Ultimate",
        (r"ultimate(?:[\s\.\-_]*edition)?",),
    ),
    RenameNormalization("Unrated", (r"unrated",)),
    RenameNormalization("Uncut", (r"uncut",)),
)

# Which EDITION_INFO entries are a "Cut" -- a different version of the film --
# versus a marketing "Edition", which the guides say to omit from the title and
# mention in the description instead. EDITION_INFO stays the single source of
# truth for *what's recognized*; this set only governs *which recognized
# entries count as a Cut* -- see token_replacer._cut().
#
# One set rather than one per tracker, because the four published guides agree
# on the question this set answers. Their example lists differ in length and
# are all written "e.g.", so a name's absence from one of them is not that
# tracker excluding it: LST states the rule outright as "included only if the
# cut is not the Theatrical cut", which admits every non-theatrical cut here.
# Where a tracker does differ, it differs on spelling or on whether it wants
# the component at all, and both of those live in its title_rules entry.
#
# "Special Edition" is a Cut despite its name. ReelFliX and Blutopia both list
# it among their cut examples, and it is a genuinely different version rather
# than the packaging that "Collectors" or "Limited" describes.
CUT_EDITION_NAMES: frozenset[str] = frozenset(
    {
        "Alternative Cut",
        "Directors Cut",
        "Extended Cut",
        "Special Edition",
        "Theatrical Cut",
        "Uncut",
        "Unrated",
    }
)

FRAME_SIZE_INFO = (
    RenameNormalization("IMAX", (IMAX_REGEX,)),
    RenameNormalization(
        "Open Matte",
        (r"open[\s\.\-_]*matte",),
    ),
)

LOCALIZATION_INFO = (
    RenameNormalization("Dubbed", (r"dubbed",)),
    RenameNormalization("Subbed", (r"subbed",)),
)

RE_RELEASE_INFO = (
    RenameNormalization("PROPER", (r"proper(?![2345])",)),
    RenameNormalization("PROPER2", (r"proper2",)),
    RenameNormalization("PROPER3", (r"proper3",)),
    RenameNormalization("PROPER4", (r"proper4",)),
    RenameNormalization("PROPER5", (r"proper5",)),
    RenameNormalization("REPACK", (r"repack(?![2345])",)),
    RenameNormalization("REPACK2", (r"repack2",)),
    RenameNormalization("REPACK3", (r"repack3",)),
    RenameNormalization("REPACK4", (r"repack4",)),
    RenameNormalization("REPACK5", (r"repack5",)),
)
