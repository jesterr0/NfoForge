from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, cast

import pytest
import tomlkit

from src.config.codec import TomlConfigCodec
from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.config.persistence import atomic_write_text
from src.enums.tracker_selection import TrackerSelection
from src.exceptions import ConfigError, ConfigSchemaError
from src.payloads.trackers import MoreThanTVInfo


def _paths(tmp_path: Path) -> ConfigPaths:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    source_defaults = Path("runtime/config/defaults")
    default_config = defaults / "default_config.toml"
    default_program = defaults / "default_program_conf.toml"
    default_config.write_text(
        (source_defaults / "default_config.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    default_program.write_text(
        (source_defaults / "default_program_conf.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return ConfigPaths(
        default_config=default_config,
        default_program=default_program,
        program=tmp_path / "program/conf.toml",
        user_configs=tmp_path / "user",
        tracker_cookies=tmp_path / "cookies",
    )


def test_manager_loads_nested_typed_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )

    manager = ConfigManager("test", _paths(tmp_path))

    assert manager.settings.general.timeout == 60
    assert manager.settings.series.standard_episode_token
    assert manager.settings.trackers.more_than_tv.source == "MTV"
    assert manager.settings.templates.newline_sequence == "\n"


def test_save_preserves_unknown_keys_and_comments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)
    profile = paths.user_configs / "test.toml"
    document = tomlkit.parse(profile.read_text(encoding="utf-8"))
    document.add(tomlkit.comment("third-party setting"))
    document["third_party"] = {"enabled": True}
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    manager.load_profile("test")
    manager.settings.general.timeout = 90
    manager.save()
    saved = profile.read_text(encoding="utf-8")

    assert "# third-party setting" in saved
    assert "[third_party]" in saved
    assert "timeout = 90" in saved


def test_manager_preserves_qbittorrent_super_seeding_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)

    assert (
        manager.settings.torrent_clients.qbittorrent.specific_params["super_seeding"]
        is False
    )

    manager.save()
    manager.load_profile("test")

    profile = paths.user_configs / "test.toml"
    saved = tomlkit.parse(profile.read_text(encoding="utf-8"))
    torrent_client = cast(MutableMapping[str, Any], saved["torrent_client"])
    qbittorrent = cast(MutableMapping[str, Any], torrent_client["qbittorrent"])
    specific_params = cast(MutableMapping[str, Any], qbittorrent["specific_params"])
    assert specific_params["super_seeding"] is False
    assert (
        manager.settings.torrent_clients.qbittorrent.specific_params["super_seeding"]
        is False
    )


def test_manager_rejects_empty_qbittorrent_super_seeding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    profile = paths.user_configs / "test.toml"
    profile.parent.mkdir(parents=True)
    document = tomlkit.parse(paths.default_config.read_text(encoding="utf-8"))
    torrent_client = cast(MutableMapping[str, Any], document["torrent_client"])
    qbittorrent = cast(MutableMapping[str, Any], torrent_client["qbittorrent"])
    specific_params = cast(MutableMapping[str, Any], qbittorrent["specific_params"])
    specific_params["super_seeding"] = ""
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    with pytest.raises(
        ConfigError,
        match=r"torrent_client\.qbittorrent\.specific_params\.super_seeding",
    ):
        ConfigManager("test", paths)


def test_lookup_helpers_do_not_cache_replaced_objects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    manager = ConfigManager("test", _paths(tmp_path))
    replacement = MoreThanTVInfo(source="replacement")

    manager.settings.trackers.more_than_tv = replacement

    assert (
        manager.settings.trackers.by_selection()[TrackerSelection.MORE_THAN_TV]
        is replacement
    )


def test_unchanged_settings_do_not_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    manager = ConfigManager("test", _paths(tmp_path))
    writes = 0

    def record_write(path: Path, text: str) -> None:
        nonlocal writes
        writes += 1

    monkeypatch.setattr("src.config.operations.atomic_write_text", record_write)

    manager.save()

    assert writes == 0


def test_codec_reports_dotted_path_for_invalid_type() -> None:
    defaults = tomlkit.parse(
        Path("runtime/config/defaults/default_config.toml").read_text(encoding="utf-8")
    )
    invalid = tomlkit.parse(tomlkit.dumps(defaults))
    general = cast(MutableMapping[str, Any], invalid["general"])
    general["timeout"] = "sixty"

    with pytest.raises(ConfigError, match=r"general\.timeout"):
        TomlConfigCodec.validate_types(invalid, defaults)


def test_manager_rejects_blank_required_series_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    profile = paths.user_configs / "test.toml"
    profile.parent.mkdir(parents=True)
    document = tomlkit.parse(paths.default_config.read_text(encoding="utf-8"))
    series_management = cast(MutableMapping[str, Any], document["series_management"])
    series_management["tvr_standard_episode_token"] = ""
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    with pytest.raises(
        ConfigError,
        match=r"series_management\.tvr_standard_episode_token",
    ):
        ConfigManager("test", paths)


def test_manager_rejects_unsupported_schema_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    profile = paths.user_configs / "test.toml"
    profile.parent.mkdir(parents=True)
    document = tomlkit.parse(paths.default_config.read_text(encoding="utf-8"))
    document["schema_version"] = 99
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    with pytest.raises(
        ConfigError, match="Unsupported configuration schema_version: 99"
    ):
        ConfigManager("test", paths)


def test_manager_rejects_old_schema_before_value_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    profile = paths.user_configs / "test.toml"
    profile.parent.mkdir(parents=True)
    document = tomlkit.parse(paths.default_config.read_text(encoding="utf-8"))
    document["schema_version"] = 1
    template_settings = cast(MutableMapping[str, Any], document["template_settings"])
    template_settings["newline_sequence"] = "\\n"
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    with pytest.raises(
        ConfigError, match="Unsupported configuration schema_version: 1"
    ):
        ConfigManager("test", paths)


def test_replace_profile_with_default_archives_old_config(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    profile = paths.user_configs / "test.toml"
    profile.parent.mkdir(parents=True)
    old_config = "schema_version = 1\n[template_settings]\nnewline_sequence = '\\n'\n"
    profile.write_text(old_config, encoding="utf-8")

    backup_path = ConfigManager.replace_profile_with_default(profile, paths)

    assert backup_path.parent == profile.parent / "old_configs"
    assert backup_path.exists()
    assert backup_path.read_text(encoding="utf-8") == old_config
    assert profile.exists()
    assert "schema_version = 2" in profile.read_text(encoding="utf-8")


@pytest.mark.parametrize("newline_sequence", ("\\n", "\\r", "\\r\\n", "invalid"))
def test_manager_rejects_invalid_newline_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, newline_sequence: str
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    profile = paths.user_configs / "test.toml"
    profile.parent.mkdir(parents=True)
    document = tomlkit.parse(paths.default_config.read_text(encoding="utf-8"))
    template_settings = cast(MutableMapping[str, Any], document["template_settings"])
    template_settings["newline_sequence"] = newline_sequence
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    with pytest.raises(ConfigError, match=r"template_settings\.newline_sequence"):
        ConfigManager("test", paths)


def test_load_profile_migrates_schema1_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    profile = paths.user_configs / "test.toml"
    profile.parent.mkdir(parents=True)
    fixture_text = Path("tests/test_config/fixtures/schema1_config.toml").read_text(
        encoding="utf-8"
    )
    profile.write_text(fixture_text, encoding="utf-8")

    manager = ConfigManager("test", paths)  # should migrate, not raise

    reloaded = tomlkit.parse(profile.read_text(encoding="utf-8"))
    assert reloaded["schema_version"] == 2
    assert reloaded["movie_management"]["mvr_release_group"] == "CustomReleaseGroup"
    assert "movie_rename" not in reloaded
    # migrated in place; the archive/backup path must not have been taken
    assert not (profile.parent / "old_configs").exists()
    assert manager.settings.movie.release_group == "CustomReleaseGroup"
    assert manager.settings.trackers.more_than_tv.username == "custom_mtv_user"


def test_migration_validation_failure_preserves_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A schema-1 config that migrates structurally (no `unmapped` sections)
    but whose resulting schema-2 document fails validation must NOT be
    written to disk. The manager must fall through to the same
    `ConfigSchemaError` archive/regenerate path used when migration can't
    map sections at all, leaving the original file byte-for-byte untouched.
    """
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    profile = paths.user_configs / "test.toml"
    profile.parent.mkdir(parents=True)
    fixture_text = Path("tests/test_config/fixtures/schema1_config.toml").read_text(
        encoding="utf-8"
    )
    profile.write_text(fixture_text, encoding="utf-8")

    # Force the post-migration validation step to fail, simulating a
    # migrated document that maps structurally but doesn't actually
    # validate (e.g. a bad type/value that survived the section mapping).
    original_decode = ConfigManager.decode

    def fake_decode(
        self: object,
        toml_data: object,
        build_defaults: bool = False,
        dry_run: bool = False,
    ) -> None:
        if dry_run:
            raise ConfigError("forced migration validation failure")
        return original_decode(self, toml_data, build_defaults=build_defaults)  # type: ignore[arg-type]

    monkeypatch.setattr(ConfigManager, "decode", fake_decode)

    with pytest.raises(ConfigError, match="Missing configuration schema_version"):
        ConfigManager("test", paths)

    # the original schema-1 file must be left completely untouched -- no
    # partial/invalid migrated document was ever persisted
    assert profile.read_text(encoding="utf-8") == fixture_text
    assert not (profile.parent / "old_configs").exists()


def test_load_profile_raises_schema_error_when_migration_cannot_map_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When migration can't fully account for the settings (or raises), the
    manager must still surface `ConfigSchemaError` -- exactly as it did
    before migration support existed -- so the caller's existing
    archive+regenerate flow (gated behind a user-facing dialog) takes over.
    ConfigManager itself never auto-archives.
    """
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    profile = paths.user_configs / "test.toml"
    profile.parent.mkdir(parents=True)
    # no [movie_rename] section at all -- cannot be migrated
    original = '[general]\nui_suffix = ""\n'
    profile.write_text(original, encoding="utf-8")

    with pytest.raises(ConfigError, match="Missing configuration schema_version"):
        ConfigManager("test", paths)

    # failed migration must not write a partial result to disk
    assert profile.read_text(encoding="utf-8") == original


def test_load_profile_leaves_current_config_unchanged_on_schema_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Switching to an incompatible profile must not persist the broken
    profile name as the active one. `program.current_config` must still
    point at the last-known-good profile after `load_profile` raises
    `ConfigSchemaError`, so a runtime profile switch can safely restore the
    previous selection instead of getting stuck on a config that can't load.
    """
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)
    assert manager.program.current_config == "test"

    broken_profile = paths.user_configs / "broken.toml"
    document = tomlkit.parse(paths.default_config.read_text(encoding="utf-8"))
    document["schema_version"] = 99
    broken_profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    with pytest.raises(ConfigSchemaError):
        manager.load_profile("broken")

    assert manager.program.current_config == "test"


def test_load_profile_persists_new_current_config_to_disk_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful `load_profile` switch must persist the NEW profile name
    to the on-disk program-conf file immediately -- not only in memory.

    Regression test: task 3.2 moved the `self.program.current_config =
    config_file` assignment in `load_profile` to *after* `self.save
    (config_path)`, but `save()` calls `save_program()`, which writes
    `self.program.current_config` to disk. With the assignment after the
    save, `save_program()` persisted the STALE (previous) profile name, so
    an abnormal termination right after a successful switch would revert to
    the old profile on next launch. The in-memory value alone (asserted by
    other tests in this file) does not catch this -- only reading the
    on-disk program-conf file back does.
    """
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)
    assert manager.program.current_config == "test"

    second_profile = paths.user_configs / "second.toml"
    second_profile.write_text(
        paths.default_config.read_text(encoding="utf-8"), encoding="utf-8"
    )

    manager.load_profile("second")

    assert manager.program.current_config == "second"
    on_disk = tomlkit.parse(paths.program.read_text(encoding="utf-8"))
    assert on_disk["current_config"] == "second"


def test_load_profile_leaves_on_disk_current_config_unchanged_on_schema_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure path must leave the on-disk program-conf file's
    `current_config` unchanged too, not just the in-memory value (see
    `test_load_profile_leaves_current_config_unchanged_on_schema_error`).
    """
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)
    assert manager.program.current_config == "test"
    on_disk_before = tomlkit.parse(paths.program.read_text(encoding="utf-8"))
    assert on_disk_before["current_config"] == "test"

    broken_profile = paths.user_configs / "broken.toml"
    document = tomlkit.parse(paths.default_config.read_text(encoding="utf-8"))
    document["schema_version"] = 99
    broken_profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    with pytest.raises(ConfigSchemaError):
        manager.load_profile("broken")

    assert manager.program.current_config == "test"
    on_disk_after = tomlkit.parse(paths.program.read_text(encoding="utf-8"))
    assert on_disk_after["current_config"] == "test"


def test_atomic_write_failure_preserves_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "config.toml"
    destination.write_text("original", encoding="utf-8")

    def fail_replace(self: Path, target: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        atomic_write_text(destination, "replacement")

    assert destination.read_text(encoding="utf-8") == "original"
