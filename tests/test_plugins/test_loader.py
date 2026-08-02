from pathlib import Path
import sys
from threading import Lock

import pytest

from src.exceptions import PluginError, PluginExecutionError
from src.payloads.media_search import MediaSearchPayload
from src.plugins.api import (
    MetadataInputContext,
    MetadataTransformContext,
    MetadataTransformRequest,
    PluginDefinition,
    TokenReplaceRequest,
)
from src.plugins.loader import PluginLoader
from src.plugins.manager import PluginManager


def _metadata_context(payload: MediaSearchPayload) -> MetadataTransformContext:
    return MetadataTransformContext(
        media_input=MetadataInputContext(
            input_path=None,
            media_type=None,
            working_dir=None,
            files=(),
        ),
        media_search=payload,
    )


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


def test_plugin_directory_collision_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))

    report = PluginLoader(PluginManager(), plugin_dir=plugin_dir).load_plugins()

    assert report.loaded == ()
    assert len(report.failures) == 1
    assert "plugins" in report.failures[0].source


def test_plugin_system_exit_is_reported_and_does_not_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = tmp_path / "plugins"
    _write_plugin(
        plugin_dir,
        "exiting",
        "test.exiting",
        "nfoforge_test_exiting",
        "raise SystemExit('plugin stopped startup')\n",
    )
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))

    report = PluginLoader(PluginManager(), plugin_dir=plugin_dir).load_plugins()

    assert report.loaded == ()
    assert len(report.failures) == 1
    assert "plugin stopped startup" in report.failures[0].reason


def test_local_plugin_import_does_not_expose_its_root_on_sys_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = tmp_path / "plugins"
    module_name = "nfoforge_test_scoped_import"
    _write_plugin(
        plugin_dir,
        "scoped",
        "test.scoped",
        module_name,
        "import secrets\n"
        "from src.plugins.api import PluginDefinition\n"
        "def secrets_source(): return secrets.__file__ or ''\n"
        "plugin = PluginDefinition(display_name='Scoped', version='1.0.0', "
        "jinja2_functions={'secrets_source': secrets_source})\n",
    )
    plugin_root = plugin_dir / "scoped"
    (plugin_root / "secrets.py").write_text(
        "raise AssertionError('plugin root poisoned stdlib import')\n",
        encoding="utf-8",
    )
    monkeypatch.delitem(sys.modules, "secrets", raising=False)
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))
    manager = PluginManager()

    report = PluginLoader(manager, plugin_dir=plugin_dir).load_plugins()

    assert report.failures == ()
    secrets_source = manager.jinja2_functions(enabled=True)["secrets_source"]()
    assert Path(secrets_source).resolve() != (plugin_root / "secrets.py").resolve()


def test_local_plugin_package_can_use_relative_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = tmp_path / "plugins"
    module_name = "nfoforge_test_relative_import"
    _write_plugin(
        plugin_dir,
        "relative",
        "test.relative",
        module_name,
        "from src.plugins.api import PluginDefinition\n"
        "from .helper import plugin_value\n"
        "plugin = PluginDefinition(display_name='Relative', version='1.0.0', "
        "jinja2_functions={'plugin_value': plugin_value})\n",
    )
    package = plugin_dir / "relative" / module_name
    (package / "helper.py").write_text(
        "def plugin_value(): return 'relative import works'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))
    manager = PluginManager()

    report = PluginLoader(manager, plugin_dir=plugin_dir).load_plugins()

    assert report.failures == ()
    assert (
        manager.jinja2_functions(enabled=True)["plugin_value"]()
        == "relative import works"
    )


def test_local_manifest_rejects_module_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_root = tmp_path / "plugins" / "invalid"
    plugin_root.mkdir(parents=True)
    (plugin_root / "nfoforge-plugin.toml").write_text(
        'schema_version = 1\nid = "test.invalid"\nmodule = "../outside"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))

    report = PluginLoader(
        PluginManager(), plugin_dir=tmp_path / "plugins"
    ).load_plugins()

    assert report.loaded == ()
    assert len(report.failures) == 1
    assert "top-level Python module" in report.failures[0].reason


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


def test_manager_rejects_plugins_using_an_older_api_version() -> None:
    manager = PluginManager()

    with pytest.raises(PluginError, match="Unsupported plugin API version 1"):
        manager.register(
            "legacy",
            PluginDefinition(
                display_name="Legacy",
                version="1.0.0",
                api_version=1,
                jinja2_functions={"legacy_value": lambda: "legacy"},
            ),
            "test",
        )


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


def test_manager_rejects_case_insensitive_flat_filter_collision() -> None:
    manager = PluginManager()

    with pytest.raises(PluginError, match="duplicates flat filter"):
        manager.register(
            "one",
            PluginDefinition(
                display_name="One",
                version="1.0.0",
                flat_filters={"Upper": lambda value: value},  # type: ignore[reportArgumentType]
            ),
            "test",
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
        context=_metadata_context(payload),
        payload=payload,
        timeout=1,
    )

    with pytest.raises(PluginExecutionError, match="provider unavailable"):
        manager.transform_metadata("metadata.fail", request)

    assert payload.title == "TMDb title"


def test_metadata_transform_context_uses_the_isolated_payload() -> None:
    def transform(request: MetadataTransformRequest) -> MediaSearchPayload:
        assert request.context.media_search is request.payload
        request.context.media_search.title = "Context mutation"
        return request.context.media_search

    manager = PluginManager()
    manager.register(
        "metadata.context",
        PluginDefinition(
            display_name="Context",
            version="1.0.0",
            metadata_transformer=transform,
        ),
        "test",
    )
    payload = MediaSearchPayload(title="TMDb title")

    result = manager.transform_metadata(
        "metadata.context",
        MetadataTransformRequest(
            config=None,  # type: ignore[arg-type]
            context=_metadata_context(payload),
            payload=payload,
            timeout=1,
        ),
    )

    assert result.title == "Context mutation"
    assert payload.title == "TMDb title"


def test_metadata_transform_rejects_uncopyable_plugin_data() -> None:
    def transform(request: MetadataTransformRequest) -> MediaSearchPayload:
        request.payload.title = "Plugin title"
        request.payload.plugin_data["client_lock"] = Lock()
        return request.payload

    manager = PluginManager()
    manager.register(
        "metadata.uncopyable",
        PluginDefinition(
            display_name="Uncopyable",
            version="1.0.0",
            metadata_transformer=transform,
        ),
        "test",
    )
    payload = MediaSearchPayload(title="TMDb title")

    with pytest.raises(PluginExecutionError, match="cannot pickle"):
        manager.transform_metadata(
            "metadata.uncopyable",
            MetadataTransformRequest(
                config=None,  # type: ignore[arg-type]
                context=_metadata_context(payload),
                payload=payload,
                timeout=1,
            ),
        )

    assert payload.title == "TMDb title"
    assert payload.plugin_data == {}


def test_metadata_transform_rejects_invalid_raw_metadata_shape() -> None:
    def transform(request: MetadataTransformRequest) -> MediaSearchPayload:
        request.payload.tmdb_data = "raw metadata"  # type: ignore[assignment]
        return request.payload

    manager = PluginManager()
    manager.register(
        "metadata.invalid",
        PluginDefinition(
            display_name="Invalid",
            version="1.0.0",
            metadata_transformer=transform,
        ),
        "test",
    )
    payload = MediaSearchPayload(title="TMDb title")

    with pytest.raises(PluginExecutionError, match="tmdb_data"):
        manager.transform_metadata(
            "metadata.invalid",
            MetadataTransformRequest(
                config=None,  # type: ignore[arg-type]
                context=_metadata_context(payload),
                payload=payload,
                timeout=1,
            ),
        )

    assert payload.title == "TMDb title"
    assert payload.tmdb_data is None


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
