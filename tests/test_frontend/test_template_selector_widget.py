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


def _make_selector_with_real_templates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> TemplateSelector:
    """A selector backed by real files, for exercising cross-instance resync.

    `TemplateSelectorBackEnd` uses `__slots__`, so its `load_templates`
    can't be monkeypatched per-instance -- real files on a patched
    `RUNTIME_DIR` stand in for "another open editor changed the directory".
    """
    monkeypatch.setattr(
        "src.backend.template_selector.RUNTIME_DIR", tmp_path / "runtime"
    )
    return _make_selector(tmp_path, monkeypatch)


def test_templates_changed_elsewhere_preserves_selection_and_unsaved_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a template created/deleted through another open TemplateSelector (e.g.
    # the wizard's "Configure NFO Templates" dialog vs. Settings > Templates)
    # must not disturb this one's active selection or in-progress edits
    selector = _make_selector_with_real_templates(tmp_path, monkeypatch)
    template_dir = selector.backend.template_dir
    (template_dir / "a.txt").write_text("A", encoding="utf-8")
    (template_dir / "b.txt").write_text("B", encoding="utf-8")
    selector.load_templates()
    selector.template_combo.setCurrentText("b")
    selector.text_edit.setPlainText("unsaved edit")

    # another window creates "c" on disk
    (template_dir / "c.txt").write_text("C", encoding="utf-8")

    selector._templates_changed_elsewhere()

    assert selector.template_combo.currentText() == "b"
    assert selector.text_edit.toPlainText() == "unsaved edit"
    assert {
        selector.template_combo.itemText(i)
        for i in range(selector.template_combo.count())
    } == {"a", "b", "c"}


def test_templates_changed_elsewhere_drops_selection_when_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # this used to leave a dead entry selected forever, and the next
    # save/read against it raised FileNotFoundError
    selector = _make_selector_with_real_templates(tmp_path, monkeypatch)
    template_dir = selector.backend.template_dir
    (template_dir / "a.txt").write_text("A", encoding="utf-8")
    b_path = template_dir / "b.txt"
    b_path.write_text("B", encoding="utf-8")
    selector.load_templates()
    selector.template_combo.setCurrentText("b")
    selector.text_edit.setPlainText("unsaved edit")

    # another window deletes "b"
    b_path.unlink()

    selector._templates_changed_elsewhere()

    assert selector.template_combo.count() == 1
    assert selector.template_combo.currentText() == "a"
    # falls back to whatever is now first on disk rather than the dead entry
    assert selector.text_edit.toPlainText() == "A"


def test_save_template_warns_and_reloads_when_selection_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the combo can show a template already removed from the backend cache
    # (deleted through another open editor); saving it must not KeyError
    selector = _make_selector(tmp_path, monkeypatch)
    selector.template_combo.addItem("ghost")
    selector.template_combo.setCurrentText("ghost")

    warnings = []
    monkeypatch.setattr(
        "src.frontend.custom_widgets.template_selector.QMessageBox.warning",
        lambda *args, **kwargs: warnings.append(args),
    )
    reload_calls = []
    monkeypatch.setattr(selector, "load_templates", lambda: reload_calls.append(True))

    selector.save_template()

    assert len(warnings) == 1
    assert reload_calls == [True]


def test_delete_template_reloads_when_selection_already_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the confirm click can land after the same template was already deleted
    # elsewhere; it must reload instead of KeyError
    selector = _make_selector(tmp_path, monkeypatch)
    selector.template_combo.addItem("ghost")
    selector.template_combo.setCurrentText("ghost")
    selector._del_timer.start()  # simulate the first click having armed "Confirm?"

    reload_calls = []
    monkeypatch.setattr(selector, "load_templates", lambda: reload_calls.append(True))

    selector.delete_template()

    assert reload_calls == [True]


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
    selector.config.settings.plugins.token_replacer = "fake_plugin"  # noqa: S105 - plugin capability name used as test fixture data, not a credential
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
