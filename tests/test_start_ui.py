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

from src.config.paths import AppPaths
from src.exceptions import ConfigError, ConfigSchemaError
import start_ui
from tests.repo_paths import build_app_paths


def _bare_nfoforge(config_file: str | None) -> start_ui.NfoForge:
    app = object.__new__(start_ui.NfoForge)
    app.config_file = config_file
    app.splash_screen = SimpleNamespace(updateMessageBox=lambda *_a, **_k: None)  # type: ignore[reportAttributeAccessIssue]
    app.program_config_malformed = False
    return app


def _bare_nfoforge_with_config() -> start_ui.NfoForge:
    """`_bare_nfoforge` plus a stub `config`, for `_maybe_prompt_template_migration`
    tests -- that method only touches `self.config.program.
    suppress_template_token_prompt` and `self.config.save_program()`, so a
    `SimpleNamespace` stub is enough without standing up a real `ConfigManager`.
    """
    app = _bare_nfoforge(None)
    app.config = SimpleNamespace(  # type: ignore[reportAttributeAccessIssue]
        program=SimpleNamespace(suppress_template_token_prompt=False),
        save_program=lambda: None,
    )
    return app


def _stub_dialog_class(migrate_requested: bool, suppress_future_prompts: bool) -> type:
    """A `TemplateMigrationDialog` stand-in with fixed post-`exec()` results.

    Used by tests that only care what `_maybe_prompt_template_migration` does
    with the two flags it reads off the dialog -- not with any real Qt
    widget or user interaction.
    """

    class _StubDialog:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.migrate_requested = migrate_requested
            self.suppress_future_prompts = suppress_future_prompts

        def exec(self) -> None:
            return None

        def deleteLater(self) -> None:
            return None

    return _StubDialog


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
    test_paths = build_app_paths(tmp_path)
    monkeypatch.setattr(start_ui, "default_paths", lambda: test_paths)

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
    unresolvable_paths = AppPaths(
        state_root=Path("nonexistent"), asset_root=Path("nonexistent")
    )
    monkeypatch.setattr(start_ui, "default_paths", lambda: unresolvable_paths)

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
    test_paths = build_app_paths(tmp_path)
    test_paths.program.parent.mkdir(parents=True, exist_ok=True)
    test_paths.program.write_text('main_window_position = ""\n', encoding="utf-8")
    monkeypatch.setattr(start_ui, "default_paths", lambda: test_paths)

    app = _bare_nfoforge(None)

    assert app._resolve_config_path() == test_paths.user_configs / "config.toml"


def test_malformed_program_config_offers_recovery_not_a_fatal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A syntactically broken `program/conf.toml` is its own small,
    recoverable problem -- it holds only the active profile name and the
    window position -- and must be distinguishable from "no config named"
    (both currently collapse to `_resolve_config_path` returning `None`) so
    `_handle_config_error` can offer to regenerate it instead of falling
    through to the fatal quit path.
    """
    test_paths = build_app_paths(tmp_path)
    test_paths.program.parent.mkdir(parents=True, exist_ok=True)
    test_paths.program.write_text('current_config = "unterminated', encoding="utf-8")
    monkeypatch.setattr(start_ui, "default_paths", lambda: test_paths)

    app = _bare_nfoforge(None)
    result = app._resolve_config_path()

    # A malformed program config is distinguishable from "no config named".
    assert result is None
    assert app.program_config_malformed is True


def test_handle_config_error_routes_malformed_program_config_to_its_own_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_handle_config_error` must offer the program-config-specific
    recovery (regenerate, not archive-and-reset-settings) when the reason
    `_resolve_config_path` returned `None` is a malformed program config --
    not the fatal `_error_on_splash` quit path, and not the profile
    archive+regenerate path (which would show the wrong, more alarming
    "settings will reset" wording for a file that holds none).
    """
    test_paths = build_app_paths(tmp_path)
    test_paths.program.parent.mkdir(parents=True, exist_ok=True)
    test_paths.program.write_text('current_config = "unterminated', encoding="utf-8")
    monkeypatch.setattr(start_ui, "default_paths", lambda: test_paths)

    program_reset_calls = []
    monkeypatch.setattr(
        start_ui.NfoForge,
        "_offer_program_config_reset",
        lambda self, error_text: program_reset_calls.append(error_text),
    )
    archive_calls = []
    monkeypatch.setattr(
        start_ui.NfoForge,
        "_offer_archive_and_regenerate",
        lambda self, *a: archive_calls.append(a),
    )
    fatal_calls = []
    monkeypatch.setattr(
        start_ui.NfoForge,
        "_error_on_splash",
        lambda self, error: fatal_calls.append(error),
    )

    app = _bare_nfoforge(None)
    app._handle_config_error(ConfigError("boom"))

    assert program_reset_calls == ["boom"]
    assert archive_calls == []
    assert fatal_calls == []


def test_resolve_config_path_detects_malformed_program_config_even_with_a_known_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ConfigManager.load_program` parses `program/conf.toml` on every
    init regardless of whether a profile name was already supplied (e.g.
    via `-c/--config`, or via the multi-profile splash selector, which
    only globs `user_configs` and never touches the program config).
    Detection must therefore not be gated behind "no config file was
    given": a malformed program config must be caught even when
    `config_file` is already known, not silently skipped in favor of
    resolving that (fine) profile's path.
    """
    test_paths = build_app_paths(tmp_path)
    test_paths.program.parent.mkdir(parents=True, exist_ok=True)
    test_paths.program.write_text('current_config = "unterminated', encoding="utf-8")
    monkeypatch.setattr(start_ui, "default_paths", lambda: test_paths)

    app = _bare_nfoforge("test")
    result = app._resolve_config_path()

    assert result is None
    assert app.program_config_malformed is True


def test_malformed_program_config_takes_priority_over_a_known_profile_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for a data-loss loop: with a profile name already
    known (as if selected via the splash selector, or passed with
    `-c/--config`) and the program config also malformed, `_handle_config_error`
    must still route to the program-config recovery dialog -- never to the
    profile archive+regenerate dialog, which would discard a perfectly
    good profile on every launch while never touching the file that is
    actually broken (the program config, which `_offer_archive_and_regenerate`
    doesn't even look at).
    """
    test_paths = build_app_paths(tmp_path)
    test_paths.program.parent.mkdir(parents=True, exist_ok=True)
    test_paths.program.write_text('current_config = "unterminated', encoding="utf-8")
    monkeypatch.setattr(start_ui, "default_paths", lambda: test_paths)
    monkeypatch.setattr(
        start_ui,
        "ConfigManager",
        lambda config_file: (_ for _ in ()).throw(ConfigError("boom")),
    )

    program_reset_calls = []
    monkeypatch.setattr(
        start_ui.NfoForge,
        "_offer_program_config_reset",
        lambda self, error_text: program_reset_calls.append(error_text),
    )
    archive_calls = []
    monkeypatch.setattr(
        start_ui.NfoForge,
        "_offer_archive_and_regenerate",
        lambda self, *a: archive_calls.append(a),
    )

    # A profile name is already known, yet the program config is still
    # malformed -- the realistic case is the multi-profile splash selector,
    # which resolves and sets `config_file` without ever reading the
    # program config.
    app = _bare_nfoforge("test")
    app._continue_init()

    assert program_reset_calls == ["boom"]
    # The critical assertion: a known-good profile must not be archived.
    assert archive_calls == []


def test_last_used_config_is_returned_only_when_profile_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_paths = build_app_paths(tmp_path)
    test_paths.program.parent.mkdir(parents=True, exist_ok=True)
    test_paths.program.write_text('current_config = "second"\n', encoding="utf-8")
    monkeypatch.setattr(start_ui, "default_paths", lambda: test_paths)

    app = _bare_nfoforge(None)

    assert app._get_last_used_config(["first", "second"]) == "second"
    assert app._get_last_used_config(["first"]) is None


def test_schema_error_recovery_uses_incompatible_config_title() -> None:
    """A `ConfigSchemaError` is a genuine schema incompatibility (unlike a
    generic value-error `ConfigError`), so its recovery dialog must keep the
    "Incompatible Config" title rather than the generic "Invalid Config"
    one.
    """
    recovery_calls = []
    app = _bare_nfoforge("test")
    app._offer_archive_and_regenerate = (
        lambda config_path, error_text, issue_description, title: recovery_calls.append(
            (config_path, error_text, issue_description, title)
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


def test_template_prompt_is_skipped_when_suppressed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def record_scan(_: Path) -> list[object]:
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(start_ui, "scan_template_dir", record_scan)

    app = _bare_nfoforge_with_config()
    app.config.program.suppress_template_token_prompt = True
    app._maybe_prompt_template_migration()

    assert called is False


def test_template_prompt_is_skipped_when_no_template_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(start_ui, "scan_template_dir", lambda _: [])
    shown = False

    def record_dialog(*args: object, **kwargs: object) -> None:
        nonlocal shown
        shown = True

    monkeypatch.setattr(start_ui, "TemplateMigrationDialog", record_dialog)

    app = _bare_nfoforge_with_config()
    app.config.program.suppress_template_token_prompt = False
    app._maybe_prompt_template_migration()

    assert shown is False


def test_a_scanner_failure_never_blocks_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(_: Path) -> list[object]:
        raise OSError("disk gone")

    monkeypatch.setattr(start_ui, "scan_template_dir", explode)

    app = _bare_nfoforge_with_config()
    app.config.program.suppress_template_token_prompt = False

    # Must not raise: a convenience prompt cannot prevent the app launching.
    app._maybe_prompt_template_migration()


def test_declining_the_prompt_does_not_migrate_templates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The consent gate itself: a decline must never touch the user's files.

    None of the other startup tests assert this -- they cover suppressed,
    empty-reports, and scanner-exception, but not the accept/decline branch
    that actually guards the destructive call.
    """
    reports_stub = [object()]
    monkeypatch.setattr(start_ui, "scan_template_dir", lambda _: reports_stub)
    monkeypatch.setattr(
        start_ui,
        "TemplateMigrationDialog",
        _stub_dialog_class(migrate_requested=False, suppress_future_prompts=False),
    )

    migrate_calls: list[object] = []
    monkeypatch.setattr(
        start_ui,
        "migrate_templates",
        lambda reports: migrate_calls.append(reports) or [],
    )

    app = _bare_nfoforge_with_config()
    app.config.program.suppress_template_token_prompt = False
    app._maybe_prompt_template_migration()

    assert migrate_calls == []


def test_accepting_the_prompt_migrates_templates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The consent gate itself: an accept must actually run the migration."""
    reports_stub = [object()]
    monkeypatch.setattr(start_ui, "scan_template_dir", lambda _: reports_stub)
    monkeypatch.setattr(
        start_ui,
        "TemplateMigrationDialog",
        _stub_dialog_class(migrate_requested=True, suppress_future_prompts=False),
    )

    migrate_calls: list[object] = []

    def record_migrate(reports: object) -> list[object]:
        migrate_calls.append(reports)
        return []

    monkeypatch.setattr(start_ui, "migrate_templates", record_migrate)
    # A successful migration shows a modal QMessageBox; stub it out so the
    # test doesn't block waiting for a click.
    monkeypatch.setattr(start_ui.QMessageBox, "information", lambda *a, **k: None)

    app = _bare_nfoforge_with_config()
    app.config.program.suppress_template_token_prompt = False
    app._maybe_prompt_template_migration()

    assert migrate_calls == [reports_stub]


def test_a_suppression_save_failure_does_not_block_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure persisting "don't ask again" must not swallow the migration
    the user just asked for, and must not escape as an exception -- it is
    logged instead. Guards against re-introducing the ordering bug where
    `save_program()` ran (and could raise) before `migrate_templates`.
    """
    reports_stub = [object()]
    monkeypatch.setattr(start_ui, "scan_template_dir", lambda _: reports_stub)
    monkeypatch.setattr(
        start_ui,
        "TemplateMigrationDialog",
        _stub_dialog_class(migrate_requested=True, suppress_future_prompts=True),
    )

    migrate_calls: list[object] = []

    def record_migrate(reports: object) -> list[object]:
        migrate_calls.append(reports)
        return []

    monkeypatch.setattr(start_ui, "migrate_templates", record_migrate)
    monkeypatch.setattr(start_ui.QMessageBox, "information", lambda *a, **k: None)

    app = _bare_nfoforge_with_config()
    app.config.program.suppress_template_token_prompt = False

    def explode_save() -> None:
        raise ConfigError("disk full")

    app.config.save_program = explode_save

    # Must not raise, and the migration must still have run.
    app._maybe_prompt_template_migration()

    assert migrate_calls == [reports_stub]


# ---------------------------------------------------------------------------
# layout migration, which runs before anything reads configuration
# ---------------------------------------------------------------------------
def _nfoforge_for_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> start_ui.NfoForge:
    """A bare instance with the two branches `_init_app` chooses between stubbed."""
    app = _bare_nfoforge(None)
    app.selected = False  # type: ignore[reportAttributeAccessIssue]
    app.migration_started = False  # type: ignore[reportAttributeAccessIssue]
    app.errors = []  # type: ignore[reportAttributeAccessIssue]
    monkeypatch.setattr(
        start_ui.NfoForge,
        "_select_config",
        lambda self: setattr(self, "selected", True),
    )
    monkeypatch.setattr(
        start_ui.NfoForge,
        "_start_layout_migration",
        lambda self: setattr(self, "migration_started", True),
    )
    monkeypatch.setattr(
        start_ui.NfoForge,
        "_error_on_splash",
        lambda self, text: self.errors.append(text),
    )
    monkeypatch.setattr(
        start_ui,
        "default_paths",
        lambda: AppPaths(state_root=tmp_path / "data", asset_root=tmp_path / "assets"),
    )
    return app


def test_a_current_layout_goes_straight_to_choosing_a_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The launch nearly everyone takes: no thread, no dialog, no delay."""
    app = _nfoforge_for_startup(monkeypatch, tmp_path)
    monkeypatch.setattr(start_ui, "migration_pending", lambda _root: False)

    app._init_app()

    assert app.selected is True  # type: ignore[reportAttributeAccessIssue]
    assert app.migration_started is False  # type: ignore[reportAttributeAccessIssue]


def test_a_pending_migration_runs_before_any_profile_is_chosen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The profile list lives in the folder the migration is still assembling.

    Choosing first would offer a user with several profiles none of them, because
    they have not been imported yet.
    """
    app = _nfoforge_for_startup(monkeypatch, tmp_path)
    monkeypatch.setattr(start_ui, "migration_pending", lambda _root: True)

    app._init_app()

    assert app.migration_started is True  # type: ignore[reportAttributeAccessIssue]
    assert app.selected is False  # type: ignore[reportAttributeAccessIssue]


def test_an_unreadable_layout_record_stops_the_launch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Not knowing whether the folder was migrated is a reason to stop.

    Guessing risks running the migration a second time over a tree that already
    had it, so the launch reports and goes no further -- it does not fall through
    to loading a configuration out of a folder of unknown shape.
    """
    app = _nfoforge_for_startup(monkeypatch, tmp_path)

    def explode(_root: Path) -> bool:
        raise start_ui.LayoutRecordError("layout.json is not valid JSON")

    monkeypatch.setattr(start_ui, "migration_pending", explode)

    app._init_app()

    assert app.errors and "layout.json" in app.errors[0]  # type: ignore[reportAttributeAccessIssue]
    assert app.selected is False  # type: ignore[reportAttributeAccessIssue]
    assert app.migration_started is False  # type: ignore[reportAttributeAccessIssue]


def test_the_summary_is_shown_then_the_launch_continues(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _nfoforge_for_startup(monkeypatch, tmp_path)
    shown: list[tuple[object, object]] = []

    class _StubSummary:
        def __init__(self, run: object, **_kwargs: object) -> None:
            shown.append(run)

        def exec(self) -> None:
            return None

        def deleteLater(self) -> None:
            return None

    monkeypatch.setattr(start_ui, "MigrationSummaryDialog", _StubSummary)
    run = SimpleNamespace(plan=object(), outcome=object(), missing_profile="")

    app._on_migration_finished(run)  # type: ignore[arg-type]

    assert shown == [run]
    assert app.selected is True  # type: ignore[reportAttributeAccessIssue]


def test_nothing_is_shown_when_there_was_nothing_to_migrate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`startup_migration` answers None for an up-to-date folder.

    Reached when the record said a hop was pending and the work turned out to be
    already done -- another copy of the application got there first, say.
    """
    app = _nfoforge_for_startup(monkeypatch, tmp_path)
    shown: list[object] = []
    monkeypatch.setattr(
        start_ui, "MigrationSummaryDialog", lambda *a, **k: shown.append(a)
    )

    app._on_migration_finished(None)

    assert shown == []
    assert app.selected is True  # type: ignore[reportAttributeAccessIssue]


def test_the_worker_always_gets_an_answer_even_if_the_dialog_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A lost answer leaves startup stopped on a splash screen with no error.

    The worker is blocked waiting, so every way of leaving the dialog -- including
    one that never opened -- has to deliver something.
    """
    app = _bare_nfoforge(None)
    answers: list[object] = []
    app._migration_relay = SimpleNamespace(answer=answers.append)  # type: ignore[reportAttributeAccessIssue]

    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("the dialog could not be built")

    monkeypatch.setattr(start_ui, "MigrationPromptDialog", explode)

    with pytest.raises(RuntimeError):
        app._ask_where_to_import(None)

    assert answers == [None]
