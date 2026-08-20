from dataclasses import dataclass, field
from pathlib import Path

from src.enums.tracker_selection import TrackerSelection
from src.nf_jinja2 import Jinja2TemplateEngine
from src.packages.custom_types import ImageUploadData, RenameNormalization
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
    custom_edition_info: tuple[RenameNormalization, ...] = field(default_factory=tuple)
    custom_cut_names: frozenset[str] = field(default_factory=frozenset)

    # Runtime-only identity/state for the saved job this run was loaded from,
    # archived or not.  The job codec intentionally ignores these fields; the
    # document is reconciled explicitly after an upload reaches a terminal
    # outcome, which is what stops a finished job from still listing every
    # tracker as pending and being uploaded a second time.
    loaded_job_path: Path | None = None
    loaded_job_id: str | None = None
    loaded_job_name: str | None = None
    loaded_job_archived: bool = False
    """Whether that job was already a reusable archive.

    Only an archive can be prepared without its original media, so this is what
    separates "update the archive in place" from the ordinary named save.
    """

    loaded_uploaded_trackers: set[TrackerSelection] = field(default_factory=set)
    loaded_uncertain_trackers: set[TrackerSelection] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.jinja_engine.add_global("nf_shared_data", self.shared_data, True)
        self.jinja_engine.add_global("nf_media_search_payload", self.media_search, True)
        self.jinja_engine.add_global("nf_media_input_payload", self.media_input, True)
