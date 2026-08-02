from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
import re
from typing import TYPE_CHECKING, Any

from jinja2 import Environment

from src.exceptions import PluginError, PluginExecutionError
from src.plugins.api import (
    PLUGIN_API_VERSION,
    FlatFilter,
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


class PluginManager:
    """Validate, register, query, and invoke external plugins."""

    def __init__(self) -> None:
        jinja_environment = Environment()
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
        assert replacer is not None
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
        assert processor is not None
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
        assert transformer is not None
        isolated_payload = deepcopy(request.payload)
        isolated_request = MetadataTransformRequest(
            config=request.config,
            context=replace(request.context, media_search=isolated_payload),
            payload=isolated_payload,
            timeout=request.timeout,
        )
        try:
            result = transformer(isolated_request)
        except Exception as error:
            raise PluginExecutionError(
                plugin_id, "metadata_transformer", error
            ) from error
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
