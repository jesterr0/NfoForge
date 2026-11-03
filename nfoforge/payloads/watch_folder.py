from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class WatchFolder:
    enabled: bool = False
    path: Path | None = None
