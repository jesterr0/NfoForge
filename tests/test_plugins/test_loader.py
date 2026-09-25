from pathlib import Path
import sys
from threading import Lock

import pytest

from nfoforge.config.paths import DATA_DIR_ENV_VAR, DEV_PLUGINS_ENV_VAR
from nfoforge.exceptions import PluginError, PluginExecutionError
from nfoforge.payloads.media_search import MediaSearchPayload
from nfoforge.plugins.api import (
    MetadataInputContext,
    MetadataTransformContext,
    MetadataTransformRequest,
    PluginDefinition,
    TokenReplaceRequest,
)
from nfoforge.plugins.loader import PluginLoader
from nfoforge.plugins.manager import PluginManager


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
        "from nfoforge.plugins.api import PluginDefinition\n"
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
        "from nfoforge.plugins.api import PluginDefinition\n"
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
        "from nfoforge.plugins.api import PluginDefinition\n"
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


def _write_manifest(tmp_path: Path, manifest_text: str) -> Path:
    """Write a single local plugin's manifest with arbitrary (possibly
    invalid) text and return the plugin directory to pass to `PluginLoader`.

    No package/module is created alongside it: every case below fails
    manifest validation before the loader would ever try to import one.
    """
    plugin_dir = tmp_path / "plugins"
    plugin_root = plugin_dir / "candidate"
    plugin_root.mkdir(parents=True)
    (plugin_root / "nfoforge-plugin.toml").write_text(manifest_text, encoding="utf-8")
    return plugin_dir


def test_manifest_with_unknown_schema_version_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = _write_manifest(
        tmp_path, 'schema_version = 99\nid = "test.future"\nmodule = "plugin"\n'
    )
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))

    report = PluginLoader(PluginManager(), plugin_dir=plugin_dir).load_plugins()

    assert report.loaded == ()
    assert len(report.failures) == 1
    assert "Unsupported manifest schema version 99" in report.failures[0].reason


def test_manifest_missing_id_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = _write_manifest(tmp_path, 'schema_version = 1\nmodule = "plugin"\n')
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))

    report = PluginLoader(PluginManager(), plugin_dir=plugin_dir).load_plugins()

    assert report.loaded == ()
    assert len(report.failures) == 1
    assert "non-empty string id" in report.failures[0].reason


def test_malformed_manifest_toml_is_reported_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A broken third-party manifest must never prevent startup -- the parse
    # error is collected as a load failure, not left to propagate.
    plugin_dir = _write_manifest(tmp_path, 'schema_version = "unterminated\n')
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))

    report = PluginLoader(PluginManager(), plugin_dir=plugin_dir).load_plugins()

    assert report.loaded == ()
    assert len(report.failures) == 1
    assert "Invalid nfoforge-plugin.toml" in report.failures[0].reason


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


def test_a_local_plugin_wins_an_id_collision_with_an_entry_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = tmp_path / "plugins"
    _write_plugin(
        plugin_dir,
        "local",
        "collide.example",
        "nfoforge_test_collision_local",
        "from nfoforge.plugins.api import PluginDefinition\n"
        "def collision_value(): return 'local'\n"
        "plugin = PluginDefinition(display_name='Local', version='1.0.0', "
        "jinja2_functions={'collision_value': collision_value})\n",
    )

    entry_point_definition = PluginDefinition(
        display_name="Installed",
        version="1.0.0",
        jinja2_functions={"collision_value": lambda: "installed"},
    )

    class EntryPoint:
        name = "collide.example"
        value = "installed_plugin:plugin"

        @staticmethod
        def load() -> PluginDefinition:
            return entry_point_definition

    monkeypatch.setattr(
        PluginLoader, "_entry_points", staticmethod(lambda: (EntryPoint(),))
    )
    manager = PluginManager()

    report = PluginLoader(manager, plugin_dir=plugin_dir).load_plugins()

    assert [record.plugin_id for record in report.loaded] == ["collide.example"]
    assert manager.jinja2_functions(enabled=True)["collision_value"]() == "local"
    assert len(report.failures) == 1
    assert "Duplicate plugin id" in report.failures[0].reason


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


def test_shipped_examples_load_alongside_the_users_own_plugins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two roots are scanned: the user's directory and the release's own.

    The examples a release ships used to sit in the same folder the user
    installs into, which meant they could not be updated without touching what
    the user put there, and a migration could not tell them apart.
    """
    plugin_dir = tmp_path / "plugins"
    shipped_dir = tmp_path / "assets" / "plugin_examples"
    _write_plugin(
        plugin_dir,
        "mine",
        "test.mine",
        "nfoforge_test_mine",
        "from nfoforge.plugins.api import PluginDefinition\n"
        "def sample(value): return value\n"
        "plugin = PluginDefinition(display_name='Mine', version='1.0.0', "
        "jinja2_filters={'sample': sample})\n",
    )
    _write_plugin(
        shipped_dir,
        "example",
        "test.example",
        "nfoforge_test_example",
        "from nfoforge.plugins.api import PluginDefinition\n"
        "def sample(value): return value\n"
        "plugin = PluginDefinition(display_name='Example', version='1.0.0', "
        "jinja2_filters={'example_sample': sample})\n",
    )
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))
    manager = PluginManager()

    PluginLoader(manager, plugin_dir=plugin_dir, shipped_dir=shipped_dir).load_plugins()

    assert manager.plugin_ids == frozenset({"test.mine", "test.example"})


def test_a_users_plugin_wins_a_collision_with_a_shipped_example(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The user's own copy takes precedence, matching existing precedence rules.

    Local plugins already beat installed entry points for the same reason: what
    the user put there must not be silently shadowed by something that arrived
    with a release.
    """
    plugin_dir = tmp_path / "plugins"
    shipped_dir = tmp_path / "assets" / "plugin_examples"
    _write_plugin(
        plugin_dir,
        "theirs",
        "test.shared",
        "nfoforge_test_theirs",
        "from nfoforge.plugins.api import PluginDefinition\n"
        "def sample(value): return value\n"
        "plugin = PluginDefinition(display_name='Theirs', version='9.9.9', "
        "jinja2_filters={'sample': sample})\n",
    )
    _write_plugin(
        shipped_dir,
        "ours",
        "test.shared",
        "nfoforge_test_ours",
        "from nfoforge.plugins.api import PluginDefinition\n"
        "def sample(value): return value\n"
        "plugin = PluginDefinition(display_name='Ours', version='1.0.0', "
        "jinja2_filters={'sample': sample})\n",
    )
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))
    manager = PluginManager()

    report = PluginLoader(
        manager, plugin_dir=plugin_dir, shipped_dir=shipped_dir
    ).load_plugins()

    assert [record.definition.display_name for record in report.loaded] == ["Theirs"]
    assert len(report.failures) == 1


def test_a_missing_shipped_directory_is_not_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shipped root lives inside the release, which is read-only territory.

    Only the user's own directory is created on demand; writing into the
    asset tree is the thing this whole refactor exists to stop.
    """
    plugin_dir = tmp_path / "plugins"
    shipped_dir = tmp_path / "assets" / "plugin_examples"
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))

    report = PluginLoader(
        PluginManager(), plugin_dir=plugin_dir, shipped_dir=shipped_dir
    ).load_plugins()

    assert report.failures == ()
    assert plugin_dir.is_dir()
    assert not shipped_dir.exists()


def test_the_plugin_directory_defaults_to_the_data_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not beside the executable, which a release replaces.

    Defaulting there would have a migrated installation load nothing: the
    plugins were copied into the data directory and the loader would be looking
    in the release folder it was extracted from.
    """
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path / "data"))

    loader = PluginLoader(PluginManager())

    assert loader.plugin_dir == tmp_path / "data" / "plugins"


def _where_plugin(where: str, name: str = "where") -> str:
    """A definition that reports which copy of itself was loaded.

    The exported name is a parameter because the manager refuses two plugins
    contributing the same Jinja function name, so a test that loads two of
    these at once has to keep them apart.
    """
    return (
        "from nfoforge.plugins.api import PluginDefinition\n"
        f"def {name}(): return {where!r}\n"
        "plugin = PluginDefinition(display_name='Sample', version='1.0.0', "
        f"jinja2_functions={{{name!r}: {name}}})\n"
    )


def test_a_development_directory_loads_every_plugin_in_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A folder of plugins, the same shape as the one it stands in for.

    Not a list of individual plugins: a developer with two checkouts should not
    have to name them one at a time, and the arrangement they are testing is
    the one a real installation has.
    """
    checkouts = tmp_path / "checkouts"
    _write_plugin(checkouts, "one", "test.one", "nfoforge_test_one", _where_plugin("a"))
    _write_plugin(
        checkouts, "two", "test.two", "nfoforge_test_two", _where_plugin("b", "there")
    )
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))

    report = PluginLoader(
        PluginManager(), plugin_dir=tmp_path / "plugins", dev_dirs=(checkouts,)
    ).load_plugins()

    assert report.failures == ()
    assert sorted(record.plugin_id for record in report.loaded) == [
        "test.one",
        "test.two",
    ]


def test_the_installed_plugins_folder_is_not_read_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replaces rather than adds, which is what makes development ordinary.

    Loading both would be an arrangement that exists on no user's machine:
    collisions that happen only here, and a plugin that can be picked up from a
    copy the developer has forgotten is there.
    """
    checkouts = tmp_path / "checkouts"
    plugin_dir = tmp_path / "plugins"
    _write_plugin(
        checkouts, "mine", "test.dev", "nfoforge_test_dev", _where_plugin("checkout")
    )
    _write_plugin(
        plugin_dir,
        "installed",
        "test.installed",
        "nfoforge_test_installed",
        _where_plugin("installed", "elsewhere"),
    )
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))
    manager = PluginManager()

    report = PluginLoader(
        manager, plugin_dir=plugin_dir, dev_dirs=(checkouts,)
    ).load_plugins()

    assert report.failures == ()
    assert [record.plugin_id for record in report.loaded] == ["test.dev"]
    assert manager.jinja2_functions(enabled=True)["where"]() == "checkout"


def test_an_installed_copy_of_the_same_plugin_is_simply_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The copy installed from this very checkout is the normal case.

    Because the real folder is not read, there is no collision to resolve and
    nothing to report -- no duplicate-ID failure, and no `sys.modules` rejection
    of the same module name from a different location, either of which would put
    a permanent red row in the status table for a setup working as intended.
    """
    checkouts = tmp_path / "checkouts"
    plugin_dir = tmp_path / "plugins"
    _write_plugin(
        checkouts, "mine", "test.both", "nfoforge_test_both", _where_plugin("checkout")
    )
    _write_plugin(
        plugin_dir,
        "mine",
        "test.both",
        "nfoforge_test_both",
        _where_plugin("installed"),
    )
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))
    manager = PluginManager()

    report = PluginLoader(
        manager, plugin_dir=plugin_dir, dev_dirs=(checkouts,)
    ).load_plugins()

    assert report.failures == ()
    assert [record.source for record in report.loaded] == [str(checkouts / "mine")]
    assert manager.jinja2_functions(enabled=True)["where"]() == "checkout"


def test_shipped_examples_still_load_beside_a_development_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the user's own folder is stood in for, not the release's.

    A development run should be the same arrangement as a real one, and a real
    one has the examples in it.
    """
    checkouts = tmp_path / "checkouts"
    shipped_dir = tmp_path / "assets" / "plugin_examples"
    _write_plugin(
        checkouts, "mine", "test.dev", "nfoforge_test_devx", _where_plugin("checkout")
    )
    _write_plugin(
        shipped_dir,
        "example",
        "test.example",
        "nfoforge_test_examplex",
        _where_plugin("shipped", "shipped"),
    )
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))

    report = PluginLoader(
        PluginManager(),
        plugin_dir=tmp_path / "plugins",
        shipped_dir=shipped_dir,
        dev_dirs=(checkouts,),
    ).load_plugins()

    assert report.failures == ()
    assert sorted(record.plugin_id for record in report.loaded) == [
        "test.dev",
        "test.example",
    ]


def test_several_development_directories_are_read_in_the_order_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checkouts are not always kept in one place.

    Two folders holding the same plugin has to be resolved somehow, and the only
    non-arbitrary answer is the one the developer wrote first -- the same
    first-come-first-served rule everything else here follows.

    The second copy is rejected for sharing the first's module name rather than
    its id, because two checkouts of one plugin share both and the module is
    checked first. Which guard catches it is not the point and is not asserted;
    that the second copy loses and is reported is.
    """
    first, second = tmp_path / "first", tmp_path / "second"
    _write_plugin(
        first, "mine", "test.same", "nfoforge_test_same", _where_plugin("one")
    )
    _write_plugin(
        second, "mine", "test.same", "nfoforge_test_same", _where_plugin("two")
    )
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))
    manager = PluginManager()

    report = PluginLoader(
        manager,
        plugin_dir=tmp_path / "plugins",
        dev_dirs=(first, second),
    ).load_plugins()

    assert [record.source for record in report.loaded] == [str(first / "mine")]
    assert manager.jinja2_functions(enabled=True)["where"]() == "one"
    assert len(report.failures) == 1
    assert report.failures[0].source == str(second / "mine")


def test_a_development_directory_that_does_not_exist_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A path someone typed, which has taken the real folder out of the run.

    An empty or missing plugins folder is normal for a real installation and is
    passed over in silence. Here the same silence would leave a developer with
    no plugins at all and nothing anywhere saying why.
    """
    missing = tmp_path / "not-here"
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))

    report = PluginLoader(
        PluginManager(), plugin_dir=tmp_path / "plugins", dev_dirs=(missing,)
    ).load_plugins()

    assert report.loaded == ()
    assert len(report.failures) == 1
    assert report.failures[0].source == str(missing)
    assert "not a directory" in report.failures[0].reason


def test_naming_a_plugin_instead_of_a_folder_of_plugins_is_recognised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The easy mistake, because the plugin is the thing being worked on.

    It is recognisable rather than merely wrong: the directory holds the
    manifest that should have been one level further down, so the message can
    say what to do instead of only that nothing loaded.
    """
    checkouts = tmp_path / "checkouts"
    _write_plugin(
        checkouts, "mine", "test.dev", "nfoforge_test_named", _where_plugin("here")
    )
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))

    report = PluginLoader(
        PluginManager(),
        plugin_dir=tmp_path / "plugins",
        dev_dirs=(checkouts / "mine",),
    ).load_plugins()

    assert report.loaded == ()
    assert len(report.failures) == 1
    assert "folder that contains it instead" in report.failures[0].reason


def test_a_development_directory_holding_no_plugins_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing loading is the symptom; this is the only place it gets explained."""
    empty = tmp_path / "empty"
    (empty / "notes").mkdir(parents=True)
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))

    report = PluginLoader(
        PluginManager(), plugin_dir=tmp_path / "plugins", dev_dirs=(empty,)
    ).load_plugins()

    assert report.loaded == ()
    assert len(report.failures) == 1
    assert "holding no plugins" in report.failures[0].reason


def test_the_installed_plugins_folder_is_not_created_while_standing_in_for_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A folder is not created in order to be ignored."""
    checkouts = tmp_path / "checkouts"
    plugin_dir = tmp_path / "plugins"
    _write_plugin(
        checkouts, "mine", "test.dev", "nfoforge_test_nomk", _where_plugin("a")
    )
    monkeypatch.setattr(PluginLoader, "_entry_points", staticmethod(lambda: ()))

    PluginLoader(
        PluginManager(), plugin_dir=plugin_dir, dev_dirs=(checkouts,)
    ).load_plugins()

    assert not plugin_dir.exists()


def test_development_directories_default_to_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEV_PLUGINS_ENV_VAR, str(tmp_path / "checkouts"))

    loader = PluginLoader(PluginManager())

    assert loader.dev_dirs == (tmp_path / "checkouts",)


def test_an_empty_development_directory_sequence_is_not_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Passing none means none, which is not the same as not passing any.

    Everything that builds a loader for one specific pair of directories needs
    to be able to say "these and nothing else" while a developer's variable is
    set in the environment around it.
    """
    monkeypatch.setenv(DEV_PLUGINS_ENV_VAR, str(tmp_path / "checkouts"))

    loader = PluginLoader(PluginManager(), dev_dirs=())

    assert loader.dev_dirs == ()
