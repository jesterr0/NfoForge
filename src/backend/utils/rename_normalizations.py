from collections.abc import Sequence

from src.packages.custom_types import RenameNormalization


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

FRAME_SIZE_INFO = (
    RenameNormalization("IMAX", (r"imax",)),
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
