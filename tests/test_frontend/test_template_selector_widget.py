from copy import deepcopy
from pathlib import Path
import re

import pytest

from src.backend.utils.example_parsed_series_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD,
    EXAMPLE_SEARCH_PAYLOAD,
)
from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.context.processing_context import ProcessingContext
from src.frontend.custom_widgets.basic_code_editor import HighlightKeywords
from src.frontend.custom_widgets.template_selector import (
    TemplateSelector,
    saved_status_message,
)
from src.plugins.api import PluginDefinition, TokenReplaceRequest


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


def _make_selector(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TemplateSelector:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    manager = ConfigManager("test", _paths(tmp_path))
    return TemplateSelector(
        config=manager,
        context=ProcessingContext(),
        sandbox=False,
        main_window=None,  # type: ignore[reportArgumentType]
        parent=None,
    )


WARNING_COLOR = "#e1401d"


def _static_patterns() -> list[HighlightKeywords]:
    return [
        HighlightKeywords(re.compile(r"\{%.*?%\}"), "#A4036F", False),
        HighlightKeywords(re.compile(r"\{\{.*?\}\}"), "#048BA8", False),
    ]


def test_set_syntax_highlights_applies_the_patterns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selector = _make_selector(tmp_path, monkeypatch)
    patterns = _static_patterns()

    selector.set_syntax_highlights(patterns, WARNING_COLOR)

    assert selector.text_edit.highlighter.patterns_colors == patterns


def test_set_syntax_highlights_replaces_rather_than_accumulates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selector = _make_selector(tmp_path, monkeypatch)

    selector.set_syntax_highlights(_static_patterns(), WARNING_COLOR)
    selector.set_syntax_highlights(_static_patterns(), WARNING_COLOR)

    assert len(selector.text_edit.highlighter.patterns_colors) == 2


def test_set_syntax_highlights_replaces_rather_than_accumulates_the_warning_pattern(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The invariant above is meaningless while `unknown_tokens` is empty, since
    # there is no warning pattern either way. With one present and refreshed,
    # reapplying the static patterns must rebuild -- not lose or duplicate --
    # the warning pattern.
    selector = _make_selector(tmp_path, monkeypatch)
    selector.set_syntax_highlights(_static_patterns(), WARNING_COLOR)
    selector.text_edit.setPlainText("{{ mi_video_codec }}")
    selector._refresh_unknown_tokens()

    selector.set_syntax_highlights(_static_patterns(), WARNING_COLOR)

    assert (
        len(selector.text_edit.highlighter.patterns_colors)
        == len(_static_patterns()) + 1
    )


def test_unknown_token_pattern_is_appended_after_the_static_patterns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Order matters: the highlighter applies patterns in list order and later
    # `setFormat` calls overwrite earlier ones for the same span, so the
    # warning color must be applied after the variable color to win.
    selector = _make_selector(tmp_path, monkeypatch)
    selector.set_syntax_highlights(_static_patterns(), WARNING_COLOR)
    selector.text_edit.setPlainText("{{ mi_video_codec }}")

    selector._refresh_unknown_tokens()

    applied = selector.text_edit.highlighter.patterns_colors
    assert len(applied) == 3
    assert applied[-1].color.lower() == "#e1401d"
    assert applied[-1].pattern.findall("{{ mi_video_codec }}") == ["mi_video_codec"]


def test_no_extra_pattern_when_every_token_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selector = _make_selector(tmp_path, monkeypatch)
    selector.set_syntax_highlights(_static_patterns(), WARNING_COLOR)
    selector.text_edit.setPlainText("{{ video_bit_rate }}")

    selector._refresh_unknown_tokens()

    assert len(selector.text_edit.highlighter.patterns_colors) == 2
    assert selector.unknown_tokens == set()


def test_unknown_tokens_are_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selector = _make_selector(tmp_path, monkeypatch)
    selector.text_edit.setPlainText(
        "{{ mi_video_codec }} / {{ video_bit_rate }} / {{ mi_video_bit_rate }}"
    )

    selector._refresh_unknown_tokens()

    assert selector.unknown_tokens == {"mi_video_codec", "mi_video_bit_rate"}


def test_unparseable_template_clears_the_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selector = _make_selector(tmp_path, monkeypatch)
    selector.set_syntax_highlights(_static_patterns(), WARNING_COLOR)
    selector.text_edit.setPlainText("{% if %}")

    selector._refresh_unknown_tokens()

    assert selector.unknown_tokens == set()
    assert len(selector.text_edit.highlighter.patterns_colors) == 2


def test_blank_warning_color_skips_the_warning_pattern(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Mirrors the `if <color>:` guard the three static colors already use in
    # `jinja_syntax_highlights`: a blank color means no highlight pattern,
    # not a fallback lookup. The selector holds no config knowledge of its
    # own to fall back to.
    selector = _make_selector(tmp_path, monkeypatch)
    patterns = _static_patterns()
    selector.set_syntax_highlights(patterns, "")
    selector.text_edit.setPlainText("{{ mi_video_codec }}")

    selector._refresh_unknown_tokens()

    applied = selector.text_edit.highlighter.patterns_colors
    assert applied == patterns


def test_warning_color_comes_from_the_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # There is no config path left to override: every color, including the
    # warning color, is supplied by the caller.
    selector = _make_selector(tmp_path, monkeypatch)
    selector.set_syntax_highlights(_static_patterns(), "#00ff00")
    selector.text_edit.setPlainText("{{ mi_video_codec }}")

    selector._refresh_unknown_tokens()

    applied = selector.text_edit.highlighter.patterns_colors
    assert applied[-1].color.lower() == "#00ff00"


def test_series_preview_fills_the_season_number_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selector = _make_selector(tmp_path, monkeypatch)
    selector.context = ProcessingContext(
        media_input=deepcopy(EXAMPLE_MEDIA_INPUT_PAYLOAD),
        media_search=deepcopy(EXAMPLE_SEARCH_PAYLOAD),
    )
    selector.template_combo.addItem("series_preview")
    selector.template_combo.setCurrentText("series_preview")
    selector.text_edit.setPlainText("Season={{ season_number }}")
    selector.preview_btn.setChecked(True)

    selector.preview_template()

    assert selector.text_edit.toPlainText() == "Season=1"


def test_preview_button_unchecks_when_input_path_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `preview_template` used to raise with `preview_btn` still checked,
    # leaving preview mode "on" with nothing previewed and no way to retry
    # without manually unchecking the button first.
    selector = _make_selector(tmp_path, monkeypatch)
    selector.template_combo.addItem("template")
    selector.template_combo.setCurrentText("template")
    selector.preview_btn.setChecked(True)

    with pytest.raises(FileNotFoundError):
        selector.preview_template()

    assert selector.preview_btn.isChecked() is False


def test_status_message_is_unchanged_when_everything_resolves() -> None:
    assert saved_status_message(0) == "Saved template"


def test_status_message_is_singular_for_one_unknown_token() -> None:
    assert saved_status_message(1) == "Saved template - 1 unrecognized token"


def test_status_message_is_plural_for_several_unknown_tokens() -> None:
    assert saved_status_message(3) == "Saved template - 3 unrecognized tokens"


def _selector_with_plugin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plugin: object,
    template_name: str = "shared_template",
    assign_to: int = 1,
) -> TemplateSelector:
    """A selector wired to a fake token replacer plugin.

    ``assign_to`` is how many trackers point their NFO template at
    ``template_name``, which is what decides whether the plugin is called at all.
    """
    selector = _make_selector(tmp_path, monkeypatch)
    selector.config.settings.general.enable_plugins = True
    selector.config.settings.plugins.token_replacer = "fake_plugin"
    selector.config.plugin_manager.register(
        "fake_plugin",
        PluginDefinition(
            display_name="Fake Plugin",
            version="1.0.0",
            token_replacer=plugin,  # type: ignore[reportArgumentType]
        ),
        "test",
    )
    for tracker in list(selector.config.settings.trackers.by_selection())[:assign_to]:
        selector.config.settings.trackers.by_selection()[
            tracker
        ].nfo_template = template_name
    selector.template_combo.addItem(template_name)
    selector.template_combo.setCurrentText(template_name)
    return selector


def test_preview_passes_the_context_and_the_dummy_flag_to_the_plugin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the preview used to omit context entirely, which every plugin needing one
    # rejected, leaving its tokens raw
    seen: dict = {}

    def fake_plugin(request: TokenReplaceRequest) -> str:
        seen["request"] = request
        return "filled"

    selector = _selector_with_plugin(tmp_path, monkeypatch, fake_plugin)

    assert selector._apply_token_replacer_plugin("{plugin_token}") == "filled"
    request = seen["request"]
    assert request.context is selector.context
    assert request.preview is True
    assert request.tracker_images is None
    assert len(request.trackers) == 1


def test_preview_skips_the_plugin_when_the_template_is_not_unique_to_one_tracker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # processing always calls the plugin for exactly one tracker; with two there
    # is no format to render as, so the tokens are left rather than guessed at
    calls = []

    def fake_plugin(request: TokenReplaceRequest) -> str:
        calls.append(request)
        return "filled"

    selector = _selector_with_plugin(tmp_path, monkeypatch, fake_plugin, assign_to=2)

    assert selector._apply_token_replacer_plugin("{plugin_token}") == "{plugin_token}"
    assert calls == []


def test_preview_reports_a_plugin_failure_instead_of_discarding_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the failure used to be swallowed, so a plugin that could not render looked
    # identical to a broken template
    warnings = []

    def fake_plugin(_request: TokenReplaceRequest) -> str:
        raise ValueError("no images for Aither")

    monkeypatch.setattr(
        "src.frontend.custom_widgets.template_selector.QMessageBox.warning",
        lambda *args, **kwargs: warnings.append(args),
    )
    selector = _selector_with_plugin(tmp_path, monkeypatch, fake_plugin)

    # the host's own output survives a plugin failure
    assert selector._apply_token_replacer_plugin("{plugin_token}") == "{plugin_token}"
    assert len(warnings) == 1
    assert "no images for Aither" in warnings[0][2]
