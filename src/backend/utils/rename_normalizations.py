from collections.abc import Sequence
from src.enums.rename import TypeHierarchy
from src.packages.custom_types import RenameNormalization


EDITION_INFO: Sequence[RenameNormalization] = (
    RenameNormalization(
        "Alternative Cut",
        (r"alternative(?:[\s|\.]*cut)?",),
        "Alternative.Cut.",
        TypeHierarchy.CUT,
    ),
    RenameNormalization(
        "Collectors Edition",
        (r"(?:collector's|collectors|collector)[\s|\.]*edition",),
        "Collectors.Edition.",
        TypeHierarchy.CUT,
    ),
    RenameNormalization(
        "Criterion Edition",
        (r"criterion(?:[\s|\.]*edition)?",),
        "Criterion.Edition.",
        TypeHierarchy.CUT,
    ),
    RenameNormalization(
        "Deluxe Edition",
        (r"deluxe(?:[\s|\.]*edition)?",),
        "Deluxe.Edition.",
        TypeHierarchy.CUT,
    ),
    RenameNormalization(
        "Directors Cut",
        (r"(?:director's|directors)[\s|\.]*cut",),
        "Directors.Cut.",
        TypeHierarchy.CUT,
    ),
    RenameNormalization(
        "Extended Cut",
        (r"extended(?:[\s|\.]*cut)?",),
        "Extended.Cut.",
        TypeHierarchy.CUT,
    ),
    RenameNormalization(
        "Limited Edition",
        (r"limited(?:[\s|\.]*edition)?",),
        "Limited.Edition.",
        TypeHierarchy.CUT,
    ),
    RenameNormalization(
        "Remastered",
        (r"remastered",),
        "Remastered.",
        TypeHierarchy.CUT,
    ),
    RenameNormalization(
        "Special Edition",
        (r"special(?:[\s|\.]*edition)?",),
        "Special.Edition.",
        TypeHierarchy.CUT,
    ),
    RenameNormalization(
        "Theatrical Cut",
        (r"theatrical(?:[\s|\.]*cut)?",),
        "Theatrical.Cut.",
        TypeHierarchy.CUT,
    ),
    RenameNormalization(
        "Uncensored", (r"uncensored",), "Uncensored.", TypeHierarchy.CUT
    ),
    RenameNormalization(
        "Ultimate",
        (r"ultimate(?:[\s|\.]*edition)?",),
        "Ultimate.",
        TypeHierarchy.CUT,
    ),
    RenameNormalization("Unrated", (r"unrated",), "Unrated.", TypeHierarchy.CUT),
    RenameNormalization("Uncut", (r"uncut",), "Uncut.", TypeHierarchy.CUT),
)

# store edition strings only in a list to be used for quick matches
EDITION_STRINGS_ONLY = [x.normalized.lower().split()[0].strip() for x in EDITION_INFO]

FRAME_SIZE_INFO = (
    RenameNormalization("IMAX", (r"imax",), "IMAX.", TypeHierarchy.EXTRAS),
    RenameNormalization(
        "Open Matte",
        (r"open[\s|\.]*matte",),
        "Open.Matte.",
        TypeHierarchy.EXTRAS,
    ),
)

LOCALIZATION_INFO = (
    RenameNormalization("Dubbed", (r"dubbed",), "Dubbed.", TypeHierarchy.LOCALIZATION),
    RenameNormalization("Subbed", (r"subbed",), "Subbed.", TypeHierarchy.LOCALIZATION),
)

RE_RELEASE_INFO = (
    RenameNormalization(
        "PROPER", (r"proper(?![2345])",), "PROPER.", TypeHierarchy.RE_RELEASE
    ),
    RenameNormalization("PROPER2", (r"proper2",), "PROPER2.", TypeHierarchy.RE_RELEASE),
    RenameNormalization("PROPER3", (r"proper3",), "PROPER3.", TypeHierarchy.RE_RELEASE),
    RenameNormalization("PROPER4", (r"proper4",), "PROPER4.", TypeHierarchy.RE_RELEASE),
    RenameNormalization("PROPER5", (r"proper5",), "PROPER5.", TypeHierarchy.RE_RELEASE),
    RenameNormalization(
        "REPACK", (r"repack(?![2345])",), "REPACK.", TypeHierarchy.RE_RELEASE
    ),
    RenameNormalization("REPACK2", (r"repack2",), "REPACK2.", TypeHierarchy.RE_RELEASE),
    RenameNormalization("REPACK3", (r"repack3",), "REPACK3.", TypeHierarchy.RE_RELEASE),
    RenameNormalization("REPACK4", (r"repack4",), "REPACK4.", TypeHierarchy.RE_RELEASE),
    RenameNormalization("REPACK5", (r"repack5",), "REPACK5.", TypeHierarchy.RE_RELEASE),
)
