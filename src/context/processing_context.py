from dataclasses import dataclass, field
from pathlib import Path

from src.enums.tracker_selection import TrackerSelection
from src.nf_jinja2 import Jinja2TemplateEngine
from src.packages.custom_types import ImageUploadData
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from src.payloads.shared_data import SharedPayload


@dataclass(slots=True)
class ProcessingContext:
    """Encapsulates all state for a single processing run."""

    # input data payloads
    media_input: MediaInputPayload = field(default_factory=MediaInputPayload)
    media_search: MediaSearchPayload = field(default_factory=MediaSearchPayload)
    shared_data: SharedPayload = field(default_factory=SharedPayload)

    # processing outputs
    generated_torrents: dict[str, Path] = field(default_factory=dict)
    uploaded_images: dict[TrackerSelection, dict[int, ImageUploadData]] = field(
        default_factory=dict
    )

    # jinja engine (created per context)
    jinja_engine: Jinja2TemplateEngine | None = field(default=None, init=False)
