from dataclasses import dataclass, field


@dataclass(slots=True)
class TorrentClient:
    enabled: bool = False
    host: str | None = None
    port: int | None = None
    user: str | None = None
    password: str | None = None
    specific_params: dict[str, str | bool] = field(default_factory=dict)
