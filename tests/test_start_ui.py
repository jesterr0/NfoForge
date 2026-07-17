"""Startup config-error recovery routing tests.

`start_ui.NfoForge` drives real Qt widgets (`QApplication`, splash screen,
message boxes) that aren't worth standing up just to prove routing logic, so
these tests construct a bare `NfoForge` instance (via `object.__new__`,
bypassing `__init__`) and drive `_continue_init` directly, stubbing out the
handler methods/collaborators it calls. This isolates exactly the thing task
3.3 changes: which except clause and which recovery handler a given
exception routes to.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

import start_ui
from src.config.paths import ConfigPaths
from src.exceptions import ConfigError, ConfigSchemaError


def _bare_nfoforge(config_file: str | None) -> start_ui.NfoForge:
    app = object.__new__(start_ui.NfoForge)
    app.config_file = config_file
    app.splash_screen = SimpleNamespace(updateMessageBox=lambda *_a, **_k: None)
    return app


def test_plain_config_error_routes_to_generic_recovery_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `ConfigError` that is NOT a `ConfigSchemaError` (e.g. a genuinely
    invalid value/type surviving `validate_types`) must be offered the
    archive+regenerate recovery path, not routed to the fatal
    `_error_on_splash` quit path.
    """
    monkeypatch.setattr(
        start_ui,
        "ConfigManager",
        lambda config_file: (_ for _ in ()).throw(ConfigError("boom")),
    )
    test_paths = ConfigPaths(
        default_config=tmp_path / "default_config.toml",
        default_program=tmp_path / "default_program_conf.toml",
        program=tmp_path / "program" / "conf.toml",
        user_configs=tmp_path / "user",
        tracker_cookies=tmp_path / "cookies",
    )
    monkeypatch.setattr(start_ui, "ConfigPaths", lambda: test_paths)

    recovery_calls = []
    monkeypatch.setattr(
        start_ui.NfoForge,
        "_offer_archive_and_regenerate",
        lambda self, config_path, error_text, issue_description, title: (
            recovery_calls.append((config_path, error_text, issue_description, title))
        ),
    )
    fatal_calls = []
    monkeypatch.setattr(
        start_ui.NfoForge,
        "_error_on_splash",
        lambda self, error: fatal_calls.append(error),
    )

    app = _bare_nfoforge("test")
    app._continue_init()

    assert fatal_calls == []
    assert len(recovery_calls) == 1
    config_path, error_text, issue_description, title = recovery_calls[0]
    assert config_path == test_paths.user_configs / "test.toml"
    assert "boom" in error_text
    assert "invalid or unsupported value" in issue_description
    # a generic value-error ConfigError isn't a schema incompatibility, so
    # the dialog title must say so rather than reusing the schema wording
    assert title == "Invalid Config"


def test_config_error_falls_back_to_fatal_when_path_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the failing config's path can't be determined at all (no config
    file requested and no on-disk program conf to read one from), there is
    nothing to archive/regenerate, so the fatal path is still correct.
    """
    monkeypatch.setattr(
        start_ui,
        "ConfigManager",
        lambda config_file: (_ for _ in ()).throw(ConfigError("boom")),
    )
    unresolvable_paths = ConfigPaths(
        default_config=Path("does-not-matter.toml"),
        default_program=Path("does-not-matter.toml"),
        program=Path("nonexistent") / "conf.toml",
        user_configs=Path("nonexistent") / "user",
        tracker_cookies=Path("nonexistent") / "cookies",
    )
    monkeypatch.setattr(start_ui, "ConfigPaths", lambda: unresolvable_paths)

    recovery_calls = []
    monkeypatch.setattr(
        start_ui.NfoForge,
        "_offer_archive_and_regenerate",
        lambda self, *a: recovery_calls.append(a),
    )
    fatal_calls = []
    monkeypatch.setattr(
        start_ui.NfoForge,
        "_error_on_splash",
        lambda self, error: fatal_calls.append(error),
    )

    app = _bare_nfoforge(None)
    app._continue_init()

    assert recovery_calls == []
    assert fatal_calls == ["boom"]


def test_resolve_config_path_defaults_missing_current_config_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_resolve_config_path` must default a missing `current_config` key
    to "config", matching `ConfigManager.decode_program`'s default, instead
    of giving up and returning `None`.
    """
    program_path = tmp_path / "program" / "conf.toml"
    program_path.parent.mkdir(parents=True, exist_ok=True)
    program_path.write_text('main_window_position = ""\n', encoding="utf-8")
    test_paths = ConfigPaths(
        default_config=tmp_path / "default_config.toml",
        default_program=tmp_path / "default_program_conf.toml",
        program=program_path,
        user_configs=tmp_path / "user",
        tracker_cookies=tmp_path / "cookies",
    )
    monkeypatch.setattr(start_ui, "ConfigPaths", lambda: test_paths)

    app = _bare_nfoforge(None)

    assert app._resolve_config_path() == test_paths.user_configs / "config.toml"


def test_schema_error_recovery_uses_incompatible_config_title() -> None:
    """A `ConfigSchemaError` is a genuine schema incompatibility (unlike a
    generic value-error `ConfigError`), so its recovery dialog must keep the
    "Incompatible Config" title rather than the generic "Invalid Config"
    one.
    """
    recovery_calls = []
    app = _bare_nfoforge("test")
    app._offer_archive_and_regenerate = (
        lambda config_path, error_text, issue_description, title: (
            recovery_calls.append((config_path, error_text, issue_description, title))
        )
    )

    app._handle_config_schema_error(
        ConfigSchemaError("bad schema", config_path=Path("test.toml"))
    )

    assert len(recovery_calls) == 1
    _config_path, _error_text, _issue_description, title = recovery_calls[0]
    assert title == "Incompatible Config"


def test_config_schema_error_still_prefers_schema_specific_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ConfigSchemaError` is a subclass of `ConfigError`; the schema-specific
    (migrate-flavored) handler must still take precedence over the new
    generic `ConfigError` recovery handler.
    """
    monkeypatch.setattr(
        start_ui,
        "ConfigManager",
        lambda config_file: (_ for _ in ()).throw(
            ConfigSchemaError("bad schema", config_path=Path("test.toml"))
        ),
    )
    schema_calls = []
    generic_calls = []
    monkeypatch.setattr(
        start_ui.NfoForge,
        "_handle_config_schema_error",
        lambda self, error: schema_calls.append(error),
    )
    monkeypatch.setattr(
        start_ui.NfoForge,
        "_handle_config_error",
        lambda self, error: generic_calls.append(error),
    )

    app = _bare_nfoforge("test")
    app._continue_init()

    assert len(schema_calls) == 1
    assert generic_calls == []
