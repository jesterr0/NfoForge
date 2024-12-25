from enum import Enum


class CaseInsensitiveEnum(Enum):
    @classmethod
    def _missing_(cls, value):
        """Override this method to ignore case sensitivity"""
        if value:
            value = str(value).lower()
            for member in cls:
                member_lowered = member.name.lower()
                if (member_lowered == value) or (
                    member_lowered.replace("_", " ") == value
                ):
                    return member
        raise ValueError(f"No {cls.__name__} member with value '{value}'")
