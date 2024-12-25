from dataclasses import dataclass

from src.packages.custom_types import CropValues, AdvancedResize


@dataclass(slots=True)
class ScriptValues:
    crop_values: CropValues | None = None
    advanced_resize: AdvancedResize | None = None

    def all_set(self) -> bool:
        """Check if all fields are not None"""
        return all(
            getattr(self, field.name) is not None
            for field in self.__dataclass_fields__.values()
        )
