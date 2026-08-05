from dataclasses import dataclass

from src.payloads.image_hosts import ImagePayloadBase


@dataclass(slots=True)
class PixhostPayload(ImagePayloadBase):
    pass
