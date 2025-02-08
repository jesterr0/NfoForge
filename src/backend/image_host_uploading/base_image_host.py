from abc import ABC, abstractmethod
from src.packages.custom_types import ImageUploadData


class BaseImageHostUploader(ABC):
    """Abstract base class for image host uploaders"""

    @abstractmethod
    async def upload(self, *args, **kwargs) -> dict[int, ImageUploadData] | None:
        """Uploads images and reports progress"""
        pass
