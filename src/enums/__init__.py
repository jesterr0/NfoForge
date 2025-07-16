from enum import Enum, StrEnum


def _missing_func(cls, value):
    """Helper function to check member/value for a match."""
    if value:
        value = str(value).lower()
        for member in cls:
            member_lowered = member.name.lower()
            value_lowered = member.value.lower()
            if (
                (member_lowered == value)
                or (member_lowered.replace("_", " ") == value)
                or (value_lowered == value)
                or (value_lowered.replace("_", " ") == value)
            ):
                return member


class CaseInsensitiveEnum(Enum):
    """Case insensitive Enum that will attempt to match on both the value and member."""

    @classmethod
    def _missing_(cls, value):
        """Override this method to ignore case sensitivity"""
        missing = _missing_func(cls, value)
        if missing:
            return missing
        raise ValueError(f"No {cls.__name__} member with value '{value}'")


class CaseInsensitiveStrEnum(StrEnum):
    """Case insensitive StrEnum that will attempt to match on both the value and member."""

    @classmethod
    def _missing_(cls, value):
        """Override this method to ignore case sensitivity"""
        missing = _missing_func(cls, value)
        if missing:
            return missing
        raise ValueError(f"No {cls.__name__} member with value '{value}'")
