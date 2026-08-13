"""Streaming service abbreviations, derived from guessit's own pattern config.

Aither and LST both require the service abbreviation on a web release --
"Violet Evergarden: Recollections 2021 1080p NF WEB-DL ...", where `NF` is
Netflix. guessit already recognises the abbreviation in a release name, but it
reports the *full* name ("Netflix"), which is not what goes in a title.

The mapping between the two is guessit's `advanced_config.streaming_service`
table, which is keyed by full name and lists the abbreviations that resolve to
it, most canonical first. Reading that table gives the reverse mapping for all
~160 services it knows, in step with whatever guessit version is installed,
instead of a copy here that silently falls behind.

That table is guessit-internal, so the loader is defensive and the result is
pinned by tests/test_backend/test_streaming_services.py -- a guessit upgrade
that moves or reshapes it fails there rather than quietly dropping the service
from every title.
"""

from __future__ import annotations

from importlib import resources
import json
from typing import Any

from guessit import guessit

from src.logger.nfo_forge_logger import LOG

# A handful of well-known services, used only to prove the derived table
# actually loaded. Not a fallback: shipping five services where guessit offers
# 160 would look like it worked while quietly dropping the rest.
_SANITY_CHECK = {"Netflix": "NF", "Amazon Prime": "AMZN", "Disney+": "DSNP"}


def _first_literal(patterns: Any) -> str | None:
    """Pick the canonical abbreviation out of one service's pattern entry.

    Three shapes appear in the table:
      "AMC"                              a lone abbreviation
      ["NF", "Netflix"]                  abbreviation first, then aliases
      {"pattern": "MAX", ...}            a case-sensitive pattern

    Entries prefixed "re:" are regexes ("re:Amazon-?Prime"), never the
    abbreviation, so they are skipped.
    """
    if isinstance(patterns, str):
        candidates = [patterns]
    elif isinstance(patterns, dict):
        pattern = patterns.get("pattern")
        candidates = [pattern] if isinstance(pattern, str) else []
    elif isinstance(patterns, list):
        candidates = [p for p in patterns if isinstance(p, str)]
    else:
        return None

    for candidate in candidates:
        if not candidate.startswith("re:"):
            return candidate
    return None


def _load() -> dict[str, str]:
    try:
        config = json.loads(
            (resources.files("guessit") / "config" / "options.json").read_text(
                encoding="utf-8"
            )
        )
        table = config["advanced_config"]["streaming_service"]
        mapping = {
            name: abbreviation
            for name, patterns in table.items()
            if (abbreviation := _first_literal(patterns))
        }
    except Exception as error:
        LOG.warning(
            LOG.LOG_SOURCE.BE,
            "Could not read guessit's streaming-service table, so the "
            f"{{streaming_service}} token will stay empty: {error}",
        )
        return {}

    missing = [name for name in _SANITY_CHECK if name not in mapping]
    if missing:
        LOG.warning(
            LOG.LOG_SOURCE.BE,
            "guessit's streaming-service table loaded but is missing expected "
            f"entries ({', '.join(missing)}); its format may have changed.",
        )
    return mapping


# guessit's full service name -> the abbreviation a release title uses.
STREAMING_SERVICE_ABBREVIATIONS: dict[str, str] = _load()

# Every abbreviation, for the rename pages' Service combo box. Sorted
# case-insensitively so "iP" and "iTunes" file with the letters rather than
# ahead of everything uppercase.
STREAMING_SERVICE_CHOICES: tuple[str, ...] = tuple(
    sorted(set(STREAMING_SERVICE_ABBREVIATIONS.values()), key=str.casefold)
)


def abbreviate_streaming_service(name: object) -> str:
    """Map a guessit streaming-service name to its release abbreviation.

    guessit reports a list when a release name matches more than one service;
    the first is the one that won. An unknown name returns "" rather than
    itself -- a full service name in a title is more wrong than no service.
    """
    if isinstance(name, list):
        name = name[0] if name else ""
    if not isinstance(name, str) or not name.strip():
        return ""
    return STREAMING_SERVICE_ABBREVIATIONS.get(name.strip(), "")


def detect_streaming_service(release_name: str) -> str:
    """Return the service abbreviation a release name carries, or "".

    Used by the rename pages to preselect their Service combo. The token reads
    the same guessit field through `abbreviate_streaming_service`, so what the
    combo shows is what an untouched release would render.
    """
    if not release_name:
        return ""
    return abbreviate_streaming_service(
        guessit(release_name).get("streaming_service", "")
    )
