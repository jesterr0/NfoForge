from dataclasses import dataclass

from typing_extensions import override

from src.payloads.image_hosts import ImagePayloadBase


@dataclass(slots=True)
class CheveretoV3Payload(ImagePayloadBase):
    user: str | None = None
    password: str | None = None
    instance_id: str = ""
    label: str = ""

    @override
    def is_configured(self) -> bool:
        return bool(self.base_url and self.user and self.password and self.label)
