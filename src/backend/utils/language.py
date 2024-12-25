from typing import Union

from iso639 import Lang
from iso639.exceptions import InvalidLanguageValue
from pymediainfo import MediaInfo


def get_language_mi(
    media_track: MediaInfo.parse, char_code: int = 1
) -> Union[None, str]:
    """Used to properly detect the input language from pymediainfo track

    Args:
        media_track (MediaInfo.parse): pymediainfo track
        char_code (int, optional): 1 or 2, if set to 2 it returns 'en' else if 3 it returns 'eng'
    """
    if char_code not in {1, 2}:
        raise ValueError("Input must be (int) 1 or 2")

    if media_track.language:
        try:
            if char_code == 1:
                return str(Lang(media_track.language).pt1).upper()
            elif char_code == 2:
                return str(Lang(media_track.language).pt2b).upper()
        except InvalidLanguageValue:
            if media_track.other_language:
                for track in media_track.other_language:
                    try:
                        if char_code == 1:
                            return str(Lang(track).pt1).upper()
                        elif char_code == 2:
                            return str(Lang(track).pt2b).upper()
                    except InvalidLanguageValue:
                        try:
                            if char_code == 1:
                                return str(Lang(track.split(" ")[0]).pt1).upper()
                            elif char_code == 2:
                                return str(Lang(track.split(" ")[0]).pt2b).upper()
                        except InvalidLanguageValue:
                            continue
    return None


def get_language_str(language_str: str, char_code: int = 1) -> Union[None, str]:
    """Used to properly detect the input language from input string

    Args:
        language_str (str): Language input string
        char_code (int, optional): 1 or 2, if set to 2 it returns 'en' else if 3 it returns 'eng'
    """
    if char_code not in {1, 2}:
        raise ValueError("Input must be (int) 1 or 2")

    if language_str:
        try:
            if char_code == 1:
                return str(Lang(language_str).pt1).upper()
            elif char_code == 2:
                return str(Lang(language_str).pt2b).upper()
        except InvalidLanguageValue:
            return None
    return None
