import re
from pymediainfo import MediaInfo
from src.enums.audio_channels import AudioChannels


class ParseAudioChannels:
    @staticmethod
    def get_channel_layout(mi_obj: MediaInfo.parse) -> str:
        num_channels = AudioChannels(ParseAudioChannels.get_channels(mi_obj)).value
        channel_positions = ParseAudioChannels._get_channel_layout(mi_obj)

        if "LFE" in channel_positions:
            num_channels -= 1

        return f"{num_channels}.{'1' if 'LFE' in channel_positions else '0'}"

    @staticmethod
    def _get_channel_layout(mi_obj: MediaInfo.parse) -> str:
        # TODO: with pcm/raw data we sometimes don't get a channel layout,
        # if this becomes a problem where invalid channel layouts are being
        # returned we'll need to prompt the user unless a better solution is
        # discovered.
        # We'll likely just prompt the user with possible channels
        channel_positions = ""

        if mi_obj.channel_positions:
            channel_positions = mi_obj.channel_positions

        if mi_obj.channellayout_original:
            channel_positions = mi_obj.channellayout_original

        return channel_positions

    @staticmethod
    def get_channels(mi_object):
        """
        Get the number of audio channels for the specified track.

        The added complexity for 'check_other' is to ensure we get a report
        of the highest potential channel count.

        Args:
            mi_object (MediaInfo): A MediaInfo object containing information about the media
            file's audio track.

        Returns:
            The number of audio channels as an integer.
        """
        base_channels = mi_object.channel_s
        check_other = re.search(r"\d+", str(mi_object.other_channel_s[0]))
        check_other_2 = str(mi_object.channel_s__original)

        # Create a list of values to find the maximum
        values = [int(base_channels)]

        if check_other:
            values.append(int(check_other.group()))

        if check_other_2.isdigit():
            values.append(int(check_other_2))

        return max(values)
