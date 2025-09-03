from dataclasses import dataclass
import math

from src.packages.custom_types import AdvancedResize, CropValues


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

    def all_zeros(self) -> bool:
        """
        Return True when crop_values and advanced_resize are either None or
        present and all-zero. Returns False if any present field contains
        a non-zero component.
        """
        # CropValues: None or all ints == 0
        if self.crop_values is not None:
            if not all(
                getattr(self.crop_values, f) == 0 for f in self.crop_values._fields
            ):
                return False

        # AdvancedResize: None or all floats ~= 0
        if self.advanced_resize is not None:
            tol = 1e-9
            if not all(
                math.isclose(getattr(self.advanced_resize, f), 0.0, abs_tol=tol)
                for f in self.advanced_resize._fields
            ):
                return False

        return True
