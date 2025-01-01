from dataclasses import dataclass, field


@dataclass(slots=True)
class TrackerInfo:
    upload_enabled: bool = True
    anonymous: bool = False
    announce_url: str | None = None
    enabled: bool = False
    source: str | None = None
    comments: str | None = None
    nfo_template: str | None = None
    max_piece_size: int = 0
    specific_params: dict = field(default_factory=dict)
