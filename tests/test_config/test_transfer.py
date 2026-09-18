"""Exporting a configuration and importing one back.

The rules being locked down here are the ones that cost something when they
break: a credential leaving the machine, a bundle overwriting work that was
already here, and a profile landing on disk that the next launch cannot load.
"""

from pathlib import Path
import zipfile

import pytest
import tomlkit

from src.config.codec import TomlConfigCodec
from src.config.config import ConfigManager
from src.config.layout_apply import SUMMARY_LOG_NAME
from src.config.paths import ConfigPaths
from src.config.transfer import (
    EXPORT_MANIFEST_NAME,
    EXPORT_VERSION,
    Disposition,
    EntryKind,
    NameConflict,
    TransferError,
    apply_import,
    available_profiles,
    export_bundle,
    plan_import,
    read_bundle,
    referenced_templates,
    render_export_summary,
    render_import_summary,
)
from tests.repo_paths import CONFIG_FIXTURE_DIR, build_app_paths


@pytest.fixture(autouse=True)
def _no_dependency_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep `FindDependencies` off the host's PATH.

    Left alone it fills `[dependencies]` from whatever happens to be installed
    on the machine running the suite, which makes "these paths were cleared"
    assertions depend on the runner.
    """
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )


def _manager(tmp_path: Path, name: str = "mysetup") -> ConfigManager:
    return ConfigManager(name, build_app_paths(tmp_path))


def _edit(paths: ConfigPaths, name: str, **general: str) -> None:
    """Put credentials, a template reference and machine paths into a profile."""
    path = paths.user_configs / f"{name}.toml"
    document = tomlkit.parse(path.read_text(encoding="utf-8"))
    aither = document["tracker"]["aither"]  # type: ignore[index]
    aither["api_key"] = "SECRET-KEY"  # type: ignore[index]
    aither["announce_url"] = "https://aither.cc/announce/PASSKEY"  # type: ignore[index]
    aither["nfo_template"] = "movie"  # type: ignore[index]
    document["general"]["releasers_name"] = "someone"  # type: ignore[index]
    document["general"]["working_dir"] = "D:/elsewhere"  # type: ignore[index]
    document["dependencies"]["ffmpeg"] = "D:/tools/ffmpeg.exe"  # type: ignore[index]
    for key, value in general.items():
        document["general"][key] = value  # type: ignore[index]
    path.write_text(tomlkit.dumps(document), encoding="utf-8")


def _template(paths: ConfigPaths, stem: str, text: str = "hello") -> Path:
    paths.templates.mkdir(parents=True, exist_ok=True)
    target = paths.templates / f"{stem}.txt"
    target.write_text(text, encoding="utf-8")
    return target


def _profile(paths: ConfigPaths, name: str) -> dict:
    return tomlkit.parse(
        (paths.user_configs / f"{name}.toml").read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# export


def test_a_bundle_carries_the_profile_and_the_templates_it_names(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    _edit(manager.paths, "mysetup")
    _template(manager.paths, "movie")
    _template(manager.paths, "unused")

    outcome = export_bundle(manager.paths, ["mysetup"], tmp_path / "bundle")

    with zipfile.ZipFile(outcome.archive) as archive:
        assert sorted(archive.namelist()) == [
            EXPORT_MANIFEST_NAME,
            "profiles/mysetup.toml",
            "templates/movie.txt",
        ]
    assert outcome.templates == ("movie",)


def test_credentials_are_removed_unless_asked_for(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _edit(manager.paths, "mysetup")

    outcome = export_bundle(manager.paths, ["mysetup"], tmp_path / "bundle")
    contents = read_bundle(outcome.archive)
    document = tomlkit.parse(contents.profiles["mysetup"])

    assert document["tracker"]["aither"]["api_key"] == ""  # type: ignore[index]
    assert document["tracker"]["aither"]["announce_url"] == ""  # type: ignore[index]
    # Identity, not a credential, and usually the reason a setup is shared.
    assert document["general"]["releasers_name"] == "someone"  # type: ignore[index]
    assert contents.manifest.credentials_included is False
    assert any("api_key" in entry for entry in outcome.blanked)


def test_credentials_are_kept_when_asked_for(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _edit(manager.paths, "mysetup")

    outcome = export_bundle(
        manager.paths, ["mysetup"], tmp_path / "bundle", include_credentials=True
    )
    contents = read_bundle(outcome.archive)
    document = tomlkit.parse(contents.profiles["mysetup"])

    assert document["tracker"]["aither"]["api_key"] == "SECRET-KEY"  # type: ignore[index]
    assert contents.manifest.credentials_included is True
    assert outcome.blanked == ()


def test_a_template_that_is_no_longer_on_disk_is_reported_not_fatal(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    _edit(manager.paths, "mysetup")
    manager.paths.templates.mkdir(parents=True, exist_ok=True)

    outcome = export_bundle(manager.paths, ["mysetup"], tmp_path / "bundle")

    assert outcome.missing_templates == ("movie",)
    assert outcome.templates == ()
    assert outcome.archive.is_file()


def test_exporting_nothing_is_refused(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    with pytest.raises(TransferError):
        export_bundle(manager.paths, [], tmp_path / "bundle")


def test_available_profiles_lists_every_profile(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    (manager.paths.user_configs / "other.toml").write_text("", encoding="utf-8")
    assert available_profiles(manager.paths) == ("mysetup", "other")


def test_referenced_templates_finds_every_tracker(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    document = _profile(manager.paths, "mysetup")
    document["tracker"]["aither"]["nfo_template"] = "movie"  # type: ignore[index]
    document["tracker"]["huno"]["nfo_template"] = "series"  # type: ignore[index]
    assert referenced_templates(document) == {"movie", "series"}


# ---------------------------------------------------------------------------
# import


def test_a_bundle_lands_intact_in_another_data_folder(tmp_path: Path) -> None:
    source = _manager(tmp_path / "a")
    _edit(source.paths, "mysetup")
    _template(source.paths, "movie")
    outcome = export_bundle(source.paths, ["mysetup"], tmp_path / "bundle")

    target = _manager(tmp_path / "b", "config")
    contents = read_bundle(outcome.archive)
    plan = plan_import(target.paths, contents, NameConflict.KEEP_BOTH)
    result = apply_import(target.paths, contents, plan, target)

    assert sorted(path.name for path in result.written) == [
        "movie.txt",
        "mysetup.toml",
    ]
    landed = _profile(target.paths, "mysetup")
    assert landed["tracker"]["aither"]["nfo_template"] == "movie"  # type: ignore[index]
    # It loads: the same check the next launch would make.
    target.load_profile("mysetup")


def test_paths_belonging_to_the_exporting_machine_are_cleared(
    tmp_path: Path,
) -> None:
    source = _manager(tmp_path / "a")
    _edit(source.paths, "mysetup")
    outcome = export_bundle(source.paths, ["mysetup"], tmp_path / "bundle")

    target = _manager(tmp_path / "b", "config")
    contents = read_bundle(outcome.archive)
    plan = plan_import(target.paths, contents, NameConflict.KEEP_BOTH)
    result = apply_import(target.paths, contents, plan, target)

    landed = _profile(target.paths, "mysetup")
    assert landed["general"]["working_dir"] == ""  # type: ignore[index]
    assert landed["dependencies"]["ffmpeg"] == ""  # type: ignore[index]
    assert "mysetup: general.working_dir" in result.cleared
    assert "mysetup: dependencies.ffmpeg" in result.cleared


def test_an_older_schema_is_migrated_on_the_way_in(tmp_path: Path) -> None:
    target = _manager(tmp_path, "config")
    bundle = _write_bundle(
        tmp_path / "old.zip",
        profiles={
            "legacy": (CONFIG_FIXTURE_DIR / "schema8_config.toml").read_text(
                encoding="utf-8"
            )
        },
    )

    contents = read_bundle(bundle)
    plan = plan_import(target.paths, contents, NameConflict.KEEP_BOTH)
    apply_import(target.paths, contents, plan, target)

    landed = _profile(target.paths, "legacy")
    assert landed["schema_version"] == TomlConfigCodec.SCHEMA_VERSION
    target.load_profile("legacy")


def test_a_profile_from_a_newer_build_is_refused(tmp_path: Path) -> None:
    _manager(tmp_path, "config")
    document = tomlkit.parse(
        (CONFIG_FIXTURE_DIR / "schema12_config.toml").read_text(encoding="utf-8")
    )
    document["schema_version"] = TomlConfigCodec.SCHEMA_VERSION + 1
    bundle = _write_bundle(
        tmp_path / "future.zip", profiles={"future": tomlkit.dumps(document)}
    )

    with pytest.raises(TransferError, match="newer version"):
        read_bundle(bundle)


def test_a_bundle_from_a_newer_build_is_refused(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path / "future.zip",
        profiles={"any": "schema_version = 13\n"},
        export_version=EXPORT_VERSION + 1,
    )
    with pytest.raises(TransferError, match="newer version"):
        read_bundle(bundle)


def test_a_profile_that_would_not_load_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    target = _manager(tmp_path, "config")
    good = _profile(target.paths, "config")
    broken = tomlkit.dumps(good).replace("timeout = 60", 'timeout = "soon"')
    bundle = _write_bundle(
        tmp_path / "broken.zip",
        profiles={"good": tomlkit.dumps(good), "broken": broken},
    )

    contents = read_bundle(bundle)
    plan = plan_import(target.paths, contents, NameConflict.KEEP_BOTH)
    with pytest.raises(TransferError, match="broken"):
        apply_import(target.paths, contents, plan, target)

    assert sorted(path.stem for path in target.paths.user_configs.glob("*.toml")) == [
        "config"
    ]


def test_a_bundle_with_no_manifest_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "plain.zip"
    with zipfile.ZipFile(archive, "w") as opened:
        opened.writestr("profiles/a.toml", "schema_version = 13\n")
    with pytest.raises(TransferError, match="not an NfoForge configuration bundle"):
        read_bundle(archive)


def test_a_bundle_holding_anything_else_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "extra.zip"
    with zipfile.ZipFile(archive, "w") as opened:
        opened.writestr(EXPORT_MANIFEST_NAME, f"export_version = {EXPORT_VERSION}\n")
        opened.writestr("profiles/a.toml", "schema_version = 13\n")
        opened.writestr("tools/ffmpeg.exe", "MZ")
    with pytest.raises(TransferError, match="not part of a"):
        read_bundle(archive)


def test_an_entry_that_would_escape_the_data_folder_is_refused(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as opened:
        opened.writestr(EXPORT_MANIFEST_NAME, f"export_version = {EXPORT_VERSION}\n")
        opened.writestr("../evil.toml", "schema_version = 13\n")
    with pytest.raises(TransferError, match="points outside"):
        read_bundle(archive)


@pytest.mark.parametrize("stem", ("con", "..", "   "))
def test_a_name_that_cannot_be_a_file_is_refused(tmp_path: Path, stem: str) -> None:
    archive = tmp_path / "named.zip"
    with zipfile.ZipFile(archive, "w") as opened:
        opened.writestr(EXPORT_MANIFEST_NAME, f"export_version = {EXPORT_VERSION}\n")
        opened.writestr(f"profiles/{stem}.toml", "schema_version = 13\n")
    with pytest.raises(TransferError):
        read_bundle(archive)


def test_a_bare_profile_file_is_read_as_a_single_profile_bundle(
    tmp_path: Path,
) -> None:
    """`Save As` produces exactly this, so users already have them."""
    source = _manager(tmp_path / "a")
    contents = read_bundle(source.paths.user_configs / "mysetup.toml")

    assert tuple(contents.profiles) == ("mysetup",)
    assert contents.templates == {}
    # A bare profile carries its credentials; saying otherwise would tell a
    # user they were removed when they were not.
    assert contents.manifest.credentials_included is True


# ---------------------------------------------------------------------------
# names already in use


def _round_trip(tmp_path: Path, policy: NameConflict):
    source = _manager(tmp_path / "a")
    _edit(source.paths, "mysetup")
    _template(source.paths, "movie", "incoming")
    bundle = export_bundle(source.paths, ["mysetup"], tmp_path / "bundle").archive

    target = _manager(tmp_path / "b", "mysetup")
    _template(target.paths, "movie", "already here")

    contents = read_bundle(bundle)
    plan = plan_import(target.paths, contents, policy)
    return target, contents, plan


def test_keep_both_renames_what_is_coming_in(tmp_path: Path) -> None:
    target, contents, plan = _round_trip(tmp_path, NameConflict.KEEP_BOTH)
    result = apply_import(target.paths, contents, plan, target)

    assert {entry.destination_name for entry in plan.entries} == {
        "mysetup (2)",
        "movie (2)",
    }
    assert (target.paths.templates / "movie.txt").read_text(
        encoding="utf-8"
    ) == "already here"
    assert (target.paths.templates / "movie (2).txt").read_text(
        encoding="utf-8"
    ) == "incoming"
    assert result.archived == ()


def test_a_renamed_template_is_the_one_its_profile_uses(tmp_path: Path) -> None:
    """Otherwise an imported profile silently renders with a local template."""
    target, contents, plan = _round_trip(tmp_path, NameConflict.KEEP_BOTH)
    apply_import(target.paths, contents, plan, target)

    landed = _profile(target.paths, "mysetup (2)")
    assert landed["tracker"]["aither"]["nfo_template"] == "movie (2)"  # type: ignore[index]


def test_skip_leaves_what_is_already_here(tmp_path: Path) -> None:
    target, contents, plan = _round_trip(tmp_path, NameConflict.SKIP)
    result = apply_import(target.paths, contents, plan, target)

    assert result.written == ()
    assert all(entry.disposition is Disposition.SKIPPED for entry in plan.entries)
    assert (target.paths.templates / "movie.txt").read_text(
        encoding="utf-8"
    ) == "already here"


def test_replace_keeps_a_copy_of_what_was_there(tmp_path: Path) -> None:
    target, contents, plan = _round_trip(tmp_path, NameConflict.REPLACE)
    result = apply_import(target.paths, contents, plan, target)

    assert (target.paths.templates / "movie.txt").read_text(
        encoding="utf-8"
    ) == "incoming"
    assert len(result.archived) == 2
    assert all(path.parent.name == "old_configs" for path in result.archived)


def test_an_identical_template_is_recognised_rather_than_duplicated(
    tmp_path: Path,
) -> None:
    source = _manager(tmp_path / "a")
    _edit(source.paths, "mysetup")
    _template(source.paths, "movie", "same")
    bundle = export_bundle(source.paths, ["mysetup"], tmp_path / "bundle").archive

    target = _manager(tmp_path / "b", "config")
    _template(target.paths, "movie", "same")

    contents = read_bundle(bundle)
    plan = plan_import(target.paths, contents, NameConflict.KEEP_BOTH)
    apply_import(target.paths, contents, plan, target)

    templates = plan.for_kind(EntryKind.TEMPLATE)
    assert [entry.disposition for entry in templates] == [Disposition.UNCHANGED]
    assert not (target.paths.templates / "movie (2).txt").exists()
    assert _profile(target.paths, "mysetup")["tracker"]["aither"]["nfo_template"] == (  # type: ignore[index]
        "movie"
    )


# ---------------------------------------------------------------------------
# summaries


def test_the_export_summary_says_what_it_removed(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _edit(manager.paths, "mysetup")
    outcome = export_bundle(manager.paths, ["mysetup"], tmp_path / "bundle")

    summary = render_export_summary(outcome)
    assert "Credentials removed" in summary
    assert "tracker.aither.api_key" in summary


def test_the_export_summary_warns_when_credentials_are_in_the_bundle(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    _edit(manager.paths, "mysetup")
    outcome = export_bundle(
        manager.paths, ["mysetup"], tmp_path / "bundle", include_credentials=True
    )
    assert "carries your credentials in full" in render_export_summary(outcome)


def test_the_import_summary_says_credentials_have_to_be_set_again(
    tmp_path: Path,
) -> None:
    source = _manager(tmp_path / "a")
    _edit(source.paths, "mysetup")
    bundle = export_bundle(source.paths, ["mysetup"], tmp_path / "bundle").archive

    target = _manager(tmp_path / "b", "config")
    contents = read_bundle(bundle)
    plan = plan_import(target.paths, contents, NameConflict.KEEP_BOTH)
    summary = render_import_summary(apply_import(target.paths, contents, plan, target))

    assert "exported without credentials" in summary
    assert "general.working_dir" in summary


# ---------------------------------------------------------------------------


def _write_bundle(
    archive: Path,
    profiles: dict[str, str],
    templates: dict[str, str] | None = None,
    export_version: int = EXPORT_VERSION,
) -> Path:
    """A bundle assembled by hand, for shapes `export_bundle` will not write."""
    with zipfile.ZipFile(archive, "w") as opened:
        opened.writestr(
            EXPORT_MANIFEST_NAME,
            f"export_version = {export_version}\n"
            f"schema_version = {TomlConfigCodec.SCHEMA_VERSION}\n"
            "credentials_included = true\n",
        )
        for name, text in profiles.items():
            opened.writestr(f"profiles/{name}.toml", text)
        for name, text in (templates or {}).items():
            opened.writestr(f"templates/{name}.txt", text)
    return archive


def test_a_bundle_name_holding_a_dot_keeps_it(tmp_path: Path) -> None:
    """`with_suffix` would have written 'my setup v1.zip'."""
    manager = _manager(tmp_path)

    outcome = export_bundle(manager.paths, ["mysetup"], tmp_path / "my setup v1.2")

    assert outcome.archive.name == "my setup v1.2.zip"


def test_a_name_that_already_ends_in_zip_is_not_doubled(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    outcome = export_bundle(manager.paths, ["mysetup"], tmp_path / "shared.zip")

    assert outcome.archive.name == "shared.zip"


def test_an_export_with_nothing_to_strip_does_not_warn_about_credentials(
    tmp_path: Path,
) -> None:
    """A fresh profile blanks nothing; reading that as 'credentials kept'
    would warn about a bundle that holds none."""
    manager = _manager(tmp_path)

    outcome = export_bundle(manager.paths, ["mysetup"], tmp_path / "bundle")
    summary = render_export_summary(outcome)

    assert outcome.blanked == ()
    assert outcome.credentials_included is False
    assert "no credentials in these profiles" in summary
    assert "carries your credentials in full" not in summary


# ---------------------------------------------------------------------------
# what the import leaves behind


def _bundle_for(tmp_path: Path) -> Path:
    """One bundle, built once -- `build_app_paths` refuses a second tree."""
    source = _manager(tmp_path / "a")
    _edit(source.paths, "mysetup")
    _template(source.paths, "movie")
    return export_bundle(source.paths, ["mysetup"], tmp_path / "bundle").archive


def _import(bundle: Path, target: ConfigManager):
    contents = read_bundle(bundle)
    plan = plan_import(target.paths, contents, NameConflict.KEEP_BOTH)
    return apply_import(target.paths, contents, plan, target)


def test_an_import_keeps_a_copy_of_its_summary(tmp_path: Path) -> None:
    """The window is shown once and never rechecked, exactly as the migration's
    is -- so it goes to the same log, which log tidying leaves alone."""
    target = _manager(tmp_path / "b", "config")

    outcome = _import(_bundle_for(tmp_path), target)

    log = target.paths.logs / SUMMARY_LOG_NAME
    written = log.read_text(encoding="utf-8")
    assert "configuration import" in written
    assert render_import_summary(outcome) in written


def test_a_second_import_is_appended_rather_than_replacing_the_first(
    tmp_path: Path,
) -> None:
    target = _manager(tmp_path / "b", "config")
    bundle = _bundle_for(tmp_path)

    _import(bundle, target)
    _import(bundle, target)

    log = target.paths.logs / SUMMARY_LOG_NAME
    assert log.read_text(encoding="utf-8").count("configuration import") == 2


def test_a_log_that_cannot_be_written_does_not_fail_the_import(
    tmp_path: Path,
) -> None:
    """Everything is already on disk by then; failing over a transcript would
    trade something that worked for nothing at all.

    Blocked by putting a file where the log directory goes, rather than by
    patching, so the failure is one the filesystem really produces.
    """
    target = _manager(tmp_path / "b", "config")
    target.paths.state_root.mkdir(parents=True, exist_ok=True)
    target.paths.logs.write_text("not a directory", encoding="utf-8")

    outcome = _import(_bundle_for(tmp_path), target)

    assert outcome.written


# ---------------------------------------------------------------------------
# plugins a profile selects


def _select_plugin(paths: ConfigPaths, name: str, plugin_id: str) -> None:
    path = paths.user_configs / f"{name}.toml"
    document = tomlkit.parse(path.read_text(encoding="utf-8"))
    document["plugins"]["token_replacer"] = plugin_id  # type: ignore[index]
    path.write_text(tomlkit.dumps(document), encoding="utf-8")


def _installed_plugin(paths: ConfigPaths, plugin_id: str) -> None:
    root = paths.plugins / plugin_id
    root.mkdir(parents=True, exist_ok=True)
    (root / "nfoforge-plugin.toml").write_text(
        f'schema_version = 1\nid = "{plugin_id}"\nmodule = "plugin_x"\n',
        encoding="utf-8",
    )


def test_a_selected_plugin_that_is_not_here_is_named(tmp_path: Path) -> None:
    """Otherwise the capability quietly falls back to NfoForge's own."""
    source = _manager(tmp_path / "a")
    _select_plugin(source.paths, "mysetup", "example.absent")
    bundle = export_bundle(source.paths, ["mysetup"], tmp_path / "bundle").archive

    target = _manager(tmp_path / "b", "config")
    contents = read_bundle(bundle)
    plan = plan_import(target.paths, contents, NameConflict.KEEP_BOTH)
    outcome = apply_import(target.paths, contents, plan, target)

    assert outcome.unavailable_plugins == ("example.absent",)
    assert "example.absent" in render_import_summary(outcome)


def test_a_selected_plugin_that_is_installed_is_not_reported(tmp_path: Path) -> None:
    source = _manager(tmp_path / "a")
    _select_plugin(source.paths, "mysetup", "example.present")
    bundle = export_bundle(source.paths, ["mysetup"], tmp_path / "bundle").archive

    target = _manager(tmp_path / "b", "config")
    _installed_plugin(target.paths, "example.present")
    contents = read_bundle(bundle)
    plan = plan_import(target.paths, contents, NameConflict.KEEP_BOTH)

    assert apply_import(target.paths, contents, plan, target).unavailable_plugins == ()


def test_availability_is_read_from_disk_not_from_what_loaded(
    tmp_path: Path,
) -> None:
    """A user with external plugins switched off has nothing loaded, and
    reporting every selection as missing for them would be noise."""
    source = _manager(tmp_path / "a")
    _select_plugin(source.paths, "mysetup", "example.present")
    bundle = export_bundle(source.paths, ["mysetup"], tmp_path / "bundle").archive

    target = _manager(tmp_path / "b", "config")
    target.settings.general.enable_plugins = False
    _installed_plugin(target.paths, "example.present")
    contents = read_bundle(bundle)
    plan = plan_import(target.paths, contents, NameConflict.KEEP_BOTH)

    assert target.plugin_manager.plugin_ids == frozenset()
    assert apply_import(target.paths, contents, plan, target).unavailable_plugins == ()
