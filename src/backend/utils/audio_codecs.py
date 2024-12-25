import json
from pathlib import Path
from pymediainfo import Track


class AudioCodecs:
    def get_codec(self, mi_obj: Track, json_path: Path) -> str:
        audio_conventions = self._read_json(json_path)
        return self._codec_logic(mi_obj, audio_conventions)

    @staticmethod
    def _read_json(json_path: Path) -> dict:
        with open(json_path) as json_file:
            return json.load(json_file)

    @staticmethod
    def _codec_logic(mi_obj: Track, audio_conventions: dict):
        """
        Compares the audio codec obtained via MediaInfo with the provided naming convention dictionary.
        If the codec in the dictionary has nested formats, it attempts to match the 'other_format' of the input codec.
        If no matching key is found, it defaults to the first format listed in the nested dictionary.

        Returns:
            str: Correctly formatted string representing the audio codec.
        """

        codec = mi_obj.format
        other_format = mi_obj.other_format[0] if mi_obj.other_format else None

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
