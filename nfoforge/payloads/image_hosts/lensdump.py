from dataclasses import dataclass
from typing import override

from nfoforge.payloads.image_hosts import ImagePayloadBase


@dataclass(slots=True)
class LensdumpPayload(ImagePayloadBase):
    api_key: str | None = None

    @override
    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key)
