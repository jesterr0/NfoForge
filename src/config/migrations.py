"""Config schema migrations, applied as a chain of single-version hops.

Each entry in `MIGRATIONS` is keyed by the schema version it accepts and
produces the next version up: the migration keyed ``n`` takes a schema-``n``
document to schema-``n+1``. `migrate_document` walks that chain from whatever
version a loaded profile declares up to
``TomlConfigCodec.SCHEMA_VERSION``, so a user who skipped several releases is
migrated through every intermediate step rather than being rejected.

Schema 1 configs predate the ``schema_version`` field entirely -- the key is
simply absent from the document, so `document_version` reports such a
document as version 1.

The versions so far:

- 1 -> 2: series/TV support; ``[movie_rename]`` became ``[movie_management]``,
  with title-cleaning rules and dynamic-range settings split out into a new
  ``[global_management]`` section.
- 2 -> 3: PTPIMG support removed, dropping its image-host table and any
  stale last-used selections.
- 3 -> 4: plugin selections changed from display names to stable plugin IDs;
  selections are reset and the metadata slot is renamed.
- 4 -> 5: TorrentLeech's seeded movie title override is cleared. Its blind
  ``\\.`` -> space rule mangled audio channel layouts, and TorrentLeech's
  actual requirement is applied in code on every upload.
- 5 -> 6: per-tracker title overrides stopped being locked, so the value a
  profile stores now governs where the packaged default used to. The
  formerly locked trackers' stored values are necessarily stale (they were
  never editable, and `merge_defaults` only backfills *missing* keys), so
  they are refreshed from the packaged default.
- 6 -> 7: LST's `free` upload option changed from a boolean to the API's
  0--100 freeleech percentage. Disabled migrates to 0 and enabled to 100.

When does a bump warrant a migration?
-------------------------------------
Every `TomlConfigCodec.SCHEMA_VERSION` bump needs a matching `MIGRATIONS`
entry -- `check_migration_chain` runs at import and refuses to let the module
load otherwise. The prior question is whether the bump is warranted at all:

- Renamed, moved, or retyped keys **do** need a bump. Nothing else can map
  the old layout onto the new one.
- Added keys **do not**. ``TomlConfigCodec.merge_defaults`` backfills any key
  the packaged default declares but the user's profile lacks.
- Removed keys **do not**. ``validate_types`` only iterates over keys present
  in the default document, so a key the app no longer knows about is ignored
  rather than rejected, and decoding reads known sections by name. A stale
  section simply sits unread in the user's file.

Bumping for an added or removed key costs every user their settings for no
benefit, so prefer leaving the version alone and letting the merge/validate
path absorb the change. The 2 -> 3 hop below exists because that bump was
already released, not because removing a key required it.

This module is deliberately kept free of any Qt/UI imports so it can be unit
tested without launching the application; ``ConfigManager.load_profile`` is
the only caller in the running app, and it decides what to do when a
migration fails.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import re
from typing import Any, cast

import tomlkit

from src.config.codec import TomlConfigCodec
from src.config.paths import ConfigPaths

# Schema 1 predates the `schema_version` field; a document without the key is
# treated as this version.
SCHEMA_1_VERSION = 1
SCHEMA_2_VERSION = 2
SCHEMA_3_VERSION = 3
SCHEMA_4_VERSION = 4
SCHEMA_5_VERSION = 5
SCHEMA_6_VERSION = 6
SCHEMA_7_VERSION = 7

# A migration accepts (document, packaged_default) and returns the migrated
# document plus a list of sections it could not account for.
MigrationFn = Callable[
    [Mapping[str, Any], Mapping[str, Any] | None],
    "tuple[dict[str, Any], list[str]]",
]

# The `[image_hosts.*]` table dropped by the 2 -> 3 hop.
_REMOVED_V3_IMAGE_HOST = "ptpimg"

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


def _rename_template_settings_tokens(
    template_settings: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply the token rename map to any ``[template_settings]`` string
    values that reference tokens.

    None of schema 1's ``[template_settings]`` keys (``newline_sequence``,
    ``block_syntax_color``, etc.) are token strings today, so this call is
    forward-safety: it keeps the same rename sweep already applied to
    ``user_tokens.tokens`` and each tracker's title token override from
    silently missing a future ``[template_settings]`` field that is. Only
    string values containing ``{`` are considered, and a key is only
    rewritten if the rename actually changes it, so unrelated config
    (colors, booleans, the newline sequence) is left untouched.
    """
    new_template_settings: dict[str, Any] = dict(template_settings)
    for key, value in template_settings.items():
        if isinstance(value, str) and "{" in value:
            renamed = _rename_tokens(value)
            if renamed != value:
                new_template_settings[key] = renamed
    return new_template_settings


def _rename_tracker_title_overrides(tracker: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the token rename map to each ``[tracker.*]`` section's
    persisted ``mvr_title_token_override`` string.

    Every other tracker key is left byte-identical -- only the
    ``mvr_title_token_override`` field is a token string, and it is
    consumed verbatim as the title ``token_string`` when the tracker's
    title override is enabled (see ``src/backend/process.py``), so it must
    be carried through the same rename map applied to the movie-rename
    token fields.
    """
    new_tracker: dict[str, Any] = dict(tracker)
    for name, section in tracker.items():
        if not isinstance(section, Mapping):
            continue
        override = section.get("mvr_title_token_override")
        if isinstance(override, str) and override:
            new_section = dict(section)
            new_section["mvr_title_token_override"] = _rename_tokens(override)
            new_tracker[name] = new_section
    return new_tracker


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

    # Apply token renames to any [template_settings] string values that
    # reference tokens (see _rename_template_settings_tokens).
    template_settings = new_doc.get("template_settings")
    if isinstance(template_settings, Mapping):
        new_doc["template_settings"] = _rename_template_settings_tokens(
            template_settings
        )

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

    # Apply token renames to each tracker's persisted title token override.
    tracker_section = new_doc.get("tracker")
    if isinstance(tracker_section, Mapping):
        new_doc["tracker"] = _rename_tracker_title_overrides(tracker_section)

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


def migrate_v2_to_v3(
    old_doc: Mapping[str, Any],
    default_document: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Migrate a schema 2 config document to schema 3.

    Schema 3 removed PTPIMG support, so ``[image_hosts.ptpimg]`` and any
    ``last_used_img_host`` entries pointing at it are dropped. Nothing else
    changed: every other section is copied forward by reference, and no
    section can fail to map, so ``unmapped`` is always empty.

    Dropping the section is housekeeping rather than a requirement --
    ``validate_types`` ignores keys the packaged default no longer declares,
    and image hosts are decoded by name -- but leaving it would strand a dead
    table with a stale API key in every migrated profile.

    Args:
        old_doc: The parsed schema 2 config document.
        default_document: Unused; accepted so every migration in
            `MIGRATIONS` shares one signature.

    Returns:
        A ``(migrated_document, unmapped_sections)`` tuple.
    """
    del default_document  # signature parity across the registry

    # `schema_version` is inserted first so it serializes above the tables --
    # a top-level key emitted after a `[table]` header would be parsed back
    # as a member of that table.
    new_doc: dict[str, Any] = {"schema_version": SCHEMA_3_VERSION}
    for key, value in old_doc.items():
        if key == "schema_version":
            continue
        new_doc[key] = value

    image_hosts = new_doc.get("image_hosts")
    if isinstance(image_hosts, Mapping) and _REMOVED_V3_IMAGE_HOST in image_hosts:
        # Rebuilt rather than mutated: sections are copied forward by
        # reference above, so deleting in place would also strip the key from
        # the caller's document.
        new_doc["image_hosts"] = {
            name: section
            for name, section in image_hosts.items()
            if name != _REMOVED_V3_IMAGE_HOST
        }

    tracker_section = new_doc.get("tracker")
    if isinstance(tracker_section, Mapping):
        tracker_settings = tracker_section.get("settings")
        if isinstance(tracker_settings, Mapping):
            tracker_settings_mapping = cast(Mapping[str, Any], tracker_settings)
            last_used_hosts = tracker_settings_mapping.get("last_used_img_host")
            if isinstance(last_used_hosts, Mapping):
                cleaned_last_used_hosts: dict[str, Any] = {}
                for tracker, image_host in last_used_hosts.items():
                    if str(image_host).casefold() != _REMOVED_V3_IMAGE_HOST:
                        cleaned_last_used_hosts[str(tracker)] = image_host

                new_tracker_settings = dict(tracker_settings_mapping)
                new_tracker_settings["last_used_img_host"] = cleaned_last_used_hosts
                new_tracker = dict(cast(Mapping[str, Any], tracker_section))
                new_tracker["settings"] = new_tracker_settings
                new_doc["tracker"] = new_tracker

    return new_doc, []


def migrate_v3_to_v4(
    old_doc: Mapping[str, Any],
    default_document: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    """Reset legacy display-name plugin selections for the typed plugin API.

    ``api_keys`` (a user-supplied TMDB key override) is carried forward
    unchanged -- it is unrelated to the plugin-ID rename this hop performs.
    """

    del default_document
    new_doc: dict[str, Any] = {"schema_version": SCHEMA_4_VERSION}
    for key, value in old_doc.items():
        if key not in ("schema_version", "plugins"):
            new_doc[key] = value
    new_doc["plugins"] = {
        "wizard_page": "",
        "token_replacer": "",
        "pre_upload": "",
        "metadata_transformer": "",
    }
    return new_doc, []


# The rule TorrentLeech's override was seeded with: replace every period with
# a space. Matched exactly so a profile whose rules were edited by hand is
# carried forward untouched rather than assumed to be the seeded value.
_TL_STALE_REPLACE_MAP = [["\\.", "[space]"]]


def migrate_v4_to_v5(
    old_doc: Mapping[str, Any],
    default_document: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    """Clear TorrentLeech's seeded movie title override.

    TorrentLeech dictates no title format, so the override was locked in
    Settings and shipped enabled with a single blind rule: `\\.` -> space. It
    ran at title generation, ahead of `TLUploader.generate_release_title`,
    which applies the same rule at upload but protects audio channel layouts
    while doing it. The seeded rule got there first and shipped titles reading
    "TrueHD Atmos 7 1".

    The override was never user-editable, so a profile carrying the seeded
    rule carries it by default rather than by choice. Anything else -- a
    different rule set, or a token someone put there by hand -- is left alone.
    """

    del default_document
    new_doc: dict[str, Any] = {"schema_version": SCHEMA_5_VERSION}
    for key, value in old_doc.items():
        if key != "schema_version":
            new_doc[key] = value

    tracker_table = new_doc.get("tracker")
    if not isinstance(tracker_table, Mapping):
        return new_doc, []
    torrent_leech = tracker_table.get("torrent_leech")
    if not isinstance(torrent_leech, Mapping):
        return new_doc, []

    replace_map = _unwrap(torrent_leech.get("mvr_title_replace_map"))
    token = _unwrap(torrent_leech.get("mvr_title_token_override"))
    if replace_map != _TL_STALE_REPLACE_MAP or (token or "").strip():
        return new_doc, []

    # rebuilt rather than assigned into, so the caller's document is not
    # altered underneath it if this hop ever stops being the last one
    cleared = dict(torrent_leech)
    cleared["mvr_title_replace_map"] = []
    cleared["mvr_title_override_enabled"] = False
    new_tracker = dict(tracker_table)
    new_tracker["torrent_leech"] = cleared
    new_doc["tracker"] = new_tracker
    return new_doc, []


# Keyed by the schema version each migration accepts; each produces the next
# version up. Add an entry here for every `SCHEMA_VERSION` bump -- see the
# bump policy in this module's docstring.
# The trackers whose title override used to be locked: the settings widgets
# were disabled and the save path skipped them, so whatever a profile has
# stored for these is the packaged default from whenever that profile was
# created -- never a choice the user made.
_FORMERLY_LOCKED_TRACKER_SECTIONS = (
    "aither",
    "dark_peers",
    "huno",
    "lst",
    "only_encodes",
    "reelflix",
    "shareisland",
    "uploadcx",
)

# The keys that carry a tracker's title format.
_TITLE_OVERRIDE_KEYS = (
    "mvr_title_override_enabled",
    "mvr_title_colon_replace",
    "mvr_title_token_override",
    "mvr_title_replace_map",
    "tvr_title_overrides",
)


def migrate_v5_to_v6(
    old_doc: Mapping[str, Any],
    default_document: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    """Refresh the title overrides that used to be locked.

    Those trackers' titles were governed by the packaged default at upload
    time, so a stale value stored in a profile never mattered. Unlocking them
    makes the stored value govern instead -- and it is stale, because
    `TomlConfigCodec.merge_defaults` only backfills keys a profile is missing
    and these have been present since the profile was created.

    Left alone, every existing profile would silently go back to the title
    format it had before the tracker naming rules were corrected. Copying the
    packaged default over it loses nothing: the user could not edit these
    fields, so there is no customization here to overwrite. Trackers that were
    always editable are untouched, because for those the stored value *is* a
    choice.
    """

    new_doc: dict[str, Any] = {"schema_version": SCHEMA_6_VERSION}
    for key, value in old_doc.items():
        if key != "schema_version":
            new_doc[key] = value

    tracker_table = new_doc.get("tracker")
    if not isinstance(tracker_table, Mapping):
        return new_doc, []

    defaults = (
        default_document if default_document is not None else _load_packaged_default()
    )
    default_trackers = defaults.get("tracker")
    if not isinstance(default_trackers, Mapping):
        return new_doc, []

    new_tracker = dict(tracker_table)
    for section in _FORMERLY_LOCKED_TRACKER_SECTIONS:
        stored = new_tracker.get(section)
        packaged = default_trackers.get(section)
        if not isinstance(stored, Mapping) or not isinstance(packaged, Mapping):
            continue

        refreshed = dict(stored)
        for key in _TITLE_OVERRIDE_KEYS:
            if key in packaged:
                refreshed[key] = _unwrap(packaged[key])
            else:
                # the packaged default no longer ships this key (e.g. a
                # movie-only tracker's series overrides); drop the stale copy
                # rather than leaving it to govern
                refreshed.pop(key, None)
        new_tracker[section] = refreshed

    new_doc["tracker"] = new_tracker
    return new_doc, []


def migrate_v6_to_v7(
    old_doc: Mapping[str, Any],
    default_document: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    """Convert LST's legacy freeleech toggle to a percentage.

    The old checkbox could only send ``0`` or ``1``. Under LST's current API,
    that means 0% or 1%, while the enabled checkbox meant a fully freeleech
    upload. Preserve that intent as 100%. Integer 0/1 values are handled too,
    since older profiles sometimes persisted boolean flags that way. A
    hand-edited percentage from 2 through 100 is retained.
    """

    del default_document
    new_doc: dict[str, Any] = {"schema_version": SCHEMA_7_VERSION}
    for key, value in old_doc.items():
        if key != "schema_version":
            new_doc[key] = value

    tracker_table = new_doc.get("tracker")
    if not isinstance(tracker_table, Mapping):
        return new_doc, []
    lst = tracker_table.get("lst")
    if not isinstance(lst, Mapping) or "free" not in lst:
        return new_doc, []

    legacy_free = _unwrap(lst["free"])
    if type(legacy_free) is bool:
        percentage = 100 if legacy_free else 0
    elif type(legacy_free) is int and legacy_free in (0, 1):
        percentage = 100 if legacy_free else 0
    else:
        percentage = legacy_free

    migrated_lst = dict(lst)
    migrated_lst["free"] = percentage
    migrated_trackers = dict(tracker_table)
    migrated_trackers["lst"] = migrated_lst
    new_doc["tracker"] = migrated_trackers
    return new_doc, []


MIGRATIONS: dict[int, MigrationFn] = {
    SCHEMA_1_VERSION: migrate_unversioned_to_v2,
    SCHEMA_2_VERSION: migrate_v2_to_v3,
    SCHEMA_3_VERSION: migrate_v3_to_v4,
    SCHEMA_4_VERSION: migrate_v4_to_v5,
    SCHEMA_5_VERSION: migrate_v5_to_v6,
    SCHEMA_6_VERSION: migrate_v6_to_v7,
}


def check_migration_chain(
    registry: Mapping[int, MigrationFn],
    schema_version: int,
    lowest: int = SCHEMA_1_VERSION,
) -> None:
    """Verify the registry can carry any supported document to the current
    schema version.

    Raises:
        RuntimeError: If a hop is missing (some version cannot reach
            ``schema_version``) or the registry holds a hop outside the
            supported range.
    """
    expected = set(range(lowest, schema_version))
    actual = set(registry)

    missing = sorted(expected - actual)
    if missing:
        raise RuntimeError(
            "Config migration chain is incomplete: no migration is registered "
            f"for schema version(s) {missing}, so a profile at that version "
            f"cannot reach schema_version {schema_version} and would be "
            "rejected as unsupported at startup. Every SCHEMA_VERSION bump "
            "needs a matching MIGRATIONS entry -- see the bump policy in "
            "src/config/migrations.py."
        )

    unexpected = sorted(actual - expected)
    if unexpected:
        raise RuntimeError(
            "Config migration chain registers hop(s) beyond the supported "
            f"range: {unexpected}. The current schema_version is "
            f"{schema_version}, so migrations may only be keyed "
            f"{lowest}..{schema_version - 1}."
        )


def document_version(document: Mapping[str, Any]) -> int:
    """The schema version a config document declares.

    Schema 1 predates the field, so a document without ``schema_version`` is
    reported as `SCHEMA_1_VERSION`.

    Raises:
        TypeError, ValueError: If the field is present but not an integer.
    """
    if "schema_version" not in document:
        return SCHEMA_1_VERSION
    raw = document["schema_version"]
    return int(raw.unwrap() if hasattr(raw, "unwrap") else raw)


def migrate_document(
    document: Mapping[str, Any],
    default_document: Mapping[str, Any] | None = None,
    target_version: int | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Apply every migration needed to bring ``document`` up to the current
    schema version.

    Hops are applied in sequence, so a profile several versions behind is
    carried through each intermediate shape rather than being rejected. A
    document already at the target version is returned unchanged.

    Args:
        document: The parsed config document, at any supported version.
        default_document: The packaged default, passed through to each
            migration so they source brand new sections from the same
            defaults the rest of the load path uses.
        target_version: The version to migrate to. Defaults to
            ``TomlConfigCodec.SCHEMA_VERSION``.

    Returns:
        A ``(migrated_document, unmapped_sections)`` tuple, with
        ``unmapped_sections`` accumulated across every hop. A non-empty list
        means some hop could not fully account for the user's settings and
        the caller should discard the result in favor of archive+regenerate.

    Raises:
        RuntimeError: If a required hop is missing from `MIGRATIONS`. The
            import-time `check_migration_chain` call makes this unreachable
            for the real registry.
    """
    target = (
        TomlConfigCodec.SCHEMA_VERSION if target_version is None else target_version
    )
    version = document_version(document)
    unmapped: list[str] = []
    current: Mapping[str, Any] = document

    while version < target:
        migration = MIGRATIONS.get(version)
        if migration is None:
            raise RuntimeError(
                f"No config migration registered for schema version {version}; "
                f"cannot reach schema_version {target}."
            )
        current, step_unmapped = migration(current, default_document)
        unmapped.extend(step_unmapped)
        version += 1

    return dict(current), unmapped


# Import-time invariant: a SCHEMA_VERSION bump without a matching migration
# breaks every existing profile, and the symptom (an "unsupported schema"
# dialog offering to wipe the user's settings) surfaces far from the cause.
# Failing here means the developer who bumped the version hits it on their
# next run instead. Both operands are source constants, so this cannot start
# failing in the field for a build that imports cleanly.
#
# Deliberately an explicit raise rather than `assert`, which `python -O`
# strips. The packaged default's `schema_version` is checked separately by
# `ConfigManager.load_profile`, which validates the default document on every
# load -- that one needs file I/O and so does not belong at import time.
check_migration_chain(MIGRATIONS, TomlConfigCodec.SCHEMA_VERSION)
