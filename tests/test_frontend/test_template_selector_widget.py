import re
from pathlib import Path

import pytest

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.context.processing_context import ProcessingContext
from src.frontend.custom_widgets.basic_code_editor import HighlightKeywords
from src.frontend.custom_widgets.template_selector import (
    TemplateSelector,
    saved_status_message,
)


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
        main_window=None,
        parent=None,
    )


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

    selector.set_syntax_highlights(patterns)

    assert selector.text_edit.highlighter.patterns_colors == patterns


def test_set_syntax_highlights_replaces_rather_than_accumulates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selector = _make_selector(tmp_path, monkeypatch)

    selector.set_syntax_highlights(_static_patterns())
    selector.set_syntax_highlights(_static_patterns())

    assert len(selector.text_edit.highlighter.patterns_colors) == 2


def test_set_syntax_highlights_replaces_rather_than_accumulates_the_warning_pattern(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The invariant above is meaningless while `unknown_tokens` is empty, since
    # there is no warning pattern either way. With one present and refreshed,
    # reapplying the static patterns must rebuild -- not lose or duplicate --
    # the warning pattern.
    selector = _make_selector(tmp_path, monkeypatch)
    selector.set_syntax_highlights(_static_patterns())
    selector.text_edit.setPlainText("{{ mi_video_codec }}")
    selector._refresh_unknown_tokens()

    selector.set_syntax_highlights(_static_patterns())

    assert (
        len(selector.text_edit.highlighter.patterns_colors)
        == len(_static_patterns()) + 1
    )


def test_unknown_token_pattern_is_appended_after_the_static_patterns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Order matters: the highlighter applies patterns in list order and later
    # `setFormat` calls overwrite earlier ones for the same span, so the
    # warning colour must be applied after the variable colour to win.
    selector = _make_selector(tmp_path, monkeypatch)
    selector.set_syntax_highlights(_static_patterns())
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
    selector.set_syntax_highlights(_static_patterns())
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
    selector.set_syntax_highlights(_static_patterns())
    selector.text_edit.setPlainText("{% if %}")

    selector._refresh_unknown_tokens()

    assert selector.unknown_tokens == set()
    assert len(selector.text_edit.highlighter.patterns_colors) == 2


def test_blank_warning_colour_falls_back_to_the_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selector = _make_selector(tmp_path, monkeypatch)
    selector.config.settings.templates.warning_syntax_color = ""
    selector.text_edit.setPlainText("{{ mi_video_codec }}")

    selector._refresh_unknown_tokens()

    applied = selector.text_edit.highlighter.patterns_colors
    assert applied[-1].color.lower() == "#e1401d"


def test_warning_colour_override_wins_over_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The settings picker passes its own value so the editor can live-preview
    # a change before it is saved; config (unchanged here) must not win.
    selector = _make_selector(tmp_path, monkeypatch)
    assert selector.config.settings.templates.warning_syntax_color.lower() != "#00ff00"
    selector.set_syntax_highlights(_static_patterns(), "#00ff00")
    selector.text_edit.setPlainText("{{ mi_video_codec }}")

    selector._refresh_unknown_tokens()

    applied = selector.text_edit.highlighter.patterns_colors
    assert applied[-1].color.lower() == "#00ff00"


def test_status_message_is_unchanged_when_everything_resolves() -> None:
    assert saved_status_message(0) == "Saved template"


def test_status_message_is_singular_for_one_unknown_token() -> None:
    assert saved_status_message(1) == "Saved template - 1 unrecognised token"


def test_status_message_is_plural_for_several_unknown_tokens() -> None:
    assert saved_status_message(3) == "Saved template - 3 unrecognised tokens"
