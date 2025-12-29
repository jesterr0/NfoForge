from enum import Enum


class TVDBSeasonType(Enum):
    """TVDB Season Type IDs and their corresponding API parameters."""

    AIRED_ORDER = (1, "official", "Aired Order")
    DVD_ORDER = (2, "dvd", "DVD Order")
    ABSOLUTE_ORDER = (3, "absolute", "Absolute Order")

    def __init__(self, type_id: int, api_param: str, display_name: str):
        self.type_id = type_id
        self.api_param = api_param
        self.display_name = display_name

    @classmethod
    def get_main_types(cls: type["TVDBSeasonType"]):
        """Get the three main season types we care about."""
        return [cls.AIRED_ORDER, cls.DVD_ORDER, cls.ABSOLUTE_ORDER]

    @classmethod
    def get_by_id(cls: type["TVDBSeasonType"], type_id: int):
        """Get season type by its ID."""
        for season_type in cls:
            if season_type.type_id == type_id:
                return season_type
        return None

    @classmethod
    def get_by_api_param(cls: type["TVDBSeasonType"], api_param: str):
        """Get season type by its API parameter (e.g., 'official', 'dvd', 'absolute')."""
        for season_type in cls:
            if season_type.api_param == api_param:
                return season_type
        return None

    @classmethod
    def from_tvdb_season_type_info(cls: type["TVDBSeasonType"], season_type_info: dict):
        """
        Get season type from TVDB seasonTypes data structure.
        Tries ID mapping first, then falls back to type name mapping.

        Args:
            season_type_info: Dict with 'id' and 'type' fields from TVDB API

        Returns:
            TVDBSeasonType enum or None if not recognized
        """
        season_type_id = season_type_info.get("id")
        season_type_name = season_type_info.get("type")

        # try mapping by ID first
        if season_type_id is not None:
            season_type = cls.get_by_id(season_type_id)
            if season_type:
                return season_type

        # fall back to mapping by API parameter name
        if season_type_name:
            return cls.get_by_api_param(season_type_name)

        return None
