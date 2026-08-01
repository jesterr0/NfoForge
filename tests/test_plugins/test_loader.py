from pathlib import Path

import pytest

from src.exceptions import PluginError, PluginExecutionError
from src.payloads.media_search import MediaSearchPayload
from src.plugins.api import (
    MetadataTransformRequest,
    PluginDefinition,
    TokenReplaceRequest,
)
from src.plugins.loader import PluginLoader
from src.plugins.manager import PluginManager


def _write_plugin(
    root: Path,
    directory: str,
    plugin_id: str,
    module: str,
    definition: str,
) -> None:
    plugin_root = root / directory
    package = plugin_root / module
    package.mkdir(parents=True)
    (plugin_root / "nfoforge-plugin.toml").write_text(
        f'schema_version = 1\nid = "{plugin_id}"\nmodule = "{module}"\n',
        encoding="utf-8",
    )
    (package / "__init__.py").write_text(definition, encoding="utf-8")


def test_load_plugins_skips_failures_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = tmp_path / "plugins"
    _write_plugin(
        plugin_dir,
        "good",
        "test.good",
        "nfoforge_test_good",
        "from src.plugins.api import PluginDefinition\n"
        "def sample(value): return value\n"
        "plugin = PluginDefinition(display_name='Good', version='1.0.0', "
        "jinja2_filters={'sample': sample})\n",
    )
    _write_plugin(
        plugin_dir,
        "bad",
        "test.bad",
        "nfoforge_test_bad",
        "raise ImportError('missing dependency')\n",
    )
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))
    manager = PluginManager()

    report = PluginLoader(manager, plugin_dir=plugin_dir).load_plugins()

    assert manager.plugin_ids == frozenset({"test.good"})
    assert [record.plugin_id for record in report.loaded] == ["test.good"]
    assert len(report.failures) == 1
    assert "missing dependency" in report.failures[0].reason
    assert len(manager.load_issues) == 1
    assert manager.load_issues[0].source.endswith("bad")
    assert "missing dependency" in manager.load_issues[0].reason


def test_directory_without_manifest_is_not_a_plugin_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ignored = tmp_path / "plugins" / "unrelated_directory"
    ignored.mkdir(parents=True)
    (ignored / "__init__.py").write_text("raise AssertionError", encoding="utf-8")
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))

    report = PluginLoader(
        PluginManager(), plugin_dir=tmp_path / "plugins"
    ).load_plugins()

    assert report.loaded == ()
    assert report.failures == ()


def test_installed_entry_point_uses_its_name_as_the_plugin_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    definition = PluginDefinition(
        display_name="Installed",
        version="2.0.0",
        jinja2_functions={"installed": lambda: "yes"},
    )

    class EntryPoint:
        name = "installed.example"
        value = "installed_plugin:plugin"

        @staticmethod
        def load() -> PluginDefinition:
            return definition

    monkeypatch.setattr(
        PluginLoader, "_entry_points", staticmethod(lambda: (EntryPoint(),))
    )
    manager = PluginManager()

    report = PluginLoader(manager, plugin_dir=tmp_path / "plugins").load_plugins()

    assert report.failures == ()
    assert manager.get("installed.example") is not None


def test_manager_rejects_duplicate_ids() -> None:
    manager = PluginManager()
    definition = PluginDefinition(
        display_name="Example",
        version="1.0.0",
        jinja2_filters={"one": lambda value: value},
    )
    manager.register("example", definition, "one")

    with pytest.raises(PluginError, match="Duplicate plugin id"):
        manager.register("example", definition, "two")


def test_manager_rejects_contribution_name_collisions() -> None:
    manager = PluginManager()
    manager.register(
        "one",
        PluginDefinition(
            display_name="One",
            version="1.0.0",
            flat_filters={"custom": lambda value: value},  # type: ignore[reportArgumentType]
        ),
        "one",
    )

    with pytest.raises(PluginError, match="duplicates flat filter"):
        manager.register(
            "two",
            PluginDefinition(
                display_name="Two",
                version="1.0.0",
                flat_filters={"custom": lambda value: value},  # type: ignore[reportArgumentType]
            ),
            "two",
        )


def test_manager_rejects_built_in_filter_name_collisions() -> None:
    manager = PluginManager()

    with pytest.raises(PluginError, match="duplicates Jinja2 filter"):
        manager.register(
            "one",
            PluginDefinition(
                display_name="One",
                version="1.0.0",
                jinja2_filters={"upper": lambda value: value},
            ),
            "one",
        )


def test_metadata_transform_is_atomic_on_failure() -> None:
    def fail(request: MetadataTransformRequest) -> MediaSearchPayload:
        request.payload.title = "partial mutation"
        raise RuntimeError("provider unavailable")

    manager = PluginManager()
    manager.register(
        "metadata.fail",
        PluginDefinition(
            display_name="Failure",
            version="1.0.0",
            metadata_transformer=fail,
        ),
        "test",
    )
    payload = MediaSearchPayload(title="TMDb title")
    request = MetadataTransformRequest(
        config=None,  # type: ignore[arg-type]
        context=None,  # type: ignore[arg-type]
        payload=payload,
        timeout=1,
    )

    with pytest.raises(PluginExecutionError, match="provider unavailable"):
        manager.transform_metadata("metadata.fail", request)

    assert payload.title == "TMDb title"


def test_token_replacer_uses_typed_request() -> None:
    def replace(request: TokenReplaceRequest) -> str:
        return request.text.replace("{custom}", "value")

    manager = PluginManager()
    manager.register(
        "token.example",
        PluginDefinition(
            display_name="Token",
            version="1.0.0",
            token_replacer=replace,
        ),
        "test",
    )
    request = TokenReplaceRequest(
        config=None,  # type: ignore[arg-type]
        context=None,  # type: ignore[arg-type]
        text="A {custom}",
        trackers=(),
    )

    assert manager.replace_tokens("token.example", request) == "A value"
