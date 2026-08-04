from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
import re
import threading
from typing import TYPE_CHECKING, Any

from jinja2 import Environment

from src.exceptions import PluginError, PluginExecutionError
from src.plugins.api import (
    PLUGIN_API_VERSION,
    FlatFilter,
    MetadataTransformer,
    MetadataTransformRequest,
    PluginDefinition,
    PluginRecord,
    PreUploadDecision,
    PreUploadRequest,
    TokenReplaceRequest,
)

if TYPE_CHECKING:
    from src.payloads.media_search import MediaSearchPayload


_PLUGIN_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class PluginLoadIssue:
    """A plugin discovery or loading failure retained for diagnostics."""

    source: str
    reason: str


@dataclass(slots=True)
class _TransformOutcome:
    """Mutable holder a transform worker writes and the caller reads after `join`.

    Not frozen: the worker thread populates exactly one of these fields after
    the main thread has already constructed and started reading from it.
    """

    value: MediaSearchPayload | None = None
    error: BaseException | None = None


class PluginManager:
    """Validate, register, query, and invoke external plugins."""

    def __init__(self) -> None:
        # lint reason: only used below to read the built-in filter/global
        # names so plugins can't shadow them; nothing is ever rendered
        # through this environment, so autoescape is irrelevant here
        jinja_environment = Environment()  # noqa: S701
        self._records: dict[str, PluginRecord] = {}
        self._jinja2_filters: dict[str, Any] = {}
        self._jinja2_functions: dict[str, Any] = {}
        self._flat_filters: dict[str, FlatFilter] = {}
        self._load_issues: list[PluginLoadIssue] = []
        self._reserved_jinja2_filters = frozenset(jinja_environment.filters)
        self._reserved_jinja2_functions = frozenset(jinja_environment.globals) | {
            "nf_shared_data",
            "nf_media_search_payload",
            "nf_media_input_payload",
        }
        self._reserved_flat_filters = frozenset(
            name.casefold()
            for name in (
                "upper",
                "lower",
                "title",
                "swapcase",
                "capitalize",
                "zfill",
                "replace",
            )
        )

    @property
    def records(self) -> tuple[PluginRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    @property
    def plugin_ids(self) -> frozenset[str]:
        return frozenset(self._records)

    @property
    def load_issues(self) -> tuple[PluginLoadIssue, ...]:
        return tuple(self._load_issues)

    def clear_load_issues(self) -> None:
        self._load_issues.clear()

    def record_load_issue(self, source: str, reason: str) -> None:
        self._load_issues.append(PluginLoadIssue(source, reason))

    def register(
        self, plugin_id: str, definition: PluginDefinition, source: str
    ) -> PluginRecord:
        self._validate(plugin_id, definition)
        if plugin_id in self._records:
            raise PluginError(f"Duplicate plugin id: '{plugin_id}'")

        self._check_contribution_conflicts(plugin_id, definition)
        record = PluginRecord(plugin_id, definition, source)
        self._records[plugin_id] = record
        self._jinja2_filters.update(definition.jinja2_filters)
        self._jinja2_functions.update(definition.jinja2_functions)
        self._flat_filters.update(definition.flat_filters)
        return record

    def get(self, plugin_id: str | None) -> PluginRecord | None:
        if not plugin_id:
            return None
        return self._records.get(plugin_id)

    def definitions_with(self, capability: str) -> tuple[PluginRecord, ...]:
        return tuple(
            record
            for record in self.records
            if getattr(record.definition, capability, None) is not None
        )

    def jinja2_filters(self, *, enabled: bool) -> dict[str, Any]:
        return dict(self._jinja2_filters) if enabled else {}

    def jinja2_functions(self, *, enabled: bool) -> dict[str, Any]:
        return dict(self._jinja2_functions) if enabled else {}

    def flat_filters(self, *, enabled: bool) -> dict[str, FlatFilter]:
        return dict(self._flat_filters) if enabled else {}

    def replace_tokens(self, plugin_id: str, request: TokenReplaceRequest) -> str:
        record = self._require_capability(plugin_id, "token_replacer")
        replacer = record.definition.token_replacer
        # type-narrowing only: `_require_capability` already raised PluginError
        # above if this attribute were None, so the condition can't be false here
        assert replacer is not None  # noqa: S101
        try:
            result = replacer(request)
        except Exception as error:
            raise PluginExecutionError(plugin_id, "token_replacer", error) from error
        if result is not None and not isinstance(result, str):
            raise PluginExecutionError(
                plugin_id,
                "token_replacer",
                TypeError("token replacer must return str or None"),
            )
        return result if result is not None else request.text

    def run_pre_upload(
        self, plugin_id: str, request: PreUploadRequest
    ) -> PreUploadDecision:
        record = self._require_capability(plugin_id, "pre_upload")
        processor = record.definition.pre_upload
        # type-narrowing only: `_require_capability` already raised PluginError
        # above if this attribute were None, so the condition can't be false here
        assert processor is not None  # noqa: S101
        try:
            result = processor(request)
        except Exception as error:
            raise PluginExecutionError(plugin_id, "pre_upload", error) from error
        if not isinstance(result, PreUploadDecision):
            raise PluginExecutionError(
                plugin_id,
                "pre_upload",
                TypeError("pre-upload processor must return PreUploadDecision"),
            )
        return result

    def transform_metadata(
        self, plugin_id: str, request: MetadataTransformRequest
    ) -> MediaSearchPayload:
        """Run a transformer against an isolated copy and commit only valid output."""

        from src.payloads.media_search import MediaSearchPayload

        record = self._require_capability(plugin_id, "metadata_transformer")
        transformer = record.definition.metadata_transformer
        # type-narrowing only: `_require_capability` already raised PluginError
        # above if this attribute were None, so the condition can't be false here
        assert transformer is not None  # noqa: S101
        isolated_payload = deepcopy(request.payload)
        isolated_request = MetadataTransformRequest(
            config=request.config,
            context=replace(request.context, media_search=isolated_payload),
            payload=isolated_payload,
            timeout=request.timeout,
        )
        result = self._run_transformer_with_timeout(
            plugin_id, transformer, isolated_request, request.timeout
        )
        if result is None:
            return request.payload
        if not isinstance(result, MediaSearchPayload):
            raise PluginExecutionError(
                plugin_id,
                "metadata_transformer",
                TypeError(
                    "metadata transformer must return MediaSearchPayload or None"
                ),
            )
        try:
            result.validate()
            return deepcopy(result)
        except Exception as error:
            raise PluginExecutionError(
                plugin_id, "metadata_transformer", error
            ) from error

    @staticmethod
    def _run_transformer_with_timeout(
        plugin_id: str,
        transformer: MetadataTransformer,
        isolated_request: MetadataTransformRequest,
        timeout: int,
    ) -> MediaSearchPayload | None:
        """Run `transformer` on a background thread and enforce `timeout`.

        A transformer's worker thread cannot be forcibly killed, so a hung
        transformer is abandoned rather than awaited: the worker keeps running
        as a daemon thread, which does not block interpreter exit (unlike a
        `ThreadPoolExecutor` worker, which is non-daemon and would be joined by
        an `atexit` handler at shutdown).

        Abandoning it is safe only for `isolated_request.payload` and
        `isolated_request.context.media_search`: both wrap a deep copy, so a
        write to either from the abandoned thread after this function returns
        can never reach canonical state. `isolated_request.config` is *not*
        isolated -- it is the live `ConfigManager` shared with the UI thread,
        by reference (deep-copying it is not viable; it owns the plugin
        manager and the live settings tree). Transformers must already treat
        `config` as read-only (see `docs/view/plugins/metadata-transformers.md`);
        a transformer that writes to `config` and then hangs can race the UI
        thread for as long as it keeps running, and this timeout provides no
        protection against that.
        """

        outcome = _TransformOutcome()

        def _run() -> None:
            try:
                outcome.value = transformer(isolated_request)
            except BaseException as error:
                # Catch BaseException, not Exception: a transformer calling
                # sys.exit() raises SystemExit, which Exception does not
                # catch. Left uncaught, the thread would die silently,
                # outcome would stay empty, and the caller would read that
                # as "the transformer chose not to change anything" instead
                # of a crash. KeyboardInterrupt cannot be delivered to a
                # non-main thread, so catching BaseException here does not
                # carry the usual risk of swallowing an interactive
                # interrupt.
                outcome.error = error

        worker = threading.Thread(
            target=_run,
            name=f"plugin-transform-{plugin_id}",
            daemon=True,
        )
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            raise PluginExecutionError(
                plugin_id,
                "metadata_transformer",
                TimeoutError(f"timed out after {timeout}s and was abandoned"),
            )
        if outcome.error is not None:
            raise PluginExecutionError(
                plugin_id, "metadata_transformer", outcome.error
            ) from outcome.error
        return outcome.value

    def _require_capability(self, plugin_id: str, capability: str) -> PluginRecord:
        record = self.get(plugin_id)
        if record is None:
            raise PluginError(f"Plugin '{plugin_id}' is not available")
        if getattr(record.definition, capability, None) is None:
            raise PluginError(f"Plugin '{plugin_id}' does not provide '{capability}'")
        return record

    @staticmethod
    def _validate(plugin_id: str, definition: PluginDefinition) -> None:
        if not _PLUGIN_ID_PATTERN.fullmatch(plugin_id):
            raise PluginError(
                "Plugin id must be lowercase and contain only letters, numbers, "
                "dots, underscores, or hyphens"
            )
        if not isinstance(definition, PluginDefinition):
            raise PluginError("Plugin export must be a PluginDefinition")
        if not definition.display_name.strip():
            raise PluginError("Plugin display_name cannot be empty")
        if not definition.version.strip():
            raise PluginError("Plugin version cannot be empty")
        if definition.api_version != PLUGIN_API_VERSION:
            raise PluginError(
                f"Unsupported plugin API version {definition.api_version}; "
                f"NfoForge requires {PLUGIN_API_VERSION}"
            )

        capabilities = (
            definition.wizard_page,
            definition.token_replacer,
            definition.pre_upload,
            definition.metadata_transformer,
            definition.jinja2_filters,
            definition.jinja2_functions,
            definition.flat_filters,
        )
        if not any(capabilities):
            raise PluginError("Plugin must provide at least one capability")

        if definition.wizard_page is not None:
            from src.frontend.wizards.wizard_base_page import BaseWizardPage

            if not isinstance(definition.wizard_page, type) or not issubclass(
                definition.wizard_page, BaseWizardPage
            ):
                raise PluginError("wizard_page must be a BaseWizardPage subclass")

        for name in ("token_replacer", "pre_upload", "metadata_transformer"):
            value = getattr(definition, name)
            if value is not None and not callable(value):
                raise PluginError(f"{name} must be callable")

        for name in ("jinja2_filters", "jinja2_functions", "flat_filters"):
            mapping = getattr(definition, name)
            if not isinstance(mapping, Mapping):
                raise PluginError(f"{name} must be a mapping")
            if not all(
                isinstance(key, str) and key.strip() and callable(value)
                for key, value in mapping.items()
            ):
                raise PluginError(
                    f"{name} must contain non-empty string names and callables"
                )

    def _check_contribution_conflicts(
        self, plugin_id: str, definition: PluginDefinition
    ) -> None:
        groups = (
            (
                "Jinja2 filter",
                definition.jinja2_filters,
                set(self._jinja2_filters) | self._reserved_jinja2_filters,
            ),
            (
                "Jinja2 function",
                definition.jinja2_functions,
                set(self._jinja2_functions) | self._reserved_jinja2_functions,
            ),
            (
                "flat filter",
                definition.flat_filters,
                set(self._flat_filters) | self._reserved_flat_filters,
            ),
        )
        for label, incoming, existing in groups:
            if label == "flat filter":
                existing_normalized = {name.casefold() for name in existing}
                duplicates = sorted(
                    name for name in incoming if name.casefold() in existing_normalized
                )
            else:
                duplicates = sorted(set(incoming) & set(existing))
            if duplicates:
                raise PluginError(
                    f"Plugin '{plugin_id}' duplicates {label} name(s): "
                    f"{', '.join(duplicates)}"
                )
