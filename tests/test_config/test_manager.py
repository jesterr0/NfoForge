from collections.abc import MutableMapping
import dataclasses
import enum
from pathlib import Path
from typing import Any, cast

import pytest
import tomlkit

from src.config.codec import TomlConfigCodec
from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.config.persistence import atomic_write_text
from src.enums.media_search_mode import MediaSearchMode
from src.enums.torrent_client import QBittorrentSavePathMode
from src.enums.tracker_selection import TrackerSelection
from src.exceptions import ConfigError, ConfigSchemaError
from src.payloads.clients import (
    DelugeConfig,
    QBittorrentConfig,
    RTorrentConfig,
    TransmissionConfig,
)
from src.payloads.trackers import BeyondHDInfo
from tests.repo_paths import CONFIG_FIXTURE_DIR, DEFAULT_CONFIG_TOML
from tests.test_config.config_tree import (
    build_config_paths as _paths,
    leaf_key_paths as _leaf_key_paths,
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
    assert manager.settings.trackers.beyond_hd.source == "BHD"
    assert manager.settings.templates.newline_sequence == "\n"


def test_media_search_mode_is_backfilled_and_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    ConfigManager("test", paths)
    profile = paths.user_configs / "test.toml"
    document = tomlkit.parse(profile.read_text(encoding="utf-8"))
    del document["general"]["media_search_mode"]  # type: ignore[index]
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    manager = ConfigManager("test", paths)
    assert manager.settings.general.media_search_mode is MediaSearchMode.BOTH

    manager.settings.general.media_search_mode = MediaSearchMode.TV
    manager.save()
    reloaded = ConfigManager("test", paths)
    assert reloaded.settings.general.media_search_mode is MediaSearchMode.TV


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
    torrent_clients = cast(MutableMapping[str, Any], document["torrent_client"])
    qbittorrent = cast(MutableMapping[str, Any], torrent_clients["qbittorrent"])
    qbittorrent_specific = cast(
        MutableMapping[str, Any],
        qbittorrent["specific_params"],
    )
    qbittorrent_specific["third_party_option"] = "preserve-me"
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    manager.load_profile("test")
    manager.settings.general.timeout = 90
    manager.save()
    saved = profile.read_text(encoding="utf-8")

    assert "# third-party setting" in saved
    assert "[third_party]" in saved
    assert "timeout = 90" in saved
    saved_document = tomlkit.parse(saved)
    saved_clients = cast(
        MutableMapping[str, Any],
        saved_document["torrent_client"],
    )
    saved_qbittorrent = cast(
        MutableMapping[str, Any],
        saved_clients["qbittorrent"],
    )
    saved_specific = cast(
        MutableMapping[str, Any],
        saved_qbittorrent["specific_params"],
    )
    assert saved_specific["third_party_option"] == "preserve-me"


def test_save_preserves_a_user_supplied_tmdb_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A user-supplied override in `[api_keys]` must survive a load + save,
    not be stripped. Restores the override this table provides -- an earlier
    revision removed it in favor of the bundled key alone and popped the
    table on every save.
    """
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)
    profile = paths.user_configs / "test.toml"
    document = tomlkit.parse(profile.read_text(encoding="utf-8"))
    document["api_keys"] = {"tmdb_api_key": "user-supplied"}
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    manager.load_profile("test")

    assert manager.settings.api_keys.tmdb_api_key == "user-supplied"
    saved_document = tomlkit.parse(profile.read_text(encoding="utf-8"))
    saved_api_keys = cast(MutableMapping[str, Any], saved_document["api_keys"])
    assert saved_api_keys["tmdb_api_key"] == "user-supplied"


def test_manager_preserves_qbittorrent_super_seeding_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)

    assert manager.settings.torrent_clients.qbittorrent.super_seeding is False

    manager.save()
    manager.load_profile("test")

    profile = paths.user_configs / "test.toml"
    saved = tomlkit.parse(profile.read_text(encoding="utf-8"))
    torrent_client = cast(MutableMapping[str, Any], saved["torrent_client"])
    qbittorrent = cast(MutableMapping[str, Any], torrent_client["qbittorrent"])
    specific_params = cast(MutableMapping[str, Any], qbittorrent["specific_params"])
    assert specific_params["super_seeding"] is False
    assert manager.settings.torrent_clients.qbittorrent.super_seeding is False


def test_manager_builds_concrete_torrent_client_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    clients = ConfigManager("test", _paths(tmp_path)).settings.torrent_clients

    assert isinstance(clients.qbittorrent, QBittorrentConfig)
    assert isinstance(clients.deluge, DelugeConfig)
    assert isinstance(clients.rtorrent, RTorrentConfig)
    assert isinstance(clients.transmission, TransmissionConfig)


def test_manager_merges_qbittorrent_save_path_defaults_into_schema3_profile(
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
    del specific_params["save_path_mode"]
    del specific_params["save_path_template"]
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    manager = ConfigManager("test", paths)

    assert (
        manager.settings.torrent_clients.qbittorrent.save_path_mode
        is QBittorrentSavePathMode.CLIENT_DEFAULT
    )
    assert manager.settings.torrent_clients.qbittorrent.save_path_template == ""


@pytest.mark.parametrize(
    ("mode", "template", "invalid_key"),
    [
        ("not-a-mode", "", "save_path_mode"),
        (QBittorrentSavePathMode.TEMPLATE.value, "", "save_path_template"),
    ],
)
def test_manager_rejects_invalid_qbittorrent_save_path_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    template: str,
    invalid_key: str,
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
    specific_params["save_path_mode"] = mode
    specific_params["save_path_template"] = template
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    with pytest.raises(ConfigError, match=invalid_key):
        ConfigManager("test", paths)


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
    replacement = BeyondHDInfo(source="replacement")

    manager.settings.trackers.beyond_hd = replacement

    assert (
        manager.settings.trackers.by_selection()[TrackerSelection.BEYOND_HD]
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
    defaults = tomlkit.parse(DEFAULT_CONFIG_TOML.read_text(encoding="utf-8"))
    invalid = tomlkit.parse(tomlkit.dumps(defaults))
    general = cast(MutableMapping[str, Any], invalid["general"])
    general["timeout"] = "sixty"

    with pytest.raises(ConfigError, match=r"general\.timeout"):
        TomlConfigCodec.validate_types(invalid, defaults)


def test_int_accepted_where_float_expected() -> None:
    """A hand-edited or plugin-written config with an int value where the
    default is a float (e.g. `ui_scale_factor = 1` vs. the default `1.0`)
    is current-schema and salvageable -- it must not be rejected."""
    defaults = tomlkit.parse(DEFAULT_CONFIG_TOML.read_text(encoding="utf-8"))
    doc = tomlkit.parse(tomlkit.dumps(defaults))
    general = cast(MutableMapping[str, Any], doc["general"])
    assert isinstance(general["ui_scale_factor"].unwrap(), float)
    general["ui_scale_factor"] = 1  # int, default is 1.0

    TomlConfigCodec.validate_types(doc, defaults)  # must not raise


def test_bool_still_rejected_where_float_expected() -> None:
    """`bool` is a subclass of `int` in Python and must still be rejected
    where a float is expected, even though a plain `int` is now tolerated."""
    defaults = tomlkit.parse(DEFAULT_CONFIG_TOML.read_text(encoding="utf-8"))
    invalid = tomlkit.parse(tomlkit.dumps(defaults))
    general = cast(MutableMapping[str, Any], invalid["general"])
    general["ui_scale_factor"] = True

    with pytest.raises(ConfigError, match=r"general\.ui_scale_factor"):
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

    with pytest.raises(ConfigError, match="schema_version 99 is newer"):
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
        ConfigSchemaError,
        match="Could not migrate configuration schema_version 1",
    ):
        ConfigManager("test", paths)


def test_validate_schema_rejects_non_integer_schema_version() -> None:
    """A malformed `schema_version` (e.g. a string) must raise
    `ConfigSchemaError`, not a bare `ValueError` -- a bare `ValueError` would
    bubble past the friendly startup error handlers straight to the global
    excepthook instead of offering the migrate/regenerate recovery path."""
    with pytest.raises(ConfigSchemaError):
        TomlConfigCodec.validate_schema({"schema_version": "two"})


def test_validate_schema_distinguishes_newer_schema_version() -> None:
    """A `schema_version` newer than the app's `SCHEMA_VERSION` (e.g. the
    config was written by a newer app version and the app was then
    downgraded) must raise `ConfigSchemaError` with wording that
    distinguishes it from the older/needs-migration case, instead of the
    same generic "please generate a new config file" message used when the
    config predates the current schema."""
    newer_version = TomlConfigCodec.SCHEMA_VERSION + 1
    with pytest.raises(ConfigSchemaError, match="newer"):
        TomlConfigCodec.validate_schema({"schema_version": newer_version})


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
    assert f"schema_version = {TomlConfigCodec.SCHEMA_VERSION}" in profile.read_text(
        encoding="utf-8"
    )


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


def test_load_profile_rejects_unversioned_config_without_mutating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unversioned config the migration chain cannot fully map (here: no
    `[movie_rename]` section at all) is handed to the archive-and-regenerate
    flow, with the original left untouched. ConfigManager never auto-archives.
    """
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    profile = paths.user_configs / "test.toml"
    profile.parent.mkdir(parents=True)
    original = '[general]\nui_suffix = ""\n'
    profile.write_text(original, encoding="utf-8")

    with pytest.raises(
        ConfigSchemaError,
        match="Could not migrate configuration schema_version 1",
    ):
        ConfigManager("test", paths)

    # failed migration must not write a partial result to disk
    assert profile.read_text(encoding="utf-8") == original


def test_manager_wraps_malformed_profile_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    profile = paths.user_configs / "test.toml"
    profile.parent.mkdir(parents=True)
    profile.write_text("[broken", encoding="utf-8")

    with pytest.raises(ConfigError, match="Error reading user configuration"):
        ConfigManager("test", paths)


def test_manager_wraps_malformed_program_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    paths.program.parent.mkdir(parents=True)
    paths.program.write_text("[broken", encoding="utf-8")

    with pytest.raises(ConfigError, match="Error reading program configuration"):
        ConfigManager("test", paths)


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


def test_load_profile_keeps_toml_data_consistent_with_settings_past_schema_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reload that fails *past* schema validation -- at `validate_types` or
    `decode`, not at the `schema_version` check -- must not leave
    `_toml_data` holding the new (invalid) profile's merged document while
    `settings` still holds the old profile.

    `_toml_data` is only reassigned once `_validate_document` fully succeeds
    (schema check, merge, `validate_types`, `decode`); if it fails at any
    later step, the assignment never happens and `_toml_data` stays exactly
    where it was, consistent with `settings`. This is a deliberate
    improvement over the previous eager-assignment behavior, where
    `_toml_data` was updated to the merged (but not yet fully validated)
    document *before* `validate_types`/`decode` ran, so a failure at those
    later steps left `_toml_data` and `settings` pointing at two different
    profiles. The schema-failure tests above (using `schema_version = 99`)
    fail at the very first step and so never exercise this path.
    """
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)

    # profile A ("test") is loaded successfully -- capture its known-good
    # state, present in both `_toml_data` and the decoded `settings`.
    assert manager.settings.general.timeout == 60
    general_a = cast(MutableMapping[str, Any], manager._toml_data["general"])
    assert general_a["timeout"] == 60

    # profile B passes schema validation (a current `schema_version` is
    # present) but fails `validate_types`: `general.timeout` is a string
    # where the default document has an int.
    broken_profile = paths.user_configs / "broken.toml"
    document = tomlkit.parse(paths.default_config.read_text(encoding="utf-8"))
    broken_general = cast(MutableMapping[str, Any], document["general"])
    broken_general["timeout"] = "not-a-number"
    broken_profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        manager.load_profile("broken")
    # must fail past schema validation, not at it
    assert not isinstance(exc_info.value, ConfigSchemaError)

    # `_toml_data` must still reflect profile A, matching `settings` --
    # never the failed profile's (invalid) value.
    assert manager.settings.general.timeout == 60
    general_after = cast(MutableMapping[str, Any], manager._toml_data["general"])
    assert general_after["timeout"] == 60


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


def test_bool_tracker_flag_config_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tracker flag persisted as a real boolean must load without raising.

    Regression: `tracker.*.anonymous` (and the other tracker checkbox flags)
    is a `bool` in the model, the UI (`QCheckBox.isChecked()`) and the write
    path, but the packaged default shipped it as the int `0`. The moment the
    app wrote the config back from its own model the value became a TOML
    `true`/`false`, and `validate_types` -- which deliberately refuses to
    treat `bool` as `int` -- then rejected the very config the app produced
    with `Invalid type at tracker.beyond_hd.anonymous: expected int, got
    bool` on the next launch.
    """
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    profile = paths.user_configs / "test.toml"
    profile.parent.mkdir(parents=True)
    document = tomlkit.parse(paths.default_config.read_text(encoding="utf-8"))
    tracker = cast(MutableMapping[str, Any], document["tracker"])
    beyond_hd = cast(MutableMapping[str, Any], tracker["beyond_hd"])
    beyond_hd["anonymous"] = True  # a real bool, as the app writes it
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    manager = ConfigManager("test", paths)  # must not raise

    assert manager.settings.trackers.beyond_hd.anonymous is True


def test_tracker_bool_flag_roundtrips_through_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setting a tracker flag from the UI (`QCheckBox.isChecked()` -> a real
    `bool`) and saving must produce a config that reloads cleanly -- the exact
    write-then-relaunch sequence that first surfaced the bug."""
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)

    manager.settings.trackers.beyond_hd.anonymous = True  # isChecked()
    manager.save()
    manager.load_profile("test")  # must not raise

    assert manager.settings.trackers.beyond_hd.anonymous is True
    saved = tomlkit.parse(
        (paths.user_configs / "test.toml").read_text(encoding="utf-8")
    )
    tracker = cast(MutableMapping[str, Any], saved["tracker"])
    beyond_hd = cast(MutableMapping[str, Any], tracker["beyond_hd"])
    raw = beyond_hd["anonymous"]
    raw = raw.unwrap() if hasattr(raw, "unwrap") else raw
    assert type(raw) is bool and raw is True


def test_beyond_hd_stream_and_localization_flags_persist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`BeyondHDInfo.add_localization_to_custom_edition` and `stream_optimized`
    are real, user-facing checkboxes that persisted on release configs. The
    typed-config refactor dropped both from the decode and save paths (and the
    packaged default), so toggling them no longer survived a reload. They must
    round-trip like every other tracker flag.
    """
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)

    manager.settings.trackers.beyond_hd.add_localization_to_custom_edition = True
    manager.settings.trackers.beyond_hd.stream_optimized = True
    manager.save()
    manager.load_profile("test")  # must not raise

    assert (
        manager.settings.trackers.beyond_hd.add_localization_to_custom_edition is True
    )
    assert manager.settings.trackers.beyond_hd.stream_optimized is True


def test_int_tracker_flag_is_coerced_and_persisted_as_bool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A profile still holding the legacy int `anonymous = 0` must self-heal
    to a bool rather than fail `validate_types` against the now-boolean
    default, and the healed value must be written back as a real TOML bool so
    the two representations converge."""
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    profile = paths.user_configs / "test.toml"
    profile.parent.mkdir(parents=True)
    document = tomlkit.parse(paths.default_config.read_text(encoding="utf-8"))
    tracker = cast(MutableMapping[str, Any], document["tracker"])
    beyond_hd = cast(MutableMapping[str, Any], tracker["beyond_hd"])
    beyond_hd["anonymous"] = 0  # legacy int representation
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    manager = ConfigManager("test", paths)  # must not raise

    assert manager.settings.trackers.beyond_hd.anonymous is False
    # the healed value is persisted as a real TOML boolean, not an int
    saved = tomlkit.parse(profile.read_text(encoding="utf-8"))
    saved_tracker = cast(MutableMapping[str, Any], saved["tracker"])
    saved_bhd = cast(MutableMapping[str, Any], saved_tracker["beyond_hd"])
    raw = saved_bhd["anonymous"]
    raw = raw.unwrap() if hasattr(raw, "unwrap") else raw
    assert type(raw) is bool
    ConfigManager("test", paths)  # a fresh load of the healed file is clean


def test_coerce_bool_flags_normalizes_int_flags() -> None:
    """`coerce_bool_flags` turns a persisted int 0/1 into a bool where the
    default declares a bool, and leaves genuine ints, enum-backed ints and
    non-0/1 values alone (the latter so real corruption still surfaces as a
    type error rather than being silently coerced)."""
    defaults = {
        "tracker": {
            "beyond_hd": {
                "anonymous": False,  # bool flag
                "internal": False,  # bool flag
                "row_space": 0,  # genuine int
                "promo": 0,  # enum-backed int
            }
        }
    }
    document: dict[str, Any] = {
        "tracker": {
            "beyond_hd": {
                "anonymous": 1,  # legacy int for a bool flag -> True
                "internal": 5,  # not 0/1 -> left for validate_types to reject
                "row_space": 0,  # int default -> untouched
                "promo": 2,  # int default -> untouched
            }
        }
    }

    TomlConfigCodec.coerce_bool_flags(document, defaults)

    bhd = document["tracker"]["beyond_hd"]
    assert bhd["anonymous"] is True
    assert type(bhd["internal"]) is int and bhd["internal"] == 5
    assert type(bhd["row_space"]) is int and bhd["row_space"] == 0
    assert type(bhd["promo"]) is int and bhd["promo"] == 2


def test_default_config_round_trips_without_key_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard against schema drift between the packaged default and the code.

    Loading the default and saving it back writes every field the model
    knows about. Comparing the saved document's keys against the packaged
    default catches two failure modes:

    - orphan keys: a key ships in the default that ``save`` never writes
      (e.g. a leftover from a removed feature) -- these must not exist.
    - missing keys: ``save`` writes a key the default omits. The only
      legitimate case is the per-tracker ``tvr_title_overrides`` tables.
      Trackers that enforce a series title ship them (Aither, LST); the
      rest are seeded on save. Anything else means the default is behind
      the model.
    """
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)
    manager.save()

    saved = tomlkit.parse(
        (paths.user_configs / "test.toml").read_text(encoding="utf-8")
    )
    default_doc = tomlkit.parse(paths.default_config.read_text(encoding="utf-8"))
    saved_keys = _leaf_key_paths(saved)
    default_keys = _leaf_key_paths(default_doc)

    orphans = default_keys - saved_keys
    assert not orphans, f"default ships keys the code never writes: {sorted(orphans)}"

    unexpected = {
        k for k in saved_keys - default_keys if "tvr_title_overrides" not in k
    }
    assert not unexpected, (
        f"save writes keys missing from the default config: {sorted(unexpected)}"
    )


def test_all_tracker_scalar_fields_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every scalar tracker field must survive a save/reload.

    A field dropped from ``decode`` or ``save`` (as ``add_localization_to_
    custom_edition`` and ``stream_optimized`` were for BeyondHD) silently
    reverts to its dataclass default on reload. Mutate every bool/int/str/
    enum field on every tracker to a distinct value, save, reload, and
    assert each mutation persisted -- a drop makes the round-trip fail.
    Container fields (lists, the ``tvr_title_overrides`` mapping) and
    ``None`` values are skipped.
    """
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)

    def probe(current: object, field_name: str) -> object | None:
        # bool before int: bool is an int subclass; enum before int: IntEnum
        # is both. Return None to skip a field.
        if isinstance(current, bool):
            return not current
        if isinstance(current, enum.Enum):
            return next((m for m in type(current) if m != current), None)
        if isinstance(current, str):
            return f"probe-{field_name}"
        if isinstance(current, int):
            return current + 7
        return None

    changes: dict[TrackerSelection, dict[str, object]] = {}
    for selection, tracker in manager.settings.trackers.by_selection().items():
        field_changes: dict[str, object] = {}
        for f in dataclasses.fields(tracker):
            new_value = probe(getattr(tracker, f.name), f.name)
            if new_value is None:
                continue
            setattr(tracker, f.name, new_value)
            field_changes[f.name] = new_value
        changes[selection] = field_changes

    manager.save()
    manager.load_profile("test")

    reloaded = manager.settings.trackers.by_selection()
    for selection, field_changes in changes.items():
        tracker = reloaded[selection]
        for name, expected in field_changes.items():
            assert getattr(tracker, name) == expected, (
                f"{selection.value}.{name} did not survive save/reload "
                f"(dropped from decode or save?)"
            )


def test_default_season_folder_token_is_scene_style() -> None:
    defaults = tomlkit.parse(DEFAULT_CONFIG_TOML.read_text(encoding="utf-8"))
    series = cast(MutableMapping[str, Any], defaults["series_management"])
    token = str(series["tvr_season_folder_token"])

    # the dead default used {season}, which is not a real token; the valid
    # token is {season_number}
    assert "{season}" not in token
    assert "{season_number" in token
    # no episode tokens belong in a season-pack folder name
    assert "{episode_number" not in token
    assert "{episode_title_clean}" not in token


def test_default_season_subfolder_token_is_blank() -> None:
    """Blank means "use the season folder token".

    A non-blank packaged default would silently change how every existing
    single-season pack is named, since the same token then stops covering both
    the opened folder and the season inside it.
    """
    defaults = tomlkit.parse(DEFAULT_CONFIG_TOML.read_text(encoding="utf-8"))
    series = cast(MutableMapping[str, Any], defaults["series_management"])

    assert str(series["tvr_season_subfolder_token"]) == ""


def _write_fixture_profile(paths: ConfigPaths, fixture: str) -> tuple[Path, str]:
    """Install a fixture config as the "test" profile. Returns the profile
    path and the exact text written, so a test can assert the file was left
    byte-for-byte untouched."""
    profile = paths.user_configs / "test.toml"
    profile.parent.mkdir(parents=True, exist_ok=True)
    text = (CONFIG_FIXTURE_DIR / fixture).read_text(encoding="utf-8")
    profile.write_text(text, encoding="utf-8")
    return profile, text


def test_load_profile_migrates_schema1_and_archives_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A schema-1 profile migrates fully and keeps an exact rollback copy."""
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    profile, original_text = _write_fixture_profile(paths, "schema1_config.toml")

    manager = ConfigManager("test", paths)  # should migrate, not raise

    reloaded = tomlkit.parse(profile.read_text(encoding="utf-8"))
    assert reloaded["schema_version"] == TomlConfigCodec.SCHEMA_VERSION
    # The group tag folded into [general] on the way up; the two per-media-type
    # keys it came from are gone rather than left behind to drift.
    assert reloaded["general"]["release_group"] == "CustomReleaseGroup"  # type: ignore[reportIndexIssue]
    assert "mvr_release_group" not in reloaded["movie_management"]  # type: ignore[reportOperatorIssue]
    assert "tvr_release_group" not in reloaded["series_management"]  # type: ignore[reportOperatorIssue]
    assert "movie_rename" not in reloaded
    backups = list((profile.parent / "old_configs").glob("test_*.toml"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original_text
    assert manager.settings.general.release_group == "CustomReleaseGroup"
    assert manager.settings.trackers.torrent_leech.username == "custom_tl_user"


def test_load_profile_migrates_schema2_to_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A schema-2 profile migrates while retaining its original contents."""
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    profile, original_text = _write_fixture_profile(paths, "schema2_config.toml")

    manager = ConfigManager("test", paths)  # should migrate, not raise

    reloaded = tomlkit.parse(profile.read_text(encoding="utf-8"))
    assert reloaded["schema_version"] == TomlConfigCodec.SCHEMA_VERSION
    # user settings survive the hop
    assert manager.settings.general.releasers_name == "SchemaTwoUser"
    assert manager.settings.general.release_group == "SchemaTwoGroup"
    assert manager.settings.trackers.last_used_image_host == {}
    # the removed image host is dropped, taking its stale API key with it
    image_hosts = cast(MutableMapping[str, Any], reloaded["image_hosts"])
    assert "ptpimg" not in image_hosts
    tracker_settings = cast(MutableMapping[str, Any], reloaded["tracker"])["settings"]
    assert tracker_settings["last_used_img_host"] == {}
    assert "dead-ptpimg-key" not in profile.read_text(encoding="utf-8")
    backups = list((profile.parent / "old_configs").glob("test_*.toml"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original_text


def test_load_profile_ignores_unknown_last_used_image_hosts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A future/removed tracker or image host must not invalidate a profile."""
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)
    profile = paths.user_configs / "test.toml"
    document = tomlkit.parse(profile.read_text(encoding="utf-8"))
    tracker = cast(MutableMapping[str, Any], document["tracker"])
    tracker_settings = cast(MutableMapping[str, Any], tracker["settings"])
    last_used_hosts = tomlkit.inline_table()
    last_used_hosts["BeyondHD"] = "FutureHost"
    last_used_hosts["FutureTracker"] = "ImageBox"
    tracker_settings["last_used_img_host"] = last_used_hosts
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    manager.load_profile("test")

    assert manager.settings.trackers.last_used_image_host == {}


def test_migration_validation_failure_preserves_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A config that migrates structurally (no `unmapped` sections) but whose
    resulting document fails validation must NOT be written to disk. The
    manager must fall through to the same `ConfigSchemaError`
    archive/regenerate path used when migration can't map sections at all,
    leaving the original file byte-for-byte untouched.
    """
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    profile, fixture_text = _write_fixture_profile(paths, "schema1_config.toml")

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

    with pytest.raises(ConfigError, match="forced migration validation failure"):
        ConfigManager("test", paths)

    # the original schema-1 file must be left completely untouched -- no
    # partial/invalid migrated document was ever persisted
    assert profile.read_text(encoding="utf-8") == fixture_text
    assert not (profile.parent / "old_configs").exists()


def test_schema1_int_tracker_flags_load_as_bool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real release users are on schema 1, which stored the tracker flags as
    the int `0`. Migrating -- to a schema whose default declares them `bool`
    -- must coerce them so the migrated document validates, instead of
    tripping `validate_types` and forcing an archive+regenerate on upgrade.
    """
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    profile, fixture_text = _write_fixture_profile(paths, "schema1_config.toml")
    assert "anonymous = 0" in fixture_text  # guard: the fixture is the int form

    manager = ConfigManager("test", paths)  # must migrate + load, not raise

    assert manager.settings.trackers.beyond_hd.anonymous is False
    saved = tomlkit.parse(profile.read_text(encoding="utf-8"))
    assert saved["schema_version"] == TomlConfigCodec.SCHEMA_VERSION
    saved_tracker = cast(MutableMapping[str, Any], saved["tracker"])
    saved_bhd = cast(MutableMapping[str, Any], saved_tracker["beyond_hd"])
    raw = saved_bhd["anonymous"]
    raw = raw.unwrap() if hasattr(raw, "unwrap") else raw
    assert type(raw) is bool


def test_warning_syntax_color_backfills_when_a_profile_lacks_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A profile written before this key existed gains it on load.

    This is why the key needs no schema bump: `merge_defaults` backfills any
    key the packaged default declares but the profile lacks. If this test ever
    fails, the key would need a migration rather than a default.
    """
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)
    profile = paths.user_configs / "test.toml"
    document = tomlkit.parse(profile.read_text(encoding="utf-8"))
    del document["template_settings"]["warning_syntax_color"]  # type: ignore[reportIndexIssue]
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    manager.load_profile("test")

    assert manager.settings.templates.warning_syntax_color == "#E1401D"


def test_warning_syntax_color_is_written_on_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Covers the write path the read-back test above does not: setting the
    key and saving must persist the value to the profile TOML.
    """
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)

    manager.settings.templates.warning_syntax_color = "#123ABC"
    manager.save()

    profile = paths.user_configs / "test.toml"
    saved = tomlkit.parse(profile.read_text(encoding="utf-8"))
    template_settings = cast(MutableMapping[str, Any], saved["template_settings"])
    assert template_settings["warning_syntax_color"] == "#123ABC"


def test_metadata_transformer_backfills_when_a_profile_lacks_it(
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
    plugin_settings = cast(MutableMapping[str, Any], document["plugins"])
    del plugin_settings["metadata_transformer"]
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    manager.load_profile("test")

    assert manager.settings.plugins.metadata_transformer is None


def test_api_key_is_absent_from_an_upgraded_profile_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Profiles already migrated to v4 had `api_keys` stripped (the old
    `save()` popped it and the old `migrate_v3_to_v4` dropped it). Loading
    one must default the key, not raise, on startup.
    """
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)
    profile = paths.user_configs / "test.toml"
    document = tomlkit.parse(profile.read_text(encoding="utf-8"))
    del document["api_keys"]
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    manager.load_profile("test")  # must not raise

    assert manager.settings.api_keys.tmdb_api_key == ""


def test_api_key_round_trips_through_save_and_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)

    manager.settings.api_keys.tmdb_api_key = "abc123"
    manager.save()
    manager.load_profile("test")

    assert manager.settings.api_keys.tmdb_api_key == "abc123"


def test_metadata_transformer_is_written_on_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)

    manager.settings.plugins.metadata_transformer = "example.provider"
    manager.save()

    profile = paths.user_configs / "test.toml"
    saved = tomlkit.parse(profile.read_text(encoding="utf-8"))
    plugin_settings = cast(MutableMapping[str, Any], saved["plugins"])
    assert plugin_settings["metadata_transformer"] == "example.provider"


def test_post_upload_backfills_when_a_profile_lacks_it(
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
    plugin_settings = cast(MutableMapping[str, Any], document["plugins"])
    del plugin_settings["post_upload"]
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    manager.load_profile("test")

    assert manager.settings.plugins.post_upload is None


def test_post_upload_is_written_on_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)

    manager.settings.plugins.post_upload = "example.notifier"
    manager.save()

    profile = paths.user_configs / "test.toml"
    saved = tomlkit.parse(profile.read_text(encoding="utf-8"))
    plugin_settings = cast(MutableMapping[str, Any], saved["plugins"])
    assert plugin_settings["post_upload"] == "example.notifier"


def test_image_host_uploader_backfills_when_a_profile_lacks_it(
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
    plugin_settings = cast(MutableMapping[str, Any], document["plugins"])
    del plugin_settings["image_host_uploader"]
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    manager.load_profile("test")

    assert manager.settings.plugins.image_host_uploader is None


def test_image_host_uploader_is_written_on_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)

    manager.settings.plugins.image_host_uploader = "example.imghost"
    manager.save()

    profile = paths.user_configs / "test.toml"
    saved = tomlkit.parse(profile.read_text(encoding="utf-8"))
    plugin_settings = cast(MutableMapping[str, Any], saved["plugins"])
    assert plugin_settings["image_host_uploader"] == "example.imghost"


def test_duplicate_checker_backfills_when_a_profile_lacks_it(
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
    plugin_settings = cast(MutableMapping[str, Any], document["plugins"])
    del plugin_settings["duplicate_checker"]
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    manager.load_profile("test")

    assert manager.settings.plugins.duplicate_checker is None


def test_duplicate_checker_is_written_on_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)

    manager.settings.plugins.duplicate_checker = "example.dupechecker"
    manager.save()

    profile = paths.user_configs / "test.toml"
    saved = tomlkit.parse(profile.read_text(encoding="utf-8"))
    plugin_settings = cast(MutableMapping[str, Any], saved["plugins"])
    assert plugin_settings["duplicate_checker"] == "example.dupechecker"
