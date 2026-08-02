"""Detect and rewrite NfoForge tokens that were renamed, inside Jinja templates.

The config migration in `src/config/migrations.py` rewrites flat `{token}`
strings stored in the profile TOML. NFO templates are separate user-authored
files using Jinja's `{{ token }}` syntax, so they need an identifier-level
rewrite instead of a substring one. Jinja renders an undefined name as an
empty string, which is why an unmigrated template fails silently rather than
raising.

This module is deliberately Qt-free so it can be unit-tested and reused
headlessly.
"""

from dataclasses import dataclass, field
from pathlib import Path
import re

# Mirrors `_TOKEN_RENAME_MAP` and `_MI_PREFIX_RE` in `src/config/migrations.py`,
# expressed as bare identifiers because Jinja references names, not `{token}`
# strings. The `mi_` prefix strip is applied as a rule rather than enumerated,
# matching how the config migration handles it.
_EXPLICIT_RENAMES = {
    "movie_title": "title",
    "movie_clean_title": "title_clean",
    "movie_exact_title": "title_exact",
}

_MI_PREFIX = "mi_"

# Removed outright in the token overhaul with no equivalent. A template using
# this can only be reported; rewriting it would silently change meaning.
REMOVED_TEMPLATE_TOKENS = frozenset({"movie_full_title"})

# Jinja expression `{{ ... }}`, statement `{% ... %}`, and comment `{# ... #}`
# blocks. Rewriting is restricted to these spans so prose that happens to
# contain a token name is never touched.
_JINJA_BLOCK = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.DOTALL)

_IDENTIFIER = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")

_TEMPLATE_SUFFIX = ".txt"


def _build_rename_map() -> dict[str, str]:
    """Explicit renames only; `mi_` stripping is handled by `_rename_for`."""
    return dict(_EXPLICIT_RENAMES)


TEMPLATE_TOKEN_RENAMES = _build_rename_map()


def _rename_for(identifier: str) -> str | None:
    """Return the new name for `identifier`, or None if it needs no change."""
    if identifier in REMOVED_TEMPLATE_TOKENS:
        return None
    explicit = TEMPLATE_TOKEN_RENAMES.get(identifier)
    if explicit is not None:
        return explicit
    if identifier.startswith(_MI_PREFIX) and len(identifier) > len(_MI_PREFIX):
        return identifier[len(_MI_PREFIX) :]
    return None


@dataclass(slots=True)
class TemplateTokenReport:
    """One template file that references at least one stale token."""

    path: Path
    renamed: dict[str, str] = field(default_factory=dict)
    removed: set[str] = field(default_factory=set)

    @property
    def has_findings(self) -> bool:
        return bool(self.renamed or self.removed)


def scan_template_text(text: str) -> tuple[dict[str, str], set[str]]:
    """Return (renameable old->new, removed-with-no-target) for one template."""
    renamed: dict[str, str] = {}
    removed: set[str] = set()

    for block in _JINJA_BLOCK.finditer(text):
        for match in _IDENTIFIER.finditer(block.group(0)):
            identifier = match.group(0)
            if identifier in REMOVED_TEMPLATE_TOKENS:
                removed.add(identifier)
                continue
            new_name = _rename_for(identifier)
            if new_name is not None:
                renamed[identifier] = new_name

    return renamed, removed


def rewrite_template_text(text: str) -> str:
    """Rewrite renameable tokens in place, leaving everything else untouched."""

    def rewrite_block(block_match: re.Match[str]) -> str:
        def rewrite_identifier(identifier_match: re.Match[str]) -> str:
            identifier = identifier_match.group(0)
            new_name = _rename_for(identifier)
            return new_name if new_name is not None else identifier

        return _IDENTIFIER.sub(rewrite_identifier, block_match.group(0))

    return _JINJA_BLOCK.sub(rewrite_block, text)


def scan_template_dir(template_dir: Path) -> list[TemplateTokenReport]:
    """Report every `.txt` template in `template_dir` that needs migrating.

    A directory that does not exist, or a file that cannot be read as UTF-8,
    is skipped rather than raising: this runs during startup and must never
    prevent the application from launching.
    """
    if not template_dir.is_dir():
        return []

    reports: list[TemplateTokenReport] = []
    for path in sorted(template_dir.glob(f"*{_TEMPLATE_SUFFIX}")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        renamed, removed = scan_template_text(text)
        report = TemplateTokenReport(path=path, renamed=renamed, removed=removed)
        if report.has_findings:
            reports.append(report)
    return reports
