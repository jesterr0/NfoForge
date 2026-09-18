"""Taking a configuration out of the data folder, and bringing one back in.

Separate from `layout_migration`/`layout_apply`, which move a whole previous
installation folder-to-folder on the machine it is already on. This module
answers a different question: what is the smallest thing that can be handed to
another machine, or another person, and still be a working configuration.

A profile on its own is not that thing. It names its NFO templates by stem and
those live in `templates/`, so a profile copied by itself arrives with every
template reference pointing at nothing. It also carries the user's passkeys,
API keys, passwords and TOTP seeds, so "just send them the file" hands over an
identity. A bundle therefore carries the templates a profile references, and
strips credentials unless the user asks for them.

Nothing here imports Qt. The dialogs in
`src/frontend/windows/config_transfer.py` are a thin layer over these
functions, so that every rule about what may be exported, what is refused on
import and what is never overwritten is testable without a running application.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
import zipfile

import tomlkit
import tomllib

from src.backend.template_selector import TEMPLATE_SUFFIX
from src.config.codec import TomlConfigCodec
from src.config.layout_apply import SUMMARY_LOG_NAME
from src.config.migrations import document_version, migrate_document
from src.config.paths import AppPaths
from src.config.persistence import atomic_write_text
from src.config.profiles import PROFILE_SUFFIX
from src.logger.nfo_forge_logger import LOG
from src.plugins.loader import declared_plugins
from src.utils.safe_archive import UnsafeArchiveError, read_member, safe_members
from src.utils.secret_redaction import blank_credentials
from src.version import __version__

EXPORT_MANIFEST_NAME = "nfoforge-export.toml"

EXPORT_VERSION = 1
"""The bundle format, versioned independently of the profile schema.

Two things can change here and they change for unrelated reasons: what a bundle
contains, and what a profile contains. A bundle made by a newer NfoForge is
refused on the first; a profile from a newer schema is refused on the second.
"""

PROFILES_DIR_NAME = "profiles"
TEMPLATES_DIR_NAME = "templates"

PLUGINS_TABLE = "plugins"
"""The profile table holding one selected plugin id per capability."""

MAX_BUNDLE_ENTRIES = 512

MAX_BUNDLE_BYTES = 32 * 1024 * 1024
"""A bundle is profiles and templates -- text, measured in kilobytes.

Deliberately far below what a plugin archive is allowed. Nothing legitimate
comes near it, so the cap costs nothing, and a bundle that reaches it is not
one to keep reading.
"""

TEMPLATE_KEY = "nfo_template"
"""The only key in the schema that names a template.

Checked against `assets/config/defaults/default_config.toml`: seventeen tracker
tables carry it and nothing else references a template by name. Swept for
recursively rather than read from seventeen known paths, so a tracker added
later is covered without this module being told about it.
"""

_MACHINE_SPECIFIC: tuple[tuple[str, tuple[str, ...] | None], ...] = (
    ("general", ("working_dir",)),
    ("dependencies", None),
)
"""Settings whose value is a path on the machine that wrote them.

Same shape as `layout_apply._repoint`, and for the same reason: `None` means
every key in the table, so a dependency added later is cleared without this
list being updated. `enable_mkbrr` is a bool and is skipped by the string check
at the point of use.
"""

_RESERVED_STEMS = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{digit}" for digit in range(1, 10)),
        *(f"lpt{digit}" for digit in range(1, 10)),
    }
)
"""Windows device names. A file cannot be created under any of them."""

_ILLEGAL_NAME_CHARACTERS = '/\\:*?"<>|'


class TransferError(Exception):
    """An export or import was refused, with a reason worth showing a user."""


class NameConflict(Enum):
    """What to do about an incoming name that is already in use."""

    KEEP_BOTH = "Keep both"
    SKIP = "Skip"
    REPLACE = "Replace"


class EntryKind(Enum):
    PROFILE = "Profile"
    TEMPLATE = "Template"


class Disposition(Enum):
    NEW = "New"
    RENAMED = "Renamed"
    SKIPPED = "Skipped"
    REPLACED = "Replaced"
    UNCHANGED = "Already present"
    """The file already there is byte for byte the incoming one.

    Only reachable for templates, and only because importing the same bundle
    twice is an ordinary thing to do. Without it, `Keep both` would produce
    `movie (2)` identical to `movie` on every repeat import, and the profile
    that came with it would be rewritten to point at the copy.
    """


@dataclass(frozen=True, slots=True)
class PlannedEntry:
    kind: EntryKind
    source_name: str
    destination_name: str
    disposition: Disposition


@dataclass(frozen=True, slots=True)
class BundleManifest:
    export_version: int
    app_version: str
    schema_version: int
    created: str
    credentials_included: bool
    profiles: tuple[str, ...]
    templates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BundleContents:
    """A bundle read into memory, having been refused if it is not one.

    Read whole before anything is written, because the alternative is a
    half-applied import: three profiles land, the fourth turns out to be
    malformed, and the user is left working out which three they now have.
    """

    manifest: BundleManifest
    profiles: dict[str, str]
    templates: dict[str, str]
    source: Path


@dataclass(frozen=True, slots=True)
class ImportPlan:
    entries: tuple[PlannedEntry, ...]
    credentials_missing: bool

    def for_kind(self, kind: EntryKind) -> tuple[PlannedEntry, ...]:
        return tuple(entry for entry in self.entries if entry.kind is kind)


@dataclass(frozen=True, slots=True)
class ExportOutcome:
    archive: Path
    profiles: tuple[str, ...]
    templates: tuple[str, ...]
    missing_templates: tuple[str, ...]
    blanked: tuple[str, ...]
    credentials_included: bool
    """What the user asked for, which is not the same as what was removed.

    A profile with nothing configured yet blanks nothing, and reading that as
    "credentials were kept" would warn someone about a bundle that holds none.
    """


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    plan: ImportPlan
    written: tuple[Path, ...]
    archived: tuple[Path, ...]
    cleared: tuple[str, ...]
    missing_templates: tuple[str, ...]
    unavailable_plugins: tuple[str, ...]
    credentials_missing: bool


class ProfileValidator(Protocol):
    """The one thing importing needs from `ConfigManager`.

    A protocol rather than the class so that this module does not depend on a
    fully constructed manager, and so a test can prove the refusal path without
    building one.
    """

    def validate_profile_document(
        self,
        document: MutableMapping[str, Any],
        dry_run: bool = True,
    ) -> MutableMapping[str, Any]: ...


# ---------------------------------------------------------------------------
# what happened, in words


def render_export_summary(outcome: ExportOutcome) -> str:
    """What an export did, for the dialog that reports it.

    Composed here rather than in the dialog for the same reason the migration
    composes its summary in `layout_apply`: the rules about what was and was
    not included live in this module, and a second description of them written
    next to a `QTextEdit` would drift from the first.
    """
    lines = [f"Saved to {outcome.archive}", ""]
    lines.append(f"Profiles ({len(outcome.profiles)}):")
    lines.extend(f"  {name}" for name in outcome.profiles)
    if outcome.templates:
        lines.append("")
        lines.append(f"Templates ({len(outcome.templates)}):")
        lines.extend(f"  {name}" for name in outcome.templates)
    if outcome.missing_templates:
        lines.append("")
        lines.append("Templates named by a profile but not on disk, so not included:")
        lines.extend(f"  {name}" for name in outcome.missing_templates)
    lines.append("")
    if outcome.credentials_included:
        lines.append(
            "This bundle carries your credentials in full -- tracker keys, "
            "passkeys, passwords and announce URLs. Treat it as you would the "
            "credentials themselves."
        )
    elif outcome.blanked:
        lines.append(f"Credentials removed ({len(outcome.blanked)}):")
        lines.extend(f"  {key}" for key in outcome.blanked)
        lines.append("")
        lines.append(
            "Your releaser name and group tag are not credentials and are "
            "still in the bundle."
        )
    else:
        lines.append("There were no credentials in these profiles to remove.")
    return "\n".join(lines)


def render_import_summary(outcome: ImportOutcome) -> str:
    """What an import did, and what it left for the user to do."""
    lines: list[str] = []
    for kind in (EntryKind.PROFILE, EntryKind.TEMPLATE):
        entries = outcome.plan.for_kind(kind)
        if not entries:
            continue
        lines.append(f"{kind.value}s:")
        for entry in entries:
            if entry.destination_name == entry.source_name:
                lines.append(
                    f"  {entry.source_name} -- {entry.disposition.value.lower()}"
                )
            else:
                lines.append(
                    f"  {entry.source_name} -> {entry.destination_name} "
                    f"-- {entry.disposition.value.lower()}"
                )
        lines.append("")

    if outcome.archived:
        lines.append("Replaced, and kept a copy of what was there:")
        lines.extend(f"  {path}" for path in outcome.archived)
        lines.append("")

    if outcome.cleared:
        lines.append(
            "Settings cleared because they named a location on the machine "
            "that exported them:"
        )
        lines.extend(f"  {key}" for key in outcome.cleared)
        lines.append(
            "  Set these again under Settings -> General and Settings -> Dependencies."
        )
        lines.append("")

    if outcome.missing_templates:
        lines.append("Templates an imported profile names but which are not here:")
        lines.extend(f"  {name}" for name in outcome.missing_templates)
        lines.append("")

    if outcome.unavailable_plugins:
        lines.append("Plugins an imported profile selects but which are not here:")
        lines.extend(f"  {name}" for name in outcome.unavailable_plugins)
        lines.append(
            "  Those capabilities fall back to NfoForge's own until the "
            "plugins are installed. The selections are kept."
        )
        lines.append("")

    if outcome.credentials_missing:
        lines.append(
            "This bundle was exported without credentials. Tracker API keys, "
            "passkeys, passwords and announce URLs are empty and have to be "
            "set under Settings -> Trackers before anything can be uploaded."
        )
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# reading the data folder


def available_profiles(paths: AppPaths) -> tuple[str, ...]:
    """Every profile name that could be exported, sorted."""
    try:
        return tuple(
            sorted(
                path.stem
                for path in paths.user_configs.glob(f"*{PROFILE_SUFFIX}")
                if path.is_file()
            )
        )
    except OSError as error:
        raise TransferError(f"Could not list your profiles: {error}") from error


def referenced_templates(document: Mapping[str, Any]) -> set[str]:
    """Every template stem a profile names, at any depth."""
    found: set[str] = set()
    _collect_templates(document, found)
    return found


def selected_plugins(document: Mapping[str, Any]) -> set[str]:
    """Every plugin id a profile selects for one of its capabilities.

    Read straight off the `[plugins]` table rather than through `PluginSettings`,
    because this runs against a document that has not been decoded -- and
    because a capability added later lands here without this being told about
    it, the same way the template sweep works.
    """
    table = document.get(PLUGINS_TABLE)
    if not isinstance(table, Mapping):
        return set()
    return {
        value.strip()
        for value in table.values()
        if isinstance(value, str) and value.strip()
    }


def _collect_templates(value: Any, found: set[str]) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == TEMPLATE_KEY and isinstance(child, str) and child.strip():
                found.add(child.strip())
            else:
                _collect_templates(child, found)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _collect_templates(child, found)


# ---------------------------------------------------------------------------
# export


def export_bundle(
    paths: AppPaths,
    profile_names: Sequence[str],
    destination: Path,
    include_credentials: bool = False,
) -> ExportOutcome:
    """Write the named profiles, and the templates they use, to one archive.

    Not threaded. A bundle is text measured in kilobytes, unlike the legacy
    import, which is threaded because it copies a hand-assembled toolchain.
    """
    if not profile_names:
        raise TransferError("Select at least one profile to export.")

    documents: dict[str, MutableMapping[str, Any]] = {}
    for name in profile_names:
        source = paths.user_configs / f"{name}{PROFILE_SUFFIX}"
        try:
            documents[name] = tomlkit.parse(source.read_text(encoding="utf-8"))
        except OSError as error:
            raise TransferError(
                f"Profile '{name}' could not be read: {error}"
            ) from error
        except Exception as error:
            raise TransferError(
                f"Profile '{name}' is not valid TOML: {error}"
            ) from error

    blanked: list[str] = []
    if not include_credentials:
        for name, document in documents.items():
            blanked.extend(f"{name}: {key}" for key in blank_credentials(document))

    wanted: set[str] = set()
    for document in documents.values():
        wanted |= referenced_templates(document)

    templates: dict[str, str] = {}
    missing: list[str] = []
    for stem in sorted(wanted):
        source = paths.templates / f"{stem}{TEMPLATE_SUFFIX}"
        try:
            templates[stem] = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            # Reported, never fatal. A profile naming a template the user has
            # since deleted is an ordinary state to be in, and refusing the
            # whole export over it would make a stale reference unexportable
            # rather than fixable.
            missing.append(stem)

    manifest = BundleManifest(
        export_version=EXPORT_VERSION,
        app_version=str(__version__),
        schema_version=TomlConfigCodec.SCHEMA_VERSION,
        created=datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        credentials_included=include_credentials,
        profiles=tuple(documents),
        templates=tuple(templates),
    )

    # Appended rather than set with `with_suffix`, which replaces everything
    # after the last dot: a bundle the user named "my setup v1.2" would be
    # written as "my setup v1.zip".
    if destination.suffix.casefold() != ".zip":
        destination = destination.with_name(f"{destination.name}.zip")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(EXPORT_MANIFEST_NAME, _render_manifest(manifest))
            for name, document in documents.items():
                archive.writestr(
                    f"{PROFILES_DIR_NAME}/{name}{PROFILE_SUFFIX}",
                    TomlConfigCodec.dumps(document),
                )
            for stem, text in templates.items():
                archive.writestr(f"{TEMPLATES_DIR_NAME}/{stem}{TEMPLATE_SUFFIX}", text)
    except OSError as error:
        raise TransferError(f"The bundle could not be written: {error}") from error

    LOG.info(
        LOG.LOG_SOURCE.BE,
        f"Exported {len(documents)} profile(s) to {destination} "
        f"(credentials {'included' if include_credentials else 'stripped'})",
    )
    return ExportOutcome(
        archive=destination,
        profiles=manifest.profiles,
        templates=manifest.templates,
        missing_templates=tuple(missing),
        blanked=tuple(blanked),
        credentials_included=include_credentials,
    )


def _render_manifest(manifest: BundleManifest) -> str:
    document = tomlkit.document()
    document["export_version"] = manifest.export_version
    document["app_version"] = manifest.app_version
    document["schema_version"] = manifest.schema_version
    document["created"] = manifest.created
    document["credentials_included"] = manifest.credentials_included
    document["profiles"] = list(manifest.profiles)
    document["templates"] = list(manifest.templates)
    return tomlkit.dumps(document)


# ---------------------------------------------------------------------------
# reading a bundle


def read_bundle(source: Path) -> BundleContents:
    """Read and vet a bundle, writing nothing.

    A bare `.toml` is accepted as well as a `.zip`: `Save As` produces exactly
    that, users already have them, and reading one as a single-profile bundle
    with no templates costs one branch.
    """
    if source.suffix.casefold() == PROFILE_SUFFIX:
        return _read_bare_profile(source)
    return _read_archive(source)


def _read_bare_profile(source: Path) -> BundleContents:
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise TransferError(f"'{source.name}' could not be read: {error}") from error

    name = _checked_stem(source.stem, "profile")
    schema_version = _declared_schema_version(name, text)
    manifest = BundleManifest(
        export_version=EXPORT_VERSION,
        app_version="",
        schema_version=schema_version,
        created="",
        # Unknowable for a bare profile, and the honest answer is the one that
        # does not tell a user their credentials were removed when they were
        # not. `Save As` writes them in full.
        credentials_included=True,
        profiles=(name,),
        templates=(),
    )
    return BundleContents(
        manifest=manifest, profiles={name: text}, templates={}, source=source
    )


def _read_archive(source: Path) -> BundleContents:
    try:
        with zipfile.ZipFile(source) as archive:
            members = safe_members(archive, MAX_BUNDLE_ENTRIES, MAX_BUNDLE_BYTES)
            payloads = {
                str(PurePosixPath(info.filename)): read_member(
                    archive, info, MAX_BUNDLE_BYTES
                )
                for info in members
            }
    except UnsafeArchiveError as error:
        raise TransferError(str(error)) from error
    except zipfile.BadZipFile as error:
        raise TransferError(
            f"'{source.name}' is not a readable zip: {error}"
        ) from error
    except OSError as error:
        raise TransferError(f"'{source.name}' could not be read: {error}") from error

    raw_manifest = payloads.pop(EXPORT_MANIFEST_NAME, None)
    if raw_manifest is None:
        raise TransferError(
            f"'{source.name}' is not an NfoForge configuration bundle: it has "
            f"no {EXPORT_MANIFEST_NAME}."
        )
    manifest = _parse_manifest(raw_manifest, source.name)

    profiles: dict[str, str] = {}
    templates: dict[str, str] = {}
    for name, payload in payloads.items():
        parts = PurePosixPath(name).parts
        if len(parts) != 2:
            raise TransferError(_not_part_of_a_bundle(source.name, name))
        folder, filename = parts
        try:
            text = payload.decode("utf-8")
        except UnicodeError as error:
            raise TransferError(f"'{name}' is not valid UTF-8: {error}") from error

        folded = filename.casefold()
        if folder == PROFILES_DIR_NAME and folded.endswith(PROFILE_SUFFIX):
            profiles[_checked_stem(PurePosixPath(filename).stem, "profile")] = text
        elif folder == TEMPLATES_DIR_NAME and folded.endswith(TEMPLATE_SUFFIX):
            templates[_checked_stem(PurePosixPath(filename).stem, "template")] = text
        else:
            raise TransferError(_not_part_of_a_bundle(source.name, name))

    if not profiles:
        raise TransferError(f"'{source.name}' holds no profiles.")

    for name, text in profiles.items():
        _declared_schema_version(name, text)

    return BundleContents(
        manifest=manifest, profiles=profiles, templates=templates, source=source
    )


def _not_part_of_a_bundle(archive_name: str, entry: str) -> str:
    return (
        f"'{archive_name}' holds '{entry}', which is not part of a "
        "configuration bundle."
    )


def _parse_manifest(payload: bytes, archive_name: str) -> BundleManifest:
    try:
        document = tomllib.loads(payload.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as error:
        raise TransferError(
            f"The manifest in '{archive_name}' could not be read: {error}"
        ) from error

    export_version = document.get("export_version")
    if not isinstance(export_version, int) or isinstance(export_version, bool):
        raise TransferError(
            f"The manifest in '{archive_name}' declares no bundle version."
        )
    if export_version > EXPORT_VERSION:
        raise TransferError(
            f"'{archive_name}' was made by a newer version of NfoForge "
            f"(bundle format {export_version}; this build reads up to "
            f"{EXPORT_VERSION}). Update NfoForge and try again."
        )

    schema_version = document.get("schema_version", TomlConfigCodec.SCHEMA_VERSION)
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise TransferError(
            f"The manifest in '{archive_name}' declares an unreadable "
            "configuration version."
        )

    return BundleManifest(
        export_version=export_version,
        app_version=str(document.get("app_version", "")),
        schema_version=schema_version,
        created=str(document.get("created", "")),
        credentials_included=bool(document.get("credentials_included", True)),
        profiles=tuple(_strings(document.get("profiles"))),
        templates=tuple(_strings(document.get("templates"))),
    )


def _strings(value: Any) -> Iterable[str]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _declared_schema_version(name: str, text: str) -> int:
    """The schema a profile declares, refusing one this build cannot read.

    Checked while reading rather than while writing, so a bundle from a future
    release is rejected with a sentence about updating instead of a schema
    error on the next launch. Migration *up* is the load path's job and works;
    there is no migration down.
    """
    try:
        document = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, UnicodeError) as error:
        raise TransferError(f"Profile '{name}' is not valid TOML: {error}") from error
    try:
        version = document_version(document)
    except (TypeError, ValueError) as error:
        raise TransferError(
            f"Profile '{name}' declares an unreadable schema version: {error}"
        ) from error
    if version > TomlConfigCodec.SCHEMA_VERSION:
        raise TransferError(
            f"Profile '{name}' was written by a newer version of NfoForge "
            f"(configuration version {version}; this build reads up to "
            f"{TomlConfigCodec.SCHEMA_VERSION}). Update NfoForge and try again."
        )
    return version


def _checked_stem(stem: str, description: str) -> str:
    """A name from a bundle, refused unless it can be a file of its own.

    A bundle is written by someone else, and every name in one becomes a
    filename in the user's data folder. Directory parts are already gone by the
    time this is called, so this is about what is left: nothing empty, nothing
    that is a relative reference, and nothing Windows will not create.
    """
    cleaned = stem.strip()
    if not cleaned or cleaned in {".", ".."}:
        raise TransferError(f"The bundle holds a {description} with no usable name.")
    if any(character in cleaned for character in _ILLEGAL_NAME_CHARACTERS):
        raise TransferError(
            f"The bundle holds a {description} named '{stem}', which is not a "
            "usable file name."
        )
    if cleaned.casefold() in _RESERVED_STEMS:
        raise TransferError(
            f"The bundle holds a {description} named '{stem}', which Windows "
            "reserves for a device."
        )
    return cleaned


# ---------------------------------------------------------------------------
# import


def plan_import(
    paths: AppPaths,
    contents: BundleContents,
    policy: NameConflict,
) -> ImportPlan:
    """What importing `contents` would do, without doing any of it.

    Nothing is ever replaced without being archived first -- the same contract
    the layout migration keeps. `KEEP_BOTH` is the default because it is the
    only one of the three that cannot lose anything.
    """
    entries: list[PlannedEntry] = []
    taken_profiles = {
        path.stem.casefold() for path in _existing(paths.user_configs, PROFILE_SUFFIX)
    }
    taken_templates = {
        path.stem.casefold() for path in _existing(paths.templates, TEMPLATE_SUFFIX)
    }

    for kind, names, taken in (
        (EntryKind.PROFILE, sorted(contents.profiles), taken_profiles),
        (EntryKind.TEMPLATE, sorted(contents.templates), taken_templates),
    ):
        for name in names:
            if kind is EntryKind.TEMPLATE and _template_already_here(
                paths, name, contents.templates[name]
            ):
                entries.append(PlannedEntry(kind, name, name, Disposition.UNCHANGED))
                continue
            destination, disposition = _resolve_name(name, taken, policy)
            if disposition is not Disposition.SKIPPED:
                taken.add(destination.casefold())
            entries.append(PlannedEntry(kind, name, destination, disposition))

    return ImportPlan(
        entries=tuple(entries),
        credentials_missing=not contents.manifest.credentials_included,
    )


def _template_already_here(paths: AppPaths, stem: str, incoming: str) -> bool:
    """Whether the template on disk is the incoming one, character for character.

    Line endings are normalised before comparing, because a template that has
    been through a zip on one platform and a checkout on another differs only
    in those. Without this, importing the same bundle twice would fill the
    templates directory with `movie (2)`, `movie (3)` and so on, and repoint
    each imported profile at the newest copy.
    """
    existing = paths.templates / f"{stem}{TEMPLATE_SUFFIX}"
    try:
        current = existing.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    return current.replace("\r\n", "\n") == incoming.replace("\r\n", "\n")


def _existing(directory: Path, suffix: str) -> tuple[Path, ...]:
    try:
        return tuple(directory.glob(f"*{suffix}"))
    except OSError:
        return ()


def _resolve_name(
    name: str, taken: set[str], policy: NameConflict
) -> tuple[str, Disposition]:
    if name.casefold() not in taken:
        return name, Disposition.NEW
    if policy is NameConflict.SKIP:
        return name, Disposition.SKIPPED
    if policy is NameConflict.REPLACE:
        return name, Disposition.REPLACED
    counter = 2
    while f"{name} ({counter})".casefold() in taken:
        counter += 1
    return f"{name} ({counter})", Disposition.RENAMED


def apply_import(
    paths: AppPaths,
    contents: BundleContents,
    plan: ImportPlan,
    validator: ProfileValidator,
) -> ImportOutcome:
    """Carry out `plan`, having first proved every profile in it would load.

    Every profile is migrated, cleared of machine-specific paths and validated
    *before* the first byte is written. A profile that cannot be made to load
    takes the whole import down with a message naming it, leaving the data
    folder as it was -- which is recoverable, unlike a launch that fails on a
    profile the user has never opened.
    """
    try:
        default_document = tomllib.loads(
            paths.default_config.read_text(encoding="utf-8")
        )
    except (OSError, tomllib.TOMLDecodeError, UnicodeError) as error:
        raise TransferError(
            f"The packaged default configuration could not be read: {error}"
        ) from error

    renames = {
        entry.source_name: entry.destination_name
        for entry in plan.for_kind(EntryKind.TEMPLATE)
        if entry.destination_name != entry.source_name
        and entry.disposition is not Disposition.SKIPPED
    }

    prepared: dict[str, str] = {}
    cleared: list[str] = []
    for entry in plan.for_kind(EntryKind.PROFILE):
        if entry.disposition is Disposition.SKIPPED:
            continue
        text, touched = _prepare_profile(
            entry.source_name,
            contents.profiles[entry.source_name],
            default_document,
            validator,
            renames,
        )
        prepared[entry.destination_name] = text
        cleared.extend(f"{entry.destination_name}: {key}" for key in touched)

    written: list[Path] = []
    archived: list[Path] = []
    for entry in plan.entries:
        if entry.disposition in (Disposition.SKIPPED, Disposition.UNCHANGED):
            continue
        if entry.kind is EntryKind.PROFILE:
            target = paths.user_configs / f"{entry.destination_name}{PROFILE_SUFFIX}"
            payload = prepared[entry.destination_name]
        else:
            target = paths.templates / f"{entry.destination_name}{TEMPLATE_SUFFIX}"
            payload = contents.templates[entry.source_name]

        if entry.disposition is Disposition.REPLACED and target.exists():
            archived.append(_archive(target))
        try:
            atomic_write_text(target, payload)
        except OSError as error:
            raise TransferError(
                f"'{target.name}' could not be written: {error}"
            ) from error
        written.append(target)

    wanted: set[str] = set()
    selected: set[str] = set()
    for text in prepared.values():
        document = tomllib.loads(text)
        wanted |= referenced_templates(document)
        selected |= selected_plugins(document)
    on_disk = {path.stem for path in _existing(paths.templates, TEMPLATE_SUFFIX)}

    # Measured against what is on disk rather than against
    # `PluginManager.plugin_ids`, which only knows what was loaded -- and
    # nothing is loaded when external plugins are switched off. Asking the
    # manager would report every selection as missing for a user who simply has
    # plugins disabled, which is both noisy and wrong.
    present = {
        found.plugin_id
        for directory in (paths.plugins, paths.plugin_examples)
        for found in declared_plugins(directory)
    }

    LOG.info(
        LOG.LOG_SOURCE.BE, f"Imported {len(written)} file(s) from {contents.source}"
    )
    outcome = ImportOutcome(
        plan=plan,
        written=tuple(written),
        archived=tuple(archived),
        cleared=tuple(cleared),
        missing_templates=tuple(sorted(wanted - on_disk)),
        unavailable_plugins=tuple(sorted(selected - present)),
        credentials_missing=plan.credentials_missing,
    )
    _record_import(paths, outcome)
    return outcome


def _record_import(paths: AppPaths, outcome: ImportOutcome) -> None:
    """Keep a copy of the summary the user is about to be shown once.

    The migration makes the same promise for the same reason: its window is
    shown once and nothing on it is rechecked, so a transcript goes to
    `logs/migration.log`, which log tidying leaves alone. An import from
    Settings is the same shape of event -- it changes the data folder and then
    the account of it disappears -- so it is appended to the same file rather
    than a second one the user would have to know about.

    Best effort throughout. By the time this runs everything is already on
    disk, so a log that cannot be written costs a transcript and nothing else;
    failing the import over it would trade something that worked for nothing.
    """
    destination = paths.logs / SUMMARY_LOG_NAME
    try:
        paths.logs.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with destination.open("a", encoding="utf-8") as handle:
            handle.write(f"===== {stamp} configuration import =====\n\n")
            handle.write(render_import_summary(outcome))
            handle.write("\n\n")
    except OSError as error:
        LOG.warning(
            LOG.LOG_SOURCE.BE,
            f"Could not keep a copy of the import summary at {destination}, so "
            f"it will only be shown once: {error}",
        )


def _archive(target: Path) -> Path:
    """Move an existing file aside, reusing the manager's own backup layout.

    Named for profiles because that is what it was written for, but it is a
    timestamped copy into an `old_configs` folder beside the file, which is
    exactly as useful for a template. Used for both rather than growing a
    second convention the user would have to learn.

    Imported inside the function rather than at module scope: `ConfigManager`
    reaches into the plugin package, which imports back through `src.config`,
    and this module is read while that is still being set up.
    """
    from src.config.config import ConfigManager

    backup = ConfigManager.archive_profile(target)
    target.unlink()
    return backup


def _prepare_profile(
    name: str,
    text: str,
    default_document: Mapping[str, Any],
    validator: ProfileValidator,
    template_renames: Mapping[str, str],
) -> tuple[str, tuple[str, ...]]:
    """Migrate, repoint, clear and validate one incoming profile.

    Returns the text to write and the machine-specific keys that were cleared.
    """
    try:
        document = tomlkit.parse(text)
    except Exception as error:
        raise TransferError(f"Profile '{name}' is not valid TOML: {error}") from error

    if document_version(document) < TomlConfigCodec.SCHEMA_VERSION:
        try:
            migrated, unmapped = migrate_document(document, default_document)
        except Exception as error:
            raise TransferError(
                f"Profile '{name}' could not be brought up to the current "
                f"configuration version: {type(error).__name__}: {error}"
            ) from error
        if unmapped:
            raise TransferError(
                f"Profile '{name}' could not be brought up to the current "
                "configuration version; these sections could not be mapped: "
                + ", ".join(sorted(set(unmapped)))
            )
        document = tomlkit.parse(TomlConfigCodec.dumps(migrated))

    _repoint_templates(document, template_renames)
    cleared = _clear_machine_specific(document)
    serialized = TomlConfigCodec.dumps(document)

    try:
        validator.validate_profile_document(tomlkit.parse(serialized))
    except Exception as error:
        raise TransferError(
            f"Profile '{name}' would not load: {type(error).__name__}: {error}"
        ) from error

    return serialized, cleared


def _repoint_templates(
    document: MutableMapping[str, Any], renames: Mapping[str, str]
) -> None:
    """Point an imported profile at the templates that arrived with it.

    A template whose name was already in use lands under a new one, and a
    profile still naming the old one would then render with the template that
    was already there -- a different NFO, from the same settings, with nothing
    on screen saying so. The profile follows its own templates instead.
    """
    if renames:
        _repoint_value(document, renames)


def _repoint_value(value: Any, renames: Mapping[str, str]) -> None:
    if isinstance(value, MutableMapping):
        for key, child in value.items():
            if key == TEMPLATE_KEY and isinstance(child, str):
                replacement = renames.get(child.strip())
                if replacement is not None:
                    value[key] = replacement
            else:
                _repoint_value(child, renames)
    elif isinstance(value, list):
        for child in value:
            _repoint_value(child, renames)


def _clear_machine_specific(document: MutableMapping[str, Any]) -> tuple[str, ...]:
    """Empty every setting that names a path on the machine that exported it.

    Done on import rather than on export, because an export is also how a user
    backs their own configuration up, and a backup that came home having lost
    its working directory and its tool locations would be a poor one. The
    receiving machine is where those paths are certainly wrong: the working
    directory falls back to the workspace and the dependencies are found again
    by `FindDependencies`, whereas a path left pointing at a stranger's drive
    fails later, during a run.
    """
    cleared: list[str] = []
    for table_name, keys in _MACHINE_SPECIFIC:
        table = document.get(table_name)
        if not isinstance(table, MutableMapping):
            continue
        for key in keys if keys is not None else tuple(table.keys()):
            value = table.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            table[key] = ""
            cleared.append(f"{table_name}.{key}")
    return tuple(cleared)
