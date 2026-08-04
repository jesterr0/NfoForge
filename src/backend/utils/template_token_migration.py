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
from datetime import datetime
import difflib
from pathlib import Path
import re
import shutil

from src.config.persistence import atomic_write_text
from src.logger.nfo_forge_logger import LOG

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

# The three ways a `{` sequence opens something meaningful. Which of these
# comes first, textually, decides how it is handled -- see
# `_iter_template_parts`. Comments and raw blocks never nest and are never
# themselves scanned, so a `{{`/`{%`/`{#` that only exists inside one of them
# is never independently discovered: by the time the outer pass would reach
# that position, it has already jumped past the whole comment/raw span.
_MARKER = re.compile(r"\{#|\{%|\{\{")

# `{% raw %}...{% endraw %}` suppresses Jinja interpretation of everything
# between the tags. An unclosed `{% raw %}` is treated as running to the end
# of the template: Jinja itself would raise at render time, but this scanner
# must never crash on it, and nothing after an unclosed tag would be
# interpreted either way.
_RAW_OPEN = re.compile(r"\{%-?\s*raw\s*-?%\}")
_RAW_CLOSE = re.compile(r"\{%-?\s*endraw\s*-?%\}")

# A complete, closed quoted string literal (single or double, with backslash
# escapes), and a bare identifier. Matched one token at a time while walking
# a block body -- see `_block_body_parts` -- rather than as a blind
# full-block regex, so a delimiter- or identifier-looking sequence inside a
# literal is consumed as part of that literal and never independently
# inspected.
_STRING_LITERAL = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"")
_IDENTIFIER = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")

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


def _block_body_parts(
    text: str, pos: int, closer: str
) -> tuple[list[tuple[bool, str]], int]:
    """Split one block's body, from `pos` up to and including `closer`.

    Returns `(is_identifier, value)` parts -- `is_identifier` is True only
    for a bare identifier -- plus the index just past the closing delimiter.

    A quoted string literal is consumed whole as a single non-identifier
    part, so a delimiter- or token-looking sequence inside one (an
    `{{ "{% raw %}" }}` literal, say) is never mistaken for part of the
    surrounding structure. An unterminated literal cannot be parsed, so it
    consumes up to (and including) the next occurrence of `closer` -- the
    most this block could possibly still be -- provided that occurrence
    exists; if it doesn't, the block itself never closes either.

    A block (or a literal inside one) that never finds `closer` anywhere in
    the rest of the text fails closed, the same way an unclosed comment or
    raw region does: every part collected so far is discarded and replaced
    with a single non-identifier part spanning from `pos` to the end of the
    text. Failing open here -- yielding whatever identifiers happened to be
    found before the text ran out -- would mean a single missing `}` starts
    rewriting words throughout the rest of the document.
    """
    body_start = pos
    parts: list[tuple[bool, str]] = []
    length = len(text)
    while pos < length:
        if text.startswith(closer, pos):
            parts.append((False, closer))
            return parts, pos + len(closer)
        char = text[pos]
        if char in ("'", '"'):
            literal = _STRING_LITERAL.match(text, pos)
            if literal is None:
                close_index = text.find(closer, pos)
                if close_index == -1:
                    return [(False, text[body_start:length])], length
                end = close_index + len(closer)
                parts.append((False, text[pos:end]))
                return parts, end
            parts.append((False, literal.group(0)))
            pos = literal.end()
            continue
        identifier = _IDENTIFIER.match(text, pos)
        if identifier is not None:
            parts.append((True, identifier.group(0)))
            pos = identifier.end()
            continue
        parts.append((False, char))
        pos += 1
    return [(False, text[body_start:length])], length


def _iter_template_parts(text: str) -> Iterator[tuple[bool, str]]:
    """Single left-to-right pass over `text`.

    The sole place that decides what counts as a comment, a raw region, or a
    rewritable identifier, so `scan_template_text` and `rewrite_template_text`
    -- which differ only in what they do with an identifier part -- can never
    disagree about what is in scope. Yields `(is_identifier, value)` pairs
    whose values, concatenated in order, reconstruct `text` exactly.

    At each position, whichever of `{#`, `{%`, or `{{` occurs earliest in the
    remaining text is handled first. That single rule is what keeps a `{{`
    inside a comment from being mistaken for a real block (the comment is
    consumed in one step, before its contents are ever re-examined) and a
    `{% raw %}` inside a string literal from being mistaken for a raw tag
    (the enclosing block consumes that literal whole before continuing).
    """
    pos = 0
    length = len(text)
    while pos < length:
        marker = _MARKER.search(text, pos)
        if marker is None:
            yield False, text[pos:]
            return

        if marker.start() > pos:
            yield False, text[pos : marker.start()]

        marker_text = marker.group(0)

        if marker_text == "{#":
            close = text.find("#}", marker.end())
            end = close + 2 if close != -1 else length
            yield False, text[marker.start() : end]
            pos = end
            continue

        raw_open = _RAW_OPEN.match(text, marker.start())
        if raw_open is not None:
            close_match = _RAW_CLOSE.search(text, raw_open.end())
            end = close_match.end() if close_match is not None else length
            yield False, text[marker.start() : end]
            pos = end
            continue

        closer = "}}" if marker_text == "{{" else "%}"
        yield False, marker_text
        parts, pos = _block_body_parts(text, marker.end(), closer)
        yield from parts


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

    for is_identifier, value in _iter_template_parts(text):
        if not is_identifier:
            continue
        if value in REMOVED_TEMPLATE_TOKENS:
            removed.add(value)
            continue
        new_name = _rename_for(value)
        if new_name is not None:
            renamed[value] = new_name

    return renamed, removed


def rewrite_template_text(text: str) -> str:
    """Rewrite renameable tokens in place, leaving everything else untouched."""
    pieces: list[str] = []
    for is_identifier, value in _iter_template_parts(text):
        if not is_identifier:
            pieces.append(value)
            continue
        new_name = _rename_for(value)
        pieces.append(new_name if new_name is not None else value)
    return "".join(pieces)


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
        except (OSError, UnicodeDecodeError) as error:
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                f"Skipping unreadable template {path}: {error}",
            )
            continue
        renamed, removed = scan_template_text(text)
        report = TemplateTokenReport(path=path, renamed=renamed, removed=removed)
        if report.has_findings:
            reports.append(report)
    return reports


def _next_backup_path(path: Path) -> Path:
    """A timestamped sibling backup that never overwrites an earlier one.

    Mirrors the archive strategy used when replacing a corrupt profile: a
    timestamp for readability plus a counter so two runs in the same second
    stay distinct.
    """
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    candidate = path.with_name(f"{path.name}.{stamp}.bak")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.{stamp}_{counter}.bak")
        counter += 1
    return candidate


def build_diff(path: Path, original: str, migrated: str) -> str:
    """Unified diff of one template, for the confirmation dialog."""
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            migrated.splitlines(keepends=True),
            fromfile=f"{path.name} (current)",
            tofile=f"{path.name} (after migration)",
            n=1,
        )
    )


def migrate_template_file(path: Path) -> Path:
    """Rewrite one template in place, returning the backup path.

    The backup is written first so a failure part-way through never leaves the
    user without their original. Read with an empty ``newline`` argument so
    line endings are preserved verbatim rather than normalized by
    universal-newline decoding; the backup is a byte-exact copy via
    ``shutil.copy2``, and the rewrite is written atomically so a crash
    mid-write cannot truncate the user's file.
    """
    with path.open(encoding="utf-8", newline="") as template_file:
        original = template_file.read()
    backup_path = _next_backup_path(path)
    shutil.copy2(path, backup_path)
    atomic_write_text(path, rewrite_template_text(original))
    return backup_path


def migrate_templates(
    reports: list[TemplateTokenReport],
) -> list[tuple[Path, Path]]:
    """Migrate every reported template, skipping any that cannot be written.

    One unwritable file must not abort the batch: partial progress is better
    than none, and the caller reports which files were left alone.
    """
    migrated: list[tuple[Path, Path]] = []
    for report in reports:
        if not report.renamed:
            # Nothing to rewrite -- the file only references removed tokens,
            # which have no target and are reported to the user instead.
            continue
        try:
            backup_path = migrate_template_file(report.path)
        except (OSError, UnicodeDecodeError) as error:
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                f"Skipping template that could not be migrated {report.path}: {error}",
            )
            continue
        migrated.append((report.path, backup_path))
    return migrated
