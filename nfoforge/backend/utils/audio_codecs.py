import json
from pathlib import Path

from pymediainfo import Track

AudioConventions = dict[str, str | dict[str, str]]


class AudioCodecs:
    def get_codec(self, mi_obj: Track, json_path: Path) -> str:
        audio_conventions = self._read_json(json_path)
        return self._codec_logic(mi_obj, audio_conventions)

    @staticmethod
    def _read_json(json_path: Path) -> AudioConventions:
        with open(json_path) as json_file:
            loaded_data: object = json.load(json_file)

        if not isinstance(loaded_data, dict):
            raise ValueError("Audio codec conventions must be a JSON object")

        conventions: AudioConventions = {}
        for codec, format_data in loaded_data.items():
            if not isinstance(codec, str):
                raise ValueError("Audio codec convention keys must be strings")
            if isinstance(format_data, str):
                conventions[codec] = format_data
                continue
            if not isinstance(format_data, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in format_data.items()
            ):
                raise ValueError(
                    "Audio codec conventions must map to strings or string mappings"
                )
            conventions[codec] = format_data

        return conventions

    @staticmethod
    def _codec_logic(mi_obj: Track, audio_conventions: AudioConventions) -> str:
        """
        Compares the audio codec obtained via MediaInfo with the provided naming convention dictionary.
        If the codec in the dictionary has nested formats, it attempts to match the 'other_format' of the input codec.
        If no matching key is found, it defaults to the first format listed in the nested dictionary.

        Returns:
            str: Correctly formatted string representing the audio codec.
        """

        codec = mi_obj.format
        if not isinstance(codec, str):
            return ""

        other_format = mi_obj.other_format[0] if mi_obj.other_format else None
        if not isinstance(other_format, str):
            other_format = None

        if codec in audio_conventions:
            codec_formats = audio_conventions[codec]

            if isinstance(codec_formats, dict):
                if other_format:
                    nested_formats = codec_formats.get(other_format)
                    if nested_formats:
                        return nested_formats
                # If other_format is not found or codec_formats is not a dictionary, return the first format
                return next(iter(codec_formats.values()))
            else:
                return codec_formats

        # Return the original codec if not found in audio_conventions
        return codec
