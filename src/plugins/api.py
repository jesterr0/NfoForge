from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from src.config.config import ConfigManager
    from src.context.processing_context import ProcessingContext
    from src.enums.tracker_selection import TrackerSelection
    from src.frontend.wizards.wizard_base_page import BaseWizardPage
    from src.packages.custom_types import ImageUploadData
    from src.payloads.media_search import MediaSearchPayload


PLUGIN_API_VERSION = 1


class MetadataMediaKind(Enum):
    """Normalized media kinds a metadata transformer may report."""

    MOVIE = "movie"
    TV_MOVIE = "tv_movie"
    SHORT = "short"
    MINI_SERIES = "mini_series"
    STAND_UP_COMEDY = "stand_up_comedy"
    LIVE_PERFORMANCE = "live_performance"


@dataclass(frozen=True, slots=True)
class TokenReplaceRequest:
    """Inputs supplied to a token-replacer plugin."""

    config: ConfigManager
    context: ProcessingContext
    text: str
    trackers: Sequence[TrackerSelection]
    tracker_images: Mapping[int, ImageUploadData] | None = None
    formatted_screens: str | None = None
    preview: bool = False


class TokenReplacer(Protocol):
    def __call__(self, request: TokenReplaceRequest, /) -> str | None: ...


@dataclass(frozen=True, slots=True)
class UploadReporter:
    """Thread-safe UI reporting callbacks available during pre-upload work."""

    append_text: Callable[[str], None]
    replace_last_line: Callable[[str], None]
    set_progress: Callable[[float], None]


@dataclass(frozen=True, slots=True)
class PreUploadRequest:
    """Inputs supplied to a pre-upload plugin."""

    config: ConfigManager
    context: ProcessingContext
    tracker: TrackerSelection
    torrent_file: Path
    reporter: UploadReporter


class PreUploadDecision(Enum):
    CONTINUE = "continue"
    SKIP = "skip"


class PreUploadProcessor(Protocol):
    def __call__(self, request: PreUploadRequest, /) -> PreUploadDecision: ...


@dataclass(frozen=True, slots=True)
class MetadataTransformRequest:
    """A private payload copy that a metadata plugin may update and return."""

    config: ConfigManager
    context: ProcessingContext
    payload: MediaSearchPayload
    timeout: int


class MetadataTransformer(Protocol):
    def __call__(
        self, request: MetadataTransformRequest, /
    ) -> MediaSearchPayload | None: ...


class FlatFilter(Protocol):
    def __call__(self, value: str, *args: Any) -> str: ...


@dataclass(frozen=True, slots=True)
class PluginDefinition:
    """The single typed object exported by an NfoForge plugin."""

    display_name: str
    version: str
    api_version: int = PLUGIN_API_VERSION
    description: str = ""
    wizard_page: type[BaseWizardPage] | None = None
    token_replacer: TokenReplacer | None = None
    pre_upload: PreUploadProcessor | None = None
    metadata_transformer: MetadataTransformer | None = None
    jinja2_filters: Mapping[str, Callable[..., Any]] = field(default_factory=dict)
    jinja2_functions: Mapping[str, Callable[..., Any]] = field(default_factory=dict)
    flat_filters: Mapping[str, FlatFilter] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PluginRecord:
    """A validated plugin and its stable application identity."""

    plugin_id: str
    definition: PluginDefinition
    source: str
