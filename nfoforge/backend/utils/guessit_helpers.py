from collections.abc import Mapping, Sequence
from typing import Any


def _first_non_empty_string(value: object) -> str:
    """Return the first usable string from a GuessIt scalar or collection."""
    if isinstance(value, str):
        return value.strip()

    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()

    return ""


def get_guessit_title(parsed: Mapping[str, Any], fallback: str = "") -> str:
    """Extract one stable title string from a GuessIt result.

    GuessIt's current schema emits ``title`` as a scalar and
    ``alternative_title`` as a list, but older/custom result shapes may expose
    a list under ``title``.  The first non-empty title is the canonical value;
    alternatives are only used when no primary title exists.
    """
    title = _first_non_empty_string(parsed.get("title"))
    if title:
        return title

    alternative_title = _first_non_empty_string(parsed.get("alternative_title"))
    if alternative_title:
        return alternative_title

    return fallback.strip()
