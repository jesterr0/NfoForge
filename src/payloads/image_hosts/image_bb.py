from dataclasses import dataclass

from src.payloads.image_hosts import ImagePayloadBase


@dataclass(slots=True)
class ImageBBPayload(ImagePayloadBase):
    api_key: str | None = None
