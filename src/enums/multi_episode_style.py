from enum import IntEnum


class MultiEpisodeStyle(IntEnum):
    """Multi episode style options for series formatting"""

    EXTEND = 0
    DUPLICATE = 1
    REPEAT = 2
    SCENE = 3
    RANGE = 4
    PREFIXED_RANGE = 5

    def __str__(self) -> str:
        return self.name.replace("_", " ").title()
