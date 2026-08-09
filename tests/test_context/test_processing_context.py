from types import SimpleNamespace
from typing import Any

from src.context.factory import create_processing_context
from src.context.processing_context import ProcessingContext
from src.packages.custom_types import RenameNormalization
from src.plugins.api import CustomEditionContribution, PluginDefinition
from src.plugins.manager import PluginManager


def _config_payload(**overrides) -> Any:
    template_values = {
        "trim_blocks": True,
        "lstrip_blocks": False,
        "newline_sequence": "\r\n",
        "keep_trailing_newline": True,
    }
    template_values.update(overrides)
    return SimpleNamespace(
        templates=SimpleNamespace(**template_values),
        general=SimpleNamespace(enable_plugins=True),
    )


def test_processing_context_binds_payload_globals() -> None:
    context = ProcessingContext()

    globals_ = context.jinja_engine.environment.globals

    assert globals_["nf_shared_data"] is context.shared_data
    assert globals_["nf_media_search_payload"] is context.media_search
    assert globals_["nf_media_input_payload"] is context.media_input


def test_media_input_payloads_own_isolated_analysis_caches() -> None:
    first = ProcessingContext()
    second = ProcessingContext()

    assert first.media_input.analysis_cache is not second.media_input.analysis_cache


def test_factory_creates_isolated_engines() -> None:
    first = create_processing_context(_config_payload(), PluginManager())
    second = create_processing_context(_config_payload(), PluginManager())

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

    def flat_plugin_filter(value: str, *_args: Any) -> str:
        return value.upper()

    manager = PluginManager()
    manager.register(
        "example",
        PluginDefinition(
            display_name="Example",
            version="1.0.0",
            jinja2_filters={"plugin_filter": plugin_filter},
            jinja2_functions={"plugin_function": plugin_function},
            flat_filters={"flat_plugin_filter": flat_plugin_filter},
            custom_editions=(
                CustomEditionContribution(
                    entry=RenameNormalization("Fan Edit", (r"fan[\s\.\-_]*edit",)),
                    is_cut=True,
                ),
            ),
        ),
        "test",
    )

    context = create_processing_context(
        _config_payload(),
        manager,
    )
    environment = context.jinja_engine.environment

    assert environment.trim_blocks is True
    assert environment.lstrip_blocks is False
    assert environment.newline_sequence == "\r\n"
    assert environment.keep_trailing_newline is True
    assert environment.filters["plugin_filter"] is plugin_filter
    assert environment.globals["plugin_function"] is plugin_function
    assert context.flat_filters["flat_plugin_filter"] is flat_plugin_filter
    assert [item.normalized for item in context.custom_edition_info] == ["Fan Edit"]
    assert context.custom_cut_names == frozenset({"Fan Edit"})


def test_factory_does_not_apply_contributions_when_plugins_are_disabled() -> None:
    manager = PluginManager()
    manager.register(
        "example",
        PluginDefinition(
            display_name="Example",
            version="1.0.0",
            jinja2_filters={"external_filter": lambda value: value},
            flat_filters={"external_flat_filter": lambda value: value},  # type: ignore[reportArgumentType]
            custom_editions=(
                CustomEditionContribution(
                    entry=RenameNormalization("Fan Edit", (r"fan[\s\.\-_]*edit",)),
                ),
            ),
        ),
        "test",
    )
    config = _config_payload()
    config.general.enable_plugins = False

    context = create_processing_context(config, manager)

    assert "external_filter" not in context.jinja_engine.environment.filters
    assert context.flat_filters == {}
    assert context.custom_edition_info == ()
    assert context.custom_cut_names == frozenset()
