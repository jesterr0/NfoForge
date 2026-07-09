from types import SimpleNamespace
from typing import Any

import pytest

from src.context.factory import create_processing_context, normalize_newline_sequence
from src.context.processing_context import ProcessingContext


def _config_payload(**overrides) -> Any:
    template_values = {
        "trim_blocks": True,
        "lstrip_blocks": False,
        "newline_sequence": "\\r\\n",
        "keep_trailing_newline": True,
    }
    template_values.update(overrides)
    return SimpleNamespace(templates=SimpleNamespace(**template_values))


def test_processing_context_binds_payload_globals() -> None:
    context = ProcessingContext()

    globals_ = context.jinja_engine.environment.globals

    assert globals_["nf_shared_data"] is context.shared_data
    assert globals_["nf_media_search_payload"] is context.media_search
    assert globals_["nf_media_input_payload"] is context.media_input


def test_factory_creates_isolated_engines() -> None:
    first = create_processing_context(_config_payload(), {})
    second = create_processing_context(_config_payload(), {})

    first.jinja_engine.add_global("runtime_value", "first", True)

    assert first.jinja_engine is not second.jinja_engine
    assert "runtime_value" not in second.jinja_engine.environment.globals
    assert first.jinja_engine.environment.globals["nf_shared_data"] is first.shared_data
    assert (
        second.jinja_engine.environment.globals["nf_shared_data"] is second.shared_data
    )


def test_factory_applies_settings_and_plugins() -> None:
    def plugin_filter(value: str) -> str:
        return value.upper()

    def plugin_function() -> str:
        return "plugin"

    plugin: Any = SimpleNamespace(
        jinja2_filters={"plugin_filter": plugin_filter},
        jinja2_functions={"plugin_function": plugin_function},
    )

    context = create_processing_context(
        _config_payload(),
        {"example": plugin},
    )
    environment = context.jinja_engine.environment

    assert environment.trim_blocks is True
    assert environment.lstrip_blocks is False
    assert environment.newline_sequence == "\r\n"
    assert environment.keep_trailing_newline is True
    assert environment.filters["plugin_filter"] is plugin_filter
    assert environment.globals["plugin_function"] is plugin_function


@pytest.mark.parametrize(
    ("stored_value", "expected"),
    (
        ("\n", "\n"),
        ("\r", "\r"),
        ("\r\n", "\r\n"),
        ("\\n", "\n"),
        ("\\r", "\r"),
        ("\\r\\n", "\r\n"),
        ("\\\\n", "\n"),
        ("\\\\r", "\r"),
        ("\\\\r\\\\n", "\r\n"),
        ("invalid", "\n"),
    ),
)
def test_normalize_newline_sequence(stored_value: str, expected: str) -> None:
    assert normalize_newline_sequence(stored_value) == expected


def test_factory_falls_back_to_lf_for_invalid_newline_sequence() -> None:
    context = create_processing_context(
        _config_payload(newline_sequence="invalid"),
        {},
    )

    assert context.jinja_engine.environment.newline_sequence == "\n"
