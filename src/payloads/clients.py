from dataclasses import dataclass, field


@dataclass(slots=True)
class TorrentClient:
    enabled: bool = False
    host: str = None
    port: int = None
    user: str = None
    password: str = None
    specific_params: dict = field(default=dict)
