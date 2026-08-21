"""Render a release title through a tracker's entry.

Two stages, replacing the four rewriting layers that grew up separately:
compose from the entry (or the user's global template when it has none),
then normalise from the entry. This module is the normalisation half.

Normalisation always applies, whether or not the entry composes, so the
seven trackers with no layout of their own still get their separator,
colon and vocabulary imposed on the user's house style -- which is exactly
what they do today through their own `generate_release_title`.
"""

from __future__ import annotations

import re

from src.backend.token_replacer import TokenReplacer
from src.backend.trackers.title_rules import Normalisation, Separator
from src.backend.trackers.utils import dot_separate_title, strip_title_dots
from src.enums.token_replacer import ColonReplace

_REPEATED_WHITESPACE = re.compile(r"\s{2,}")
# A key must not rewrite the release group, which is a name rather than a
# vocabulary term: a group called "DV" would otherwise ship as "DoVi" on any
# tracker mapping that value. Bounding on a preceding hyphen rules the tag
# out while still letting a key match where a tag abuts it on the right, as
# "H.265-GRP" does.
_TAG_SEPARATOR_LOOKBEHIND = r"(?<!-)"


def normalise_title(
    title: str,
    normalisation: Normalisation,
    *,
    global_colon: ColonReplace,
) -> str:
    """Apply a tracker's always-on rules to a composed title.

    Four stages, in this order:

    1. **Separator**, first, so every later stage sees the form the tracker
       will actually receive. HDBits' "H.265" only looks like that once the
       dot-separated release form has been converted.
    2. **Colon**, from the entry where it names one and from the user's
       global title setting otherwise. That is field-level precedence, the
       same rule that governs layout.
    3. **Vocabulary**, plain rewrites then conditional ones.
    4. **Allowlist**, last, so a rewrite cannot reintroduce a character the
       tracker forbids.
    """
    if normalisation.separator is Separator.DOTTED:
        result = dot_separate_title(title)
    else:
        result = strip_title_dots(title)

    colon = normalisation.colon if normalisation.colon is not None else global_colon
    # Reused rather than reimplemented: a second definition of what a colon
    # becomes is exactly the kind of drift this design removes, and the
    # filename side already owns one.
    result = TokenReplacer._colon_replace(colon, result)

    for match, replacement in normalisation.vocabulary.items():
        result = _rewrite(result, match, replacement)

    for rule in normalisation.conditional_vocabulary:
        if rule.unless_present in result:
            continue
        result = _rewrite(result, rule.match, rule.replacement)

    if normalisation.allowlist is not None:
        result = re.sub(rf"[^{normalisation.allowlist}]+", "", result)
        # Removing a character that sat between a space and a period leaves
        # " ." behind. The allowlist permits the period, so nothing else
        # takes it out, and the separator stage has already run.
        result = result.replace(" .", ".").replace("..", ".")

    return _REPEATED_WHITESPACE.sub(" ", result).strip()


def _rewrite(title: str, match: str, replacement: str | None) -> str:
    """Replace one whole value, or remove it when `replacement` is None.

    Word-bounded rather than a substring replace, so a key of "DV" leaves
    "DVDRip" alone, and rather than whole space-delimited components, so a
    key still matches where the group tag abuts it.
    """
    pattern = rf"{_TAG_SEPARATOR_LOOKBEHIND}\b{re.escape(match)}\b"
    return re.sub(pattern, replacement if replacement is not None else "", title)
