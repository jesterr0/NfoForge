import re
from os import PathLike
from typing import Optional
from pathlib import Path
from pymediainfo import MediaInfo


def calculate_avg_video_bit_rate(mi_object: Optional[MediaInfo]) -> Optional[int]:
    mi_bit_rate = None
    if mi_object:
        video_track = mi_object.video_tracks[0]
        general_track = mi_object.general_tracks[0]

        # calculate average video bitrate
        if video_track.stream_size and video_track.duration:
            mi_bit_rate = round(
                (float(video_track.stream_size) / 1000)
                / ((float(video_track.duration) / 60000) * 0.0075)
                / 1000
            )

        # if one of the above metrics is missing attempt to calculate it roughly
        # with the general track info
        elif general_track.file_size and general_track.duration:
            mi_bit_rate = round(
                (float(general_track.file_size) / 1000)
                / ((float(general_track.duration) / 60000) * 0.0075)
                / 1000
                * 0.88
            )
    return mi_bit_rate


class MinimalMediaInfo:
    def __init__(self, file_input: PathLike):
        self.file_input = Path(file_input)

    def get_full_mi_str(self, cleansed: bool = False) -> str:
        if cleansed:
            return self.cleanse_mi(
                str(MediaInfo.parse(self.file_input, full=False, output=""))
            )
        return str(MediaInfo.parse(self.file_input, full=False, output=""))

    def get_minimal_mi_str(self) -> str:
        """Mocks MediaInfo's normal output with stripped down information"""
        LENGTH = 41
        mi_str = ""
        media_info_obj = MediaInfo.parse(self.file_input)

        if not isinstance(media_info_obj, MediaInfo):
            raise TypeError("Should be of type 'MediaInfo'")

        for track in media_info_obj.general_tracks:
            if track.track_type == "General":
                mi_str = mi_str + "General\n"
                if track.file_name_extension:
                    mi_str = (
                        mi_str
                        + "Complete name".ljust(LENGTH, " ")
                        + f": {track.file_name_extension}\n"
                    )
                if track.other_file_size:
                    mi_str = (
                        mi_str
                        + "File size".ljust(LENGTH, " ")
                        + f": {track.other_file_size[0]}\n"
                    )
                if track.other_duration:
                    mi_str = (
                        mi_str
                        + "Duration".ljust(LENGTH, " ")
                        + f": {track.other_duration[0]}\n"
                    )
                if track.other_overall_bit_rate_mode:
                    mi_str = (
                        mi_str
                        + "Overall bit rate mode".ljust(LENGTH, " ")
                        + f": {track.other_overall_bit_rate_mode[0]}\n"
                    )
                if track.other_overall_bit_rate:
                    mi_str = (
                        mi_str
                        + "Overall bit rate".ljust(LENGTH, " ")
                        + f": {track.other_overall_bit_rate[0]}\n"
                    )
                if track.other_frame_rate:
                    mi_str = (
                        mi_str
                        + "Frame rate".ljust(LENGTH, " ")
                        + f": {track.other_frame_rate[0]}\n"
                    )
                mi_str = mi_str + "\n"

        for track in media_info_obj.video_tracks:
            mi_str = mi_str + "Video\n"
            if track.track_id:
                mi_str = mi_str + "ID".ljust(LENGTH, " ") + f": {track.track_id}\n"
            if track.format:
                mi_str = mi_str + "Format".ljust(LENGTH, " ") + f": {track.format}\n"
            if track.format_profile:
                mi_str = (
                    mi_str
                    + "Format profile".ljust(LENGTH, " ")
                    + f": {track.format_profile}\n"
                )
            if track.other_hdr_format:
                mi_str = (
                    mi_str
                    + "HDR format".ljust(LENGTH, " ")
                    + f": {track.other_hdr_format[0]}\n"
                )
            if track.other_duration:
                mi_str = (
                    mi_str
                    + "Duration".ljust(LENGTH, " ")
                    + f": {track.other_duration[0]}\n"
                )
            if track.other_bit_rate:
                mi_str = (
                    mi_str
                    + "Bit rate".ljust(LENGTH, " ")
                    + f": {track.other_bit_rate[0]}\n"
                )
            if track.other_width:
                mi_str = (
                    mi_str + "Width".ljust(LENGTH, " ") + f": {track.other_width[0]}\n"
                )
            if track.other_height:
                mi_str = (
                    mi_str
                    + "Height".ljust(LENGTH, " ")
                    + f": {track.other_height[0]}\n"
                )
            if track.other_display_aspect_ratio:
                mi_str = (
                    mi_str
                    + "Display aspect ratio".ljust(LENGTH, " ")
                    + f": {track.other_display_aspect_ratio[0]}\n"
                )
            if track.other_frame_rate:
                mi_str = (
                    mi_str
                    + "Frame rate".ljust(LENGTH, " ")
                    + f": {track.other_frame_rate[0]}\n"
                )
            if track.color_space:
                mi_str = (
                    mi_str
                    + "Color space".ljust(LENGTH, " ")
                    + f": {track.color_space}\n"
                )
            if track.chroma_subsampling:
                mi_str = (
                    mi_str
                    + "Chroma subsampling".ljust(LENGTH, " ")
                    + f": {track.chroma_subsampling}\n"
                )
            if track.other_bit_depth:
                mi_str = (
                    mi_str
                    + "Bit depth".ljust(LENGTH, " ")
                    + f": {track.other_bit_depth[0]}\n"
                )
            mi_str = mi_str + "\n"

        for idx, track in enumerate(media_info_obj.audio_tracks, start=1):
            mi_str = mi_str + f"Audio #{idx}\n"
            if track.track_id:
                mi_str = mi_str + "ID".ljust(LENGTH, " ") + f": {track.track_id}\n"
            if track.commercial_name:
                mi_str = (
                    mi_str
                    + "Commercial name".ljust(LENGTH, " ")
                    + f": {track.commercial_name}\n"
                )
            if track.codec_id:
                mi_str = (
                    mi_str + "Codec ID".ljust(LENGTH, " ") + f": {track.codec_id}\n"
                )
            if track.other_bit_rate:
                mi_str = (
                    mi_str
                    + "Bit rate".ljust(LENGTH, " ")
                    + f": {track.other_bit_rate[0]}\n"
                )
            if track.other_channel_s:
                mi_str = (
                    mi_str
                    + "Channel(s)".ljust(LENGTH, " ")
                    + f": {track.other_channel_s[0]}\n"
                )
            if track.channel_layout:
                mi_str = (
                    mi_str
                    + "ChannelLayout_Original".ljust(LENGTH, " ")
                    + f": {track.channel_layout}\n"
                )
            if track.other_sampling_rate:
                mi_str = (
                    mi_str
                    + "Sampling rate".ljust(LENGTH, " ")
                    + f": {track.other_sampling_rate[0]}\n"
                )
            if track.other_bit_depth:
                mi_str = (
                    mi_str
                    + "Bit depth".ljust(LENGTH, " ")
                    + f": {track.other_bit_depth[0]}\n"
                )
            if track.other_language:
                mi_str = (
                    mi_str
                    + "Language".ljust(LENGTH, " ")
                    + f": {track.other_language[0]}\n"
                )
            mi_str = mi_str + "\n"

        for idx, track in enumerate(media_info_obj.text_tracks, start=1):
            mi_str = mi_str + f"Text #{idx}\n"
            if track.track_id:
                mi_str = mi_str + "ID".ljust(LENGTH, " ") + f": {track.track_id}\n"
            if track.format:
                mi_str = mi_str + "Format".ljust(LENGTH, " ") + f": {track.format}\n"
            if track.other_language:
                mi_str = (
                    mi_str
                    + "Language".ljust(LENGTH, " ")
                    + f": {track.other_language[0]}\n"
                )
            if track.title:
                mi_str = mi_str + "Title".ljust(LENGTH, " ") + f": {track.title}\n"
            mi_str = mi_str + "\n"

        for track in media_info_obj.menu_tracks:
            mi_str = mi_str + "Menu\n"
            track_data = track.to_data()
            end_key_index = list(track_data.keys()).index("chapters_pos_end")
            if end_key_index:
                chapters = {
                    key: value
                    for key, value in list(track_data.items())[end_key_index + 1 :]
                }
                for key, value in chapters.items():
                    mi_str = mi_str + str(key).ljust(LENGTH, " ") + f": {value}\n"
            mi_str = mi_str + "\n"

        mi_str = "\n".join(mi_str.splitlines())
        return mi_str

    @staticmethod
    def cleanse_mi(mi: str) -> str:
        """cleanse media-info string removing Unique ID and full path name"""
        # removing non unix style \r\n to cross platform \n
        mi = "\n".join(mi.splitlines())
        search = re.search(r"Complete\sname\s+?:\s(.+?)\n", mi, flags=re.MULTILINE)
        if search:
            file_name = Path(search.group(1))
            mi = mi.replace(search.group(1).strip(), file_name.name)
        else:
            raise ValueError("Failed to strip full 'Complete name' from MediaInfo")
        return mi
