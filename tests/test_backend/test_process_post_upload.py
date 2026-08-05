from collections.abc import Callable
from pathlib import Path

import pytest

from src.backend.process import ProcessBackEnd
from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.context.processing_context import ProcessingContext
from src.enums.tracker_selection import TrackerSelection
from src.plugins.api import PluginDefinition, PostUploadOutcome, PostUploadRequest
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
    *, plugin_id: str, post_upload: Callable[[PostUploadRequest], None]
) -> PluginDefinition:
    return PluginDefinition(
        display_name=plugin_id,
        version="1.0.0",
        post_upload=post_upload,
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


def test_a_raising_plugin_is_logged_and_does_not_propagate(
    process_backend: ProcessBackEnd,
    plugin_context: ProcessingContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def exploding_post_upload(request: PostUploadRequest) -> None:
        raise RuntimeError("notifier blew up")

    process_backend.config.plugin_manager.register(
        "test.explode",
        _definition(plugin_id="test.explode", post_upload=exploding_post_upload),
        "test",
    )
    process_backend.config.settings.plugins.post_upload = "test.explode"

    process_backend._run_post_upload_plugin(
        cur_tracker=TrackerSelection.MORE_THAN_TV,
        context=plugin_context,
        torrent_path=_any_torrent_path(),
        outcome=PostUploadOutcome.SUCCESS,
        queued_text_update=lambda _text: None,
        queued_text_update_replace_last_line=lambda _text: None,
    )  # must not raise


def test_no_configured_plugin_is_a_clean_no_op(
    process_backend: ProcessBackEnd, plugin_context: ProcessingContext
) -> None:
    process_backend.config.settings.plugins.post_upload = ""

    process_backend._run_post_upload_plugin(
        cur_tracker=TrackerSelection.MORE_THAN_TV,
        context=plugin_context,
        torrent_path=_any_torrent_path(),
        outcome=PostUploadOutcome.SUCCESS,
        queued_text_update=lambda _text: None,
        queued_text_update_replace_last_line=lambda _text: None,
    )  # must not raise


def test_plugins_disabled_skips_the_plugin_entirely(
    process_backend: ProcessBackEnd, plugin_context: ProcessingContext
) -> None:
    called = False

    def should_not_run(request: PostUploadRequest) -> None:
        nonlocal called
        called = True

    process_backend.config.plugin_manager.register(
        "test.disabled",
        _definition(plugin_id="test.disabled", post_upload=should_not_run),
        "test",
    )
    process_backend.config.settings.plugins.post_upload = "test.disabled"
    process_backend.config.settings.general.enable_plugins = False

    process_backend._run_post_upload_plugin(
        cur_tracker=TrackerSelection.MORE_THAN_TV,
        context=plugin_context,
        torrent_path=_any_torrent_path(),
        outcome=PostUploadOutcome.SUCCESS,
        queued_text_update=lambda _text: None,
        queued_text_update_replace_last_line=lambda _text: None,
    )

    assert called is False


def test_outcome_and_error_reach_the_plugin_unchanged(
    process_backend: ProcessBackEnd, plugin_context: ProcessingContext
) -> None:
    received: list[PostUploadRequest] = []

    def notify(request: PostUploadRequest) -> None:
        received.append(request)

    process_backend.config.plugin_manager.register(
        "test.notify",
        _definition(plugin_id="test.notify", post_upload=notify),
        "test",
    )
    process_backend.config.settings.plugins.post_upload = "test.notify"

    process_backend._run_post_upload_plugin(
        cur_tracker=TrackerSelection.AITHER,
        context=plugin_context,
        torrent_path=_any_torrent_path(),
        outcome=PostUploadOutcome.INJECTION_FAILED,
        queued_text_update=lambda _text: None,
        queued_text_update_replace_last_line=lambda _text: None,
        error="client offline",
    )

    assert len(received) == 1
    assert received[0].tracker is TrackerSelection.AITHER
    assert received[0].outcome is PostUploadOutcome.INJECTION_FAILED
    assert received[0].error == "client offline"
