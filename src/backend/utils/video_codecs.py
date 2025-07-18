import re

from pymediainfo import MediaInfo, Track


class VideoCodecs:
    def get_codec(self, mi_obj: MediaInfo | None, guessit_obj: dict) -> str:
        parse_guessit = self._guessit(guessit_obj)
        parse_media_info = self._mediainfo(mi_obj)
        return self._process_results(parse_guessit, parse_media_info)

    @staticmethod
    def _guessit(guessit_obj: dict) -> str:
        video_codec = guessit_obj.get("video_codec", "")
        if video_codec in ["H.264", "H.265"]:
            video_codec = video_codec.replace("H.", "x")
        return video_codec

    def _mediainfo(self, mi_obj: MediaInfo | None) -> str | None:
        if mi_obj and mi_obj.video_tracks:
            detect_video_codec = mi_obj.video_tracks[0].format
            if detect_video_codec:
                if detect_video_codec == "AV1":
                    return self._avc(mi_obj.video_tracks[0])
                elif detect_video_codec == "AVC":
                    return self._avc(mi_obj.video_tracks[0])
                elif detect_video_codec == "HEVC":
                    return self._hevc(mi_obj.video_tracks[0])
                elif detect_video_codec == "MPEG Video":
                    return self._mpeg(mi_obj.video_tracks[0])
                elif detect_video_codec == "VC-1":
                    return self._vc1(mi_obj.video_tracks[0])
                elif detect_video_codec in ["VP8", "VP9"]:
                    return self._vpx(mi_obj.video_tracks[0])

    @staticmethod
    def _process_results(parse_guessit: str, parse_media_info: str | None) -> str:
        codec = ""
        if parse_guessit:
            codec = parse_guessit

        if parse_media_info:
            codec = parse_media_info
        return codec

    @staticmethod
    def _av1(mi_obj_video_track: Track) -> str:
        return mi_obj_video_track.format

    @staticmethod
    def _avc(mi_obj_video_track: Track) -> str:
        if (
            mi_obj_video_track.writing_library
            and "x264" in mi_obj_video_track.writing_library
        ):
            return "x264"
        if mi_obj_video_track.width and mi_obj_video_track.height:
            if mi_obj_video_track.width < 1920 or mi_obj_video_track.height < 1080:
                return "x264"
        return "AVC"

    @staticmethod
    def _hevc(mi_obj_video_track: Track) -> str:
        if (
            mi_obj_video_track.writing_library
            and "x265" in mi_obj_video_track.writing_library
        ):
            return "x265"
        if mi_obj_video_track.width and mi_obj_video_track.height:
            if mi_obj_video_track.width < 3840 or mi_obj_video_track.height < 2160:
                return "x265"
        if (
            mi_obj_video_track.hdr_format_profile
            and mi_obj_video_track.hdr_format_profile == "dvhe.07"
        ):
            return "HEVC"
        return "HEVC"

    @staticmethod
    def _mpeg(mi_obj_video_track: Track) -> str:
        if mi_obj_video_track.format_version:
            version_num = re.search(r"\d", mi_obj_video_track.format_version)
            if version_num and int(version_num.group()) > 1:
                return f"MPEG-{version_num.group()}"
        return "MPEG"

    @staticmethod
    def _vc1(mi_obj_video_track: Track) -> str:
        return mi_obj_video_track.format

    @staticmethod
    def _vpx(mi_obj_video_track: Track) -> str:
        return mi_obj_video_track.format
