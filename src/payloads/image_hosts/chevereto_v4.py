from dataclasses import dataclass

from src.payloads.image_hosts import ImagePayloadBase


@dataclass(slots=True)
class CheveretoV4Payload(ImagePayloadBase):
    base_url: str | None = None
    api_key: str | None = None
