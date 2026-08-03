from collections.abc import Callable
from pathlib import Path

import pytest

from src.backend.process import ProcessBackEnd
from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.context.processing_context import ProcessingContext
from src.enums.tracker_selection import TrackerSelection
from src.plugins.api import PluginDefinition, PreUploadDecision, PreUploadRequest
from tests.repo_paths import DEFAULT_CONFIG_DIR


def _paths(tmp_path: Path) -> ConfigPaths:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    source_defaults = DEFAULT_CONFIG_DIR
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


def _definition(
    *,
    plugin_id: str,
    pre_upload: Callable[[PreUploadRequest], PreUploadDecision],
) -> PluginDefinition:
    """A minimal plugin definition contributing only ``pre_upload``."""
    return PluginDefinition(
        display_name=plugin_id,
        version="1.0.0",
        pre_upload=pre_upload,
    )


def _any_torrent_path() -> Path:
    return Path("release.torrent")


@pytest.fixture
def process_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProcessBackEnd:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    config = ConfigManager("test", _paths(tmp_path))
    config.settings.general.enable_plugins = True
    return ProcessBackEnd(config)


@pytest.fixture
def plugin_context() -> ProcessingContext:
    return ProcessingContext()


def test_a_raising_plugin_returns_an_error_instead_of_propagating(
    process_backend: ProcessBackEnd, plugin_context: ProcessingContext
) -> None:
    def exploding_pre_upload(request: PreUploadRequest) -> PreUploadDecision:
        raise RuntimeError("plugin blew up")

    process_backend.config.plugin_manager.register(
        "test.explode",
        _definition(plugin_id="test.explode", pre_upload=exploding_pre_upload),
        "test",
    )
    process_backend.config.settings.plugins.pre_upload = "test.explode"

    decision, error = process_backend._run_pre_upload_plugin(
        cur_tracker=TrackerSelection.MORE_THAN_TV,
        context=plugin_context,
        torrent_path=_any_torrent_path(),
        queued_text_update=lambda _text: None,
        queued_text_update_replace_last_line=lambda _text: None,
    )

    assert decision is None
    assert error is not None
    assert "plugin blew up" in error


def test_a_failure_on_one_tracker_leaves_the_next_one_working(
    process_backend: ProcessBackEnd, plugin_context: ProcessingContext
) -> None:
    """The containment property: a raising plugin must not poison later calls."""
    calls: list[TrackerSelection] = []

    def fails_only_for_the_first(request: PreUploadRequest) -> PreUploadDecision:
        calls.append(request.tracker)
        if len(calls) == 1:
            raise RuntimeError("first tracker only")
        return PreUploadDecision.CONTINUE

    process_backend.config.plugin_manager.register(
        "test.flaky",
        _definition(plugin_id="test.flaky", pre_upload=fails_only_for_the_first),
        "test",
    )
    process_backend.config.settings.plugins.pre_upload = "test.flaky"

    first_decision, first_error = process_backend._run_pre_upload_plugin(
        cur_tracker=TrackerSelection.MORE_THAN_TV,
        context=plugin_context,
        torrent_path=_any_torrent_path(),
        queued_text_update=lambda _text: None,
        queued_text_update_replace_last_line=lambda _text: None,
    )
    second_decision, second_error = process_backend._run_pre_upload_plugin(
        cur_tracker=TrackerSelection.TORRENT_LEECH,
        context=plugin_context,
        torrent_path=_any_torrent_path(),
        queued_text_update=lambda _text: None,
        queued_text_update_replace_last_line=lambda _text: None,
    )

    assert first_decision is None
    assert first_error is not None
    assert second_error is None
    assert second_decision is PreUploadDecision.CONTINUE
    assert len(calls) == 2


def test_no_configured_plugin_is_a_clean_no_op(
    process_backend: ProcessBackEnd, plugin_context: ProcessingContext
) -> None:
    process_backend.config.settings.plugins.pre_upload = ""

    decision, error = process_backend._run_pre_upload_plugin(
        cur_tracker=TrackerSelection.MORE_THAN_TV,
        context=plugin_context,
        torrent_path=_any_torrent_path(),
        queued_text_update=lambda _text: None,
        queued_text_update_replace_last_line=lambda _text: None,
    )

    assert decision is None
    assert error is None


def test_plugins_disabled_skips_the_plugin_entirely(
    process_backend: ProcessBackEnd, plugin_context: ProcessingContext
) -> None:
    called = False

    def should_not_run(request: PreUploadRequest) -> PreUploadDecision:
        nonlocal called
        called = True
        return PreUploadDecision.CONTINUE

    process_backend.config.plugin_manager.register(
        "test.disabled",
        _definition(plugin_id="test.disabled", pre_upload=should_not_run),
        "test",
    )
    process_backend.config.settings.plugins.pre_upload = "test.disabled"
    process_backend.config.settings.general.enable_plugins = False

    decision, error = process_backend._run_pre_upload_plugin(
        cur_tracker=TrackerSelection.MORE_THAN_TV,
        context=plugin_context,
        torrent_path=_any_torrent_path(),
        queued_text_update=lambda _text: None,
        queued_text_update_replace_last_line=lambda _text: None,
    )

    assert called is False
    assert decision is None
    assert error is None
