import re

from pymediainfo import Track

from src.enums.audio_channels import AudioChannels


class ParseAudioChannels:
    __slots__ = ()

    @staticmethod
    def get_channel_layout(a_track: Track) -> str:
        num_channels = AudioChannels(ParseAudioChannels.get_channels(a_track)).value
        channel_positions = ParseAudioChannels._get_channel_layout(a_track)

        if "LFE" in channel_positions:
            num_channels -= 1

        return f"{num_channels}.{'1' if 'LFE' in channel_positions else '0'}"

    @staticmethod
    def _get_channel_layout(a_track: Track) -> str:
        # TODO: with pcm/raw data we sometimes don't get a channel layout,
        # if this becomes a problem where invalid channel layouts are being
        # returned we'll need to prompt the user unless a better solution is
        # discovered.
        # We'll likely just prompt the user with possible channels
        channel_positions = ""
        if a_track.channel_positions:
            channel_positions = a_track.channel_positions

        if a_track.channellayout_original:
            channel_positions = a_track.channellayout_original

        return channel_positions

    @staticmethod
    def get_channels(a_track: Track) -> int:
        """
        Get the number of audio channels for the specified track.

        The added complexity for 'check_other' is to ensure we get a report
        of the highest potential channel count.

        Args:
            mi_object (Track): MediaInfo track object containing information about the media
            file's audio track.

        Returns:
            The number of audio channels as an integer.
        """
        base_channels = a_track.channel_s
        check_other = re.search(r"\d+", str(a_track.other_channel_s[0]))
        check_other_2 = str(a_track.channel_s__original)

        # Create a list of values to find the maximum
        values = [int(base_channels)]

        if check_other:
            values.append(int(check_other.group()))

        if check_other_2.isdigit():
            values.append(int(check_other_2))

        return max(values)
