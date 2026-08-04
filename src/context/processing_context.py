from dataclasses import dataclass, field
from pathlib import Path

from src.enums.tracker_selection import TrackerSelection
from src.nf_jinja2 import Jinja2TemplateEngine
from src.packages.custom_types import ImageUploadData
from src.payloads.clients import TorrentClientRunOptions
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from src.payloads.shared_data import SharedPayload
from src.plugins.api import FlatFilter


@dataclass(slots=True)
class ProcessingContext:
    """Encapsulates all state for a single processing run."""

    # input data payloads
    media_input: MediaInputPayload = field(default_factory=MediaInputPayload)
    media_search: MediaSearchPayload = field(default_factory=MediaSearchPayload)
    shared_data: SharedPayload = field(default_factory=SharedPayload)
    torrent_client_options: TorrentClientRunOptions = field(
        default_factory=TorrentClientRunOptions
    )

    # processing outputs
    generated_torrents: dict[str, Path] = field(default_factory=dict)
    uploaded_images: dict[TrackerSelection, dict[int, ImageUploadData]] = field(
        default_factory=dict
    )

    jinja_engine: Jinja2TemplateEngine = field(default_factory=Jinja2TemplateEngine)
    flat_filters: dict[str, FlatFilter] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.jinja_engine.add_global("nf_shared_data", self.shared_data, True)
        self.jinja_engine.add_global("nf_media_search_payload", self.media_search, True)
        self.jinja_engine.add_global("nf_media_input_payload", self.media_input, True)
