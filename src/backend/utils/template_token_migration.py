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

from collections.abc import Iterator
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

TEMPLATE_TOKEN_RENAMES = dict(_EXPLICIT_RENAMES)

# Jinja expression `{{ ... }}` and statement `{% ... %}` blocks. Comments
# (`{# ... #}`) are deliberately excluded from this pattern rather than
# special-cased later: a token name mentioned in a comment does not affect
# rendering, so it must be neither reported nor rewritten. Restricting to
# these spans also keeps prose that happens to contain a token name untouched.
_JINJA_BLOCK = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)

# `{% raw %}...{% endraw %}` suppresses Jinja interpretation of everything
# between the tags, so its contents must be neither reported nor rewritten.
# An unclosed `{% raw %}` is treated as running to the end of the template:
# Jinja itself would raise at render time, but this scanner must never crash
# on it, and nothing after an unclosed tag would be interpreted either way.
_RAW_OPEN = re.compile(r"\{%-?\s*raw\s*-?%\}")
_RAW_CLOSE = re.compile(r"\{%-?\s*endraw\s*-?%\}")

# A quoted string literal (single or double, with backslash escapes) or a bare
# identifier, as one alternation so a string literal's contents are never
# mistaken for an identifier reference -- `default('movie_title')` must keep
# its argument untouched even while the bare identifier `movie_title`
# elsewhere in the same block is renamed.
_STRING_LITERAL = r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\""
_BLOCK_TOKEN = re.compile(rf"{_STRING_LITERAL}|\b[A-Za-z_][A-Za-z0-9_]*\b")

_TEMPLATE_SUFFIX = ".txt"


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


def _is_string_literal(token: str) -> bool:
    """True if a `_BLOCK_TOKEN` match is a quoted string, not an identifier."""
    return bool(token) and token[0] in ("'", '"')


def _raw_block_spans(text: str) -> list[tuple[int, int]]:
    """Character ranges covered by `{% raw %}...{% endraw %}`, tags included."""
    spans: list[tuple[int, int]] = []
    pos = 0
    while True:
        open_match = _RAW_OPEN.search(text, pos)
        if open_match is None:
            break
        close_match = _RAW_CLOSE.search(text, open_match.end())
        end = close_match.end() if close_match is not None else len(text)
        spans.append((open_match.start(), end))
        pos = end
    return spans


def _is_within(position: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in spans)


def _scoped_blocks(
    text: str, raw_spans: list[tuple[int, int]]
) -> Iterator[re.Match[str]]:
    """Yield the `_JINJA_BLOCK` matches in `text` that are not inside a raw span.

    The single place that decides which blocks are in scope for token
    detection, so `scan_template_text` and `rewrite_template_text` can never
    disagree about it.
    """
    for block in _JINJA_BLOCK.finditer(text):
        if not _is_within(block.start(), raw_spans):
            yield block


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

    raw_spans = _raw_block_spans(text)
    for block in _scoped_blocks(text, raw_spans):
        for match in _BLOCK_TOKEN.finditer(block.group(0)):
            token = match.group(0)
            if _is_string_literal(token):
                continue
            if token in REMOVED_TEMPLATE_TOKENS:
                removed.add(token)
                continue
            new_name = _rename_for(token)
            if new_name is not None:
                renamed[token] = new_name

    return renamed, removed


def rewrite_template_text(text: str) -> str:
    """Rewrite renameable tokens in place, leaving everything else untouched."""
    raw_spans = _raw_block_spans(text)

    def rewrite_block(block_match: re.Match[str]) -> str:
        if _is_within(block_match.start(), raw_spans):
            return block_match.group(0)

        def rewrite_token(token_match: re.Match[str]) -> str:
            token = token_match.group(0)
            if _is_string_literal(token):
                return token
            new_name = _rename_for(token)
            return new_name if new_name is not None else token

        return _BLOCK_TOKEN.sub(rewrite_token, block_match.group(0))

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
