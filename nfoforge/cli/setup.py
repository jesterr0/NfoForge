"""`nfoforge setup`: what the desktop app does the first time it starts.

In the same order: bring the data folder up to date, importing from a
previous installation if asked to (or, for a folder already set up, import
one the way the desktop app's Settings does); create a profile if there is none; upgrade
profiles written by an older NfoForge; and update templates that use renamed
tokens. Each step does nothing when there is nothing to do, so running it
again is harmless.

It is its own command rather than something `upload` does on the way. A
migration copies a whole installation and asks a question about it, which is
not something a scheduled upload should start doing unannounced.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import tomlkit

from nfoforge.backend.utils.template_token_migration import (
    migrate_templates,
    scan_template_dir,
)
from nfoforge.cli.app import PROGRAM, CliError
from nfoforge.config.codec import TomlConfigCodec
from nfoforge.config.config import ConfigManager
from nfoforge.config.layout_apply import (
    SUMMARY_LOG_NAME,
    MigrationError,
    import_legacy,
    render_summary,
    startup_migration,
)
from nfoforge.config.layout_migration import LegacyInstall, recognise_legacy_install
from nfoforge.config.layout_version import LayoutRecordError, migration_pending
from nfoforge.config.migrations import document_version
from nfoforge.config.paths import AppPaths
from nfoforge.exceptions import ConfigError

Ask = Callable[[str], str]
"""Puts a question at the terminal and returns the line typed."""


@dataclass(frozen=True, slots=True)
class SetupOptions:
    import_from: Path | None = None
    """A previous installation to import from, instead of asking."""
    no_import: bool = False
    """Start fresh instead of asking."""
    update_templates: bool = False
    """Update templates that use renamed tokens, instead of asking."""


def run_setup(
    options: SetupOptions, paths: AppPaths, out: TextIO, ask: Ask | None
) -> None:
    """Every first-launch step, in order. `ask` is None when nobody can answer.

    Raises `CliError` for anything that stops it, before or between steps.
    """
    out.write(f"Data folder: {paths.state_root}\n")
    _migrate_data_folder(options, paths, out, ask)
    _ensure_a_profile(paths, out)
    _upgrade_profiles(paths, out)
    _update_templates(options, paths, out, ask)
    out.write("Setup is complete.\n")


# --------------------------------------------------------------------------
# the data folder
# --------------------------------------------------------------------------
def _migrate_data_folder(
    options: SetupOptions, paths: AppPaths, out: TextIO, ask: Ask | None
) -> None:
    try:
        pending = migration_pending(paths.state_root)
    except LayoutRecordError as error:
        raise CliError(f"The data folder record cannot be read: {error}") from error
    if not pending:
        if options.import_from is not None:
            _import_into_current(_recognise(options.import_from), paths, out)
        else:
            out.write("The data folder is up to date.\n")
        return

    # every way the question can be answered is settled before anything is
    # copied, so a bad answer stops setup with nothing done
    chosen: LegacyInstall | None = None
    if options.import_from is not None:
        chosen = _recognise(options.import_from)
    elif not options.no_import and ask is None:
        raise CliError(
            "The data folder has to be set up, and nobody is here to say whether "
            "to import a previous installation. Pass --import-from PATH, or "
            "--no-import to start fresh."
        )

    def decide(found: LegacyInstall | None) -> LegacyInstall | None:
        if options.import_from is not None:
            return chosen
        if options.no_import or ask is None:
            return None
        return _ask_where_to_import(found, out, ask)

    def progress(step: str) -> None:
        out.write(f"  {step}\n")

    try:
        run = startup_migration(paths, decide, progress=progress)
    except MigrationError as error:
        raise CliError(
            "The data folder could not be set up, so setup stopped rather than "
            f"leave some of it missing. Nothing was deleted.\n{error}"
        ) from error
    if run is not None:
        out.write(render_summary(run, saved_to=paths.logs / SUMMARY_LOG_NAME) + "\n")


def _import_into_current(legacy: LegacyInstall, paths: AppPaths, out: TextIO) -> None:
    """Import a previous installation into a folder that is already set up.

    What the desktop app's Settings import does: nothing already here is
    overwritten, and anything that would clash is set aside instead.
    """
    try:
        run = import_legacy(paths, legacy, progress=_progress(out))
    except MigrationError as error:
        raise CliError(
            f"The import stopped part way. Nothing was deleted.\n{error}"
        ) from error
    out.write(render_summary(run, saved_to=paths.logs / SUMMARY_LOG_NAME) + "\n")


def _progress(out: TextIO) -> Callable[[str], None]:
    def progress(step: str) -> None:
        out.write(f"  {step}\n")

    return progress


def _recognise(folder: Path) -> LegacyInstall:
    found = recognise_legacy_install(folder.expanduser())
    if found is None:
        raise CliError(f"No previous NfoForge installation was found in {folder}")
    return found


def _ask_where_to_import(
    found: LegacyInstall | None, out: TextIO, ask: Ask
) -> LegacyInstall | None:
    """The desktop app's first-launch question, at a terminal.

    A folder that holds no installation is asked about again rather than taken
    as a decision to start fresh, as the desktop app does.
    """
    out.write(
        "NfoForge keeps your settings in their own folder, outside the "
        "application. Settings can be copied in from a previous installation; "
        "that installation is not changed.\n"
    )
    if found is not None:
        out.write(f"A previous installation was found at: {found.root}\n")
        answer = ask("Import it? [Y/n], or type a different folder: ").strip()
        if answer.casefold() in {"", "y", "yes"}:
            return found
        if answer.casefold() in {"n", "no"}:
            return None
    else:
        out.write("No previous installation was found.\n")
        answer = ask("Folder to import from (leave empty to start fresh): ").strip()

    while answer:
        candidate = recognise_legacy_install(Path(answer).expanduser())
        if candidate is not None:
            return candidate
        out.write(f"No NfoForge installation was found in {answer}\n")
        answer = ask("Folder to import from (leave empty to start fresh): ").strip()
    return None


# --------------------------------------------------------------------------
# profiles
# --------------------------------------------------------------------------
def _profiles(paths: AppPaths) -> list[Path]:
    if not paths.user_configs.is_dir():
        return []
    return sorted(paths.user_configs.glob("*.toml"))


def _ensure_a_profile(paths: AppPaths, out: TextIO) -> None:
    if _profiles(paths):
        return
    try:
        config = ConfigManager(None, paths)
    except ConfigError as error:
        raise CliError(f"A profile could not be created: {error}") from error
    name = config.program.current_config
    out.write(
        f"Created profile '{name}': {paths.user_configs / f'{name}.toml'}\n"
        "  Add your trackers, templates and image hosts to it before uploading.\n"
    )


def _upgrade_profiles(paths: AppPaths, out: TextIO) -> None:
    """Upgrade every profile an older NfoForge wrote, as opening it would.

    Loading a profile is what upgrades it, and loading one also makes it the
    active profile. The program file is put back afterwards, so which profile
    the desktop app opens is not changed by setup.
    """
    current = TomlConfigCodec.SCHEMA_VERSION
    outdated: list[Path] = []
    for profile in _profiles(paths):
        try:
            version = document_version(
                tomlkit.parse(profile.read_text(encoding="utf-8"))
            )
        except Exception as error:
            out.write(f"Profile '{profile.stem}' could not be read: {error}\n")
            continue
        if version > current:
            out.write(
                f"Profile '{profile.stem}' was written by a newer NfoForge and "
                "cannot be used by this one.\n"
            )
        elif version < current:
            outdated.append(profile)
    if not outdated:
        return

    program = paths.program
    saved_program = program.read_bytes() if program.is_file() else None
    try:
        for profile in outdated:
            try:
                ConfigManager(profile.stem, paths)
            except ConfigError as error:
                out.write(f"Profile '{profile.stem}' could not be upgraded: {error}\n")
            else:
                out.write(
                    f"Upgraded profile '{profile.stem}'; the previous version was "
                    "kept in old_configs.\n"
                )
    finally:
        if saved_program is not None:
            program.write_bytes(saved_program)


# --------------------------------------------------------------------------
# templates
# --------------------------------------------------------------------------
def _update_templates(
    options: SetupOptions, paths: AppPaths, out: TextIO, ask: Ask | None
) -> None:
    reports = [
        report for report in scan_template_dir(paths.templates) if report.has_findings
    ]
    if not reports:
        return
    names = ", ".join(report.path.name for report in reports)
    out.write(f"{len(reports)} template(s) use tokens that were renamed: {names}\n")

    update = options.update_templates
    if not update and ask is not None:
        answer = ask("Update them? A copy of each is kept. [y/N] ")
        update = answer.strip().casefold() in {"y", "yes"}
    if not update:
        out.write(
            f"  Left as they are. Update them with: {PROGRAM} setup "
            "--update-templates\n"
        )
        return

    migrated = migrate_templates(reports)
    out.write(f"  Updated {len(migrated)} template(s).\n")
    left = len(reports) - len(migrated)
    if left:
        out.write(
            f"  {left} were left unchanged: they could not be written, or only "
            "use tokens that were removed and have no replacement.\n"
        )
