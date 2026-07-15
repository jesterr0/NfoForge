"""One-time migration from the unversioned ("schema 1") config layout to schema 2.

Schema 1 configs predate the ``schema_version`` field entirely -- the key is
simply absent from the document. Schema 2 introduced series/TV support and
reorganized a handful of movie-rename settings (``[movie_rename]`` became
``[movie_management]``, with the title-cleaning rules and dynamic-range
settings split out into a new ``[global_management]`` section). This module
maps a schema 1 document onto the schema 2 shape while preserving anything
the user customized.

This is deliberately kept free of any Qt/UI imports so it can be unit tested
without launching the application; ``ConfigManager.load_profile`` is the only
caller in the running app, and it decides what to do when migration fails.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import tomlkit

from src.config.paths import ConfigPaths

SCHEMA_2_VERSION = 2

# The only schema 1 section that needs to be relocated/renamed rather than
# copied forward unchanged.
_MOVIE_RENAME_KEY = "movie_rename"

# Scalar keys that move from [movie_rename] to [movie_management] unchanged.
_MOVIE_MANAGEMENT_SCALAR_KEYS = (
    "mvr_enabled",
    "mvr_replace_illegal_chars",
    "mvr_colon_replace_filename",
    "mvr_colon_replace_title",
    "mvr_parse_filename_attributes",
    "mvr_release_group",
)

# Keys that move from [movie_rename] to [movie_management] with the token
# rename map applied to their (string) values.
_MOVIE_MANAGEMENT_TOKEN_KEYS = ("mvr_token", "mvr_title_token")

# Token rename map (old movie-token name -> new generic token name). Applied
# to any persisted token string that may reference these tokens.
_TOKEN_RENAME_MAP: tuple[tuple[str, str], ...] = (
    ("{movie_title}", "{title}"),
    ("{movie_clean_title}", "{title_clean}"),
    ("{movie_exact_title}", "{title_exact}"),
)
# Every MediaInfo token dropped its `mi_` prefix, e.g. `{mi_audio_codec}` ->
# `{audio_codec}`.
_MI_PREFIX_RE = re.compile(r"\{mi_")

# Schema 1 packaged defaults shipped `template_settings.newline_sequence` as
# a TOML *literal* string (single-quoted), e.g. `newline_sequence = '\\n'`.
# Literal strings do not process escapes at all, so that parses to the
# THREE characters backslash + backslash + "n" -- not an actual newline.
# (A hand-edited *basic*, double-quoted `"\\n"` would similarly parse to the
# two characters backslash + "n".) Schema 2's `TomlConfigCodec.
# validate_settings` requires a real newline/carriage-return character, so
# we normalize the known legacy representations back to what the user
# actually intended rather than let a default, unmodified profile fail
# validation immediately after migration.
_LEGACY_NEWLINE_SEQUENCES = {
    "\\n": "\n",
    "\\r": "\r",
    "\\r\\n": "\r\n",
    "\\\\n": "\n",
    "\\\\r": "\r",
    "\\\\r\\\\n": "\r\n",
}


def _rename_tokens(value: str) -> str:
    """Apply the token rename map to a single persisted token string."""
    for old, new in _TOKEN_RENAME_MAP:
        value = value.replace(old, new)
    return _MI_PREFIX_RE.sub("{", value)


def _rename_tokens_recursive(value: Any) -> Any:
    """Apply ``_rename_tokens`` to strings, recursing into lists/mappings."""
    if isinstance(value, str):
        return _rename_tokens(value) if "{" in value else value
    if isinstance(value, Mapping):
        return {key: _rename_tokens_recursive(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_rename_tokens_recursive(item) for item in value]
    return value


def _unwrap(value: Any) -> Any:
    """Recursively convert tomlkit items into plain Python containers."""
    if hasattr(value, "unwrap"):
        return value.unwrap()
    if isinstance(value, Mapping):
        return {key: _unwrap(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_unwrap(item) for item in value]
    return value


def _load_packaged_default() -> Mapping[str, Any]:
    default_text = ConfigPaths().default_config.read_text(encoding="utf-8")
    return tomlkit.parse(default_text)


def _build_movie_management(
    movie_rename: Mapping[str, Any], unmapped: list[str]
) -> dict[str, Any] | None:
    try:
        movie_management: dict[str, Any] = {
            key: movie_rename[key] for key in _MOVIE_MANAGEMENT_SCALAR_KEYS
        }
        for key in _MOVIE_MANAGEMENT_TOKEN_KEYS:
            movie_management[key] = _rename_tokens(str(movie_rename[key]))
    except (KeyError, TypeError):
        unmapped.append("movie_management")
        return None
    return movie_management


def _build_global_management(
    movie_rename: Mapping[str, Any], unmapped: list[str]
) -> dict[str, Any] | None:
    try:
        dynamic_range_src = movie_rename["mvr_mi_video_dynamic_range"]
        global_management = {
            "title_clean_rules": _unwrap(movie_rename["mvr_clean_title_rules"]),
            "title_clean_rules_modified": movie_rename[
                "mvr_clean_title_rules_modified"
            ],
            "video_dynamic_range": {
                "resolutions": _unwrap(dynamic_range_src["resolutions"]),
                "hdr_types": _unwrap(dynamic_range_src["hdr_types"]),
                "custom_strings": _unwrap(dynamic_range_src["custom_strings"]),
            },
        }
    except (KeyError, TypeError):
        unmapped.append("global_management")
        return None
    return global_management


def migrate_unversioned_to_v2(
    old_doc: Mapping[str, Any],
    default_document: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Migrate an unversioned ("schema 1") config document to schema 2.

    Args:
        old_doc: The parsed, unversioned config document (a ``tomlkit``
            document or a plain ``dict``).
        default_document: The packaged schema-2 default document to source
            brand new sections from. When omitted, the packaged default is
            read from the default ``ConfigPaths().default_config`` location.
            Callers that already have a defaults document loaded (e.g.
            ``ConfigManager``) should pass it explicitly so the migration
            uses the exact same defaults the rest of the load path uses.

    Returns:
        A ``(migrated_document, unmapped_sections)`` tuple. When
        ``unmapped_sections`` is non-empty, the migration could not fully
        account for the user's settings and the result should be discarded
        by the caller in favor of the archive+regenerate flow -- it is
        still returned (rather than raising) so callers can inspect what
        failed.

    Note:
        This function fills brand new *sections* (``series_management``,
        the derived ``global_management``) from the packaged default, but it
        does not backfill new *leaf* keys inside otherwise-unchanged
        sections (e.g. ``general.enable_plugins``). Callers are expected to
        run the returned document through the normal
        ``TomlConfigCodec.merge_defaults`` step afterward, exactly as they
        would for any already-current-schema config, to pick those up.
    """
    unmapped: list[str] = []
    new_doc: dict[str, Any] = {"schema_version": SCHEMA_2_VERSION}

    # Copy every section forward unchanged, except `movie_rename`, which is
    # relocated/renamed below.
    for key, value in old_doc.items():
        if key in (_MOVIE_RENAME_KEY, "schema_version"):
            continue
        new_doc[key] = value

    # Defensive fix-up for the legacy newline-sequence representation.
    template_settings = new_doc.get("template_settings")
    if (
        isinstance(template_settings, Mapping)
        and "newline_sequence" in template_settings
    ):
        current = template_settings["newline_sequence"]
        fixed = _LEGACY_NEWLINE_SEQUENCES.get(str(current))
        if fixed is not None:
            new_template_settings = dict(template_settings)
            new_template_settings["newline_sequence"] = fixed
            new_doc["template_settings"] = new_template_settings

    # Apply token renames to persisted user-defined token strings.
    user_tokens = new_doc.get("user_tokens")
    if isinstance(user_tokens, Mapping) and isinstance(
        user_tokens.get("tokens"), Mapping
    ):
        new_doc["user_tokens"] = {
            **user_tokens,
            "tokens": {
                name: _rename_tokens_recursive(_unwrap(entry))
                for name, entry in user_tokens["tokens"].items()
            },
        }

    movie_rename = old_doc.get(_MOVIE_RENAME_KEY)
    if not isinstance(movie_rename, Mapping):
        unmapped.append("movie_management")
        unmapped.append("global_management")
        return new_doc, unmapped

    movie_management = _build_movie_management(movie_rename, unmapped)
    if movie_management is not None:
        new_doc["movie_management"] = movie_management

    global_management = _build_global_management(movie_rename, unmapped)
    if global_management is not None:
        new_doc["global_management"] = global_management

    # Brand new sections are seeded wholesale from the packaged default.
    try:
        defaults = (
            default_document
            if default_document is not None
            else _load_packaged_default()
        )
    except OSError:
        defaults = {}

    if "series_management" not in new_doc and "series_management" in defaults:
        new_doc["series_management"] = _unwrap(defaults["series_management"])

    return new_doc, unmapped
