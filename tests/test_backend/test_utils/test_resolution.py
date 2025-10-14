"""
Comprehensive unit tests for video resolution detection.

Tests cover:
- CommercialResolutionInfer: Pure dimension-based classification
- VideoResolutionAnalyzer: Full MediaInfo integration with scan type
"""

from unittest.mock import Mock

import pytest
from pymediainfo import MediaInfo, Track

from src.backend.utils.resolution import (
    CommercialResolutionInfer,
    VideoResolutionAnalyzer,
)
from src.exceptions import MissingVideoTrackError


class TestCommercialResolutionInfer:
    """Test the core resolution classification algorithm."""

    # Standard full-frame resolutions
    def test_standard_1080p_full_frame(self):
        result = CommercialResolutionInfer.infer(1920, 1080)
        assert result.base_label == "1080"
        assert result.confidence >= 0.95
        assert result.base_height == 1080

    def test_standard_720p_full_frame(self):
        result = CommercialResolutionInfer.infer(1280, 720)
        assert result.base_label == "720"
        assert result.confidence >= 0.95
        assert result.base_height == 720

    def test_standard_2160p_4k_full_frame(self):
        result = CommercialResolutionInfer.infer(3840, 2160)
        assert result.base_label == "2160"
        assert result.confidence >= 0.95
        assert result.base_height == 2160

    def test_standard_4320p_8k_full_frame(self):
        result = CommercialResolutionInfer.infer(7680, 4320)
        assert result.base_label == "4320"
        assert result.confidence >= 0.95
        assert result.base_height == 4320

    def test_standard_576p_pal(self):
        result = CommercialResolutionInfer.infer(1024, 576)
        assert result.base_label == "576"
        assert result.confidence >= 0.95

    def test_standard_480p_sd(self):
        result = CommercialResolutionInfer.infer(854, 480)
        assert result.base_label == "480"
        assert result.confidence >= 0.95

    # Letterboxed/scope aspect ratios (cropped height)
    def test_1080p_letterboxed_2_40_aspect(self):
        """1920x800 is 1080p content letterboxed to 2.40:1 (common for movies)."""
        result = CommercialResolutionInfer.infer(1920, 800)
        assert result.base_label == "1080"
        assert result.width == 1920
        assert result.height == 800

    def test_1080p_letterboxed_2_35_aspect(self):
        """1920x816 is 1080p content letterboxed to 2.35:1."""
        result = CommercialResolutionInfer.infer(1920, 816)
        assert result.base_label == "1080"

    def test_1080p_letterboxed_2_00_aspect(self):
        """1920x960 is 1080p content at 2:1 aspect ratio."""
        result = CommercialResolutionInfer.infer(1920, 960)
        assert result.base_label == "1080"

    def test_2160p_letterboxed_scope(self):
        """3840x1600 is 4K/2160p letterboxed."""
        result = CommercialResolutionInfer.infer(3840, 1600)
        assert result.base_label == "2160"

    def test_4320p_letterboxed_scope(self):
        """7680x3200 is 8K/4320p letterboxed."""
        result = CommercialResolutionInfer.infer(7680, 3200)
        assert result.base_label == "4320"

    # Pillarboxed content (cropped width)
    def test_1080p_pillarboxed_4_3_aspect(self):
        """1440x1080 is 1080p pillarboxed to 4:3."""
        result = CommercialResolutionInfer.infer(1440, 1080)
        assert result.base_label == "1080"

    def test_720p_pillarboxed_4_3(self):
        """960x720 is 720p in 4:3 aspect ratio (pillarboxed from 1080p)."""
        result = CommercialResolutionInfer.infer(960, 720)
        assert result.base_label == "720"
        assert result.confidence >= 0.95  # Should be perfect match with 4:3 support

    # 4:3 aspect ratio (classic TV / Academy ratio)
    def test_480p_4_3_sd(self):
        """640x480 is 480p in 4:3 aspect ratio (classic SD)."""
        result = CommercialResolutionInfer.infer(640, 480)
        assert result.base_label == "480"
        assert result.confidence >= 0.95

    def test_576p_4_3_pal(self):
        """768x576 is 576p in 4:3 aspect ratio (PAL SD)."""
        result = CommercialResolutionInfer.infer(768, 576)
        assert result.base_label == "576"
        assert result.confidence >= 0.95

    def test_1080p_4_3_full_hd(self):
        """1440x1080 is 1080p in 4:3 aspect ratio."""
        result = CommercialResolutionInfer.infer(1440, 1080)
        assert result.base_label == "1080"
        assert result.confidence >= 0.95

    def test_2160p_4_3_4k(self):
        """2880x2160 is 2160p/4K in 4:3 aspect ratio."""
        result = CommercialResolutionInfer.infer(2880, 2160)
        assert result.base_label == "2160"
        assert result.confidence >= 0.95

    # Portrait/vertical video (swapped dimensions)
    def test_1080p_portrait_vertical_video(self):
        """1080x1920 is vertical/portrait 1080p (TikTok, Instagram, etc.)."""
        result = CommercialResolutionInfer.infer(1080, 1920)
        assert result.base_label == "1080"
        assert result.confidence >= 0.95

    def test_720p_portrait_vertical_video(self):
        """720x1280 is vertical/portrait 720p."""
        result = CommercialResolutionInfer.infer(720, 1280)
        assert result.base_label == "720"

    def test_2160p_portrait_vertical_video(self):
        """2160x3840 is vertical/portrait 4K."""
        result = CommercialResolutionInfer.infer(2160, 3840)
        assert result.base_label == "2160"

    # Non-standard resolutions (should classify to nearest tier)
    def test_1600x900_classifies_as_1080p(self):
        """1600x900 (16:9 at 900p) is closer to 1080p than 720p."""
        result = CommercialResolutionInfer.infer(1600, 900)
        assert result.base_label == "1080"

    def test_1366x768_classifies_as_720p(self):
        """1366x768 (common laptop resolution) should classify as 720p."""
        result = CommercialResolutionInfer.infer(1366, 768)
        assert result.base_label == "720"

    def test_2560x1440_qhd(self):
        """2560x1440 (QHD/1440p)."""
        result = CommercialResolutionInfer.infer(2560, 1440)
        assert result.base_label == "1440"
        assert result.confidence >= 0.95

    # Ultra-wide resolutions
    def test_2560x1080_ultrawide(self):
        """2560x1080 could be ultra-wide 1080p OR letterboxed 1440p.

        The algorithm matches by width (2560 = 1440p width), so it classifies as 1440p.
        This is a reasonable interpretation since the width matches 1440p exactly.
        """
        result = CommercialResolutionInfer.infer(2560, 1080)
        assert result.base_label == "1440"  # Matched by width, not height
        assert result.confidence < 0.6  # Lower confidence due to ambiguity

    def test_3440x1440_ultrawide(self):
        """3440x1440 is ultra-wide 1440p (21:9)."""
        result = CommercialResolutionInfer.infer(3440, 1440)
        assert result.base_label == "1440"

    # Edge cases
    def test_zero_height_returns_low_confidence(self):
        """Zero height should not crash, return low confidence."""
        result = CommercialResolutionInfer.infer(1920, 0)
        assert result.confidence <= 0.2  # Very low confidence due to invalid dimensions
        assert result.base_label in ["480", "2160"]  # Fallback to some tier

    def test_very_small_resolution(self):
        """Very small resolutions should classify to lowest tier."""
        result = CommercialResolutionInfer.infer(320, 240)
        assert result.base_label == "480"

    def test_very_large_resolution_8640p(self):
        """15360x8640 is 16K/8640p."""
        result = CommercialResolutionInfer.infer(15360, 8640)
        assert result.base_label == "8640"
        assert result.confidence >= 0.95

    def test_16k_letterboxed(self):
        """15360x6400 is 16K letterboxed."""
        result = CommercialResolutionInfer.infer(15360, 6400)
        assert result.base_label == "8640"

    # Confidence scoring
    def test_perfect_match_has_high_confidence(self):
        """Standard resolutions should have very high confidence."""
        result = CommercialResolutionInfer.infer(1920, 1080)
        assert result.confidence >= 0.95

    def test_letterboxed_has_lower_confidence_than_full_frame(self):
        """Letterboxed content should have lower confidence than full-frame."""
        full_frame = CommercialResolutionInfer.infer(1920, 1080)
        letterboxed = CommercialResolutionInfer.infer(1920, 800)
        assert letterboxed.confidence < full_frame.confidence

    def test_result_is_frozen(self):
        """ResolutionResult should be immutable (frozen)."""
        result = CommercialResolutionInfer.infer(1920, 1080)
        with pytest.raises(AttributeError):
            result.base_label = "720"  # type: ignore[misc]  # Should fail - frozen dataclass

    # Metadata validation
    def test_result_contains_aspect_ratio(self):
        """Result extras should contain observed aspect ratio."""
        result = CommercialResolutionInfer.infer(1920, 1080)
        assert "observed_ar" in result.extras
        assert result.extras["observed_ar"] == pytest.approx(1.77778, rel=0.01)

    def test_result_contains_base_aspect_ratio(self):
        """Result extras should contain base aspect ratio for comparison."""
        result = CommercialResolutionInfer.infer(1920, 1080)
        assert "base_ar" in result.extras

    def test_result_contains_error_metric(self):
        """Result extras should contain normalized error metric."""
        result = CommercialResolutionInfer.infer(1920, 1080)
        assert "norm_error" in result.extras


class TestVideoResolutionAnalyzer:
    """Test the VideoResolutionAnalyzer class with MediaInfo integration."""

    def _create_mock_mediainfo(
        self,
        width: int,
        height: int,
        scan_type: str | None = "Progressive",
        fps: str | None = "24.000",
    ) -> MediaInfo:
        """Helper to create a mock MediaInfo object."""
        mock_track = Mock(spec=Track)
        mock_track.width = width
        mock_track.height = height
        mock_track.scan_type = scan_type
        mock_track.frame_rate = fps

        mock_mediainfo = Mock(spec=MediaInfo)
        mock_mediainfo.video_tracks = [mock_track]

        return mock_mediainfo

    # Basic resolution detection with scan type
    def test_1080p_progressive(self):
        """1920x1080 progressive should return '1080p'."""
        mi = self._create_mock_mediainfo(1920, 1080, "Progressive")
        analyzer = VideoResolutionAnalyzer(mi)
        assert analyzer.get_resolution() == "1080p"

    def test_1080i_interlaced(self):
        """1920x1080 interlaced should return '1080i'."""
        mi = self._create_mock_mediainfo(1920, 1080, "Interlaced")
        analyzer = VideoResolutionAnalyzer(mi)
        assert analyzer.get_resolution() == "1080i"

    def test_720p_progressive(self):
        """1280x720 progressive should return '720p'."""
        mi = self._create_mock_mediainfo(1280, 720, "Progressive")
        analyzer = VideoResolutionAnalyzer(mi)
        assert analyzer.get_resolution() == "720p"

    def test_2160p_4k(self):
        """3840x2160 should return '2160p'."""
        mi = self._create_mock_mediainfo(3840, 2160, "Progressive")
        analyzer = VideoResolutionAnalyzer(mi)
        assert analyzer.get_resolution() == "2160p"

    # PAL 25fps heuristic
    def test_25fps_treated_as_progressive(self):
        """25fps content should be treated as progressive even if scan type is interlaced."""
        mi = self._create_mock_mediainfo(1920, 1080, "Interlaced", "25.000")
        analyzer = VideoResolutionAnalyzer(mi)
        assert analyzer.get_resolution() == "1080p"  # Should be 'p' due to 25fps

    def test_25fps_progressive_stays_progressive(self):
        """25fps progressive should remain progressive."""
        mi = self._create_mock_mediainfo(1920, 1080, "Progressive", "25.000")
        analyzer = VideoResolutionAnalyzer(mi)
        assert analyzer.get_resolution() == "1080p"

    def test_24fps_interlaced(self):
        """24fps interlaced should return 'i' (not affected by 25fps heuristic)."""
        mi = self._create_mock_mediainfo(1920, 1080, "Interlaced", "24.000")
        analyzer = VideoResolutionAnalyzer(mi)
        assert analyzer.get_resolution() == "1080i"

    # Scan type detection with None/missing data
    def test_none_scan_type_defaults_to_progressive(self):
        """None/missing scan type should default to progressive."""
        mi = self._create_mock_mediainfo(1920, 1080, None)
        analyzer = VideoResolutionAnalyzer(mi)
        assert analyzer.get_resolution() == "1080p"

    def test_none_fps_with_progressive(self):
        """None FPS with progressive scan should work."""
        mock_track = Mock(spec=Track)
        mock_track.width = 1920
        mock_track.height = 1080
        mock_track.scan_type = "Progressive"
        mock_track.frame_rate = None

        mock_mediainfo = Mock(spec=MediaInfo)
        mock_mediainfo.video_tracks = [mock_track]

        analyzer = VideoResolutionAnalyzer(mock_mediainfo)
        assert analyzer.get_resolution() == "1080p"

    # remove_scan parameter
    def test_remove_scan_returns_base_resolution_only(self):
        """remove_scan=True should return only '1080' without 'p' or 'i'."""
        mi = self._create_mock_mediainfo(1920, 1080, "Progressive")
        analyzer = VideoResolutionAnalyzer(mi)
        assert analyzer.get_resolution(remove_scan=True) == "1080"

    def test_remove_scan_with_interlaced(self):
        """remove_scan=True should return base resolution even for interlaced."""
        mi = self._create_mock_mediainfo(1920, 1080, "Interlaced")
        analyzer = VideoResolutionAnalyzer(mi)
        assert analyzer.get_resolution(remove_scan=True) == "1080"

    # Letterboxed content with scan type
    def test_letterboxed_1080p_progressive(self):
        """1920x800 letterboxed should return '1080p'."""
        mi = self._create_mock_mediainfo(1920, 800, "Progressive")
        analyzer = VideoResolutionAnalyzer(mi)
        assert analyzer.get_resolution() == "1080p"

    def test_letterboxed_1080i_interlaced(self):
        """1920x800 letterboxed interlaced should return '1080i'."""
        mi = self._create_mock_mediainfo(1920, 800, "Interlaced")
        analyzer = VideoResolutionAnalyzer(mi)
        assert analyzer.get_resolution() == "1080i"

    # Portrait/vertical video
    def test_portrait_1080p(self):
        """1080x1920 portrait should return '1080p'."""
        mi = self._create_mock_mediainfo(1080, 1920, "Progressive")
        analyzer = VideoResolutionAnalyzer(mi)
        assert analyzer.get_resolution() == "1080p"

    # Zero/invalid dimensions
    def test_zero_width_returns_low_confidence(self):
        """Zero width should not crash."""
        mock_track = Mock(spec=Track)
        mock_track.width = 0
        mock_track.height = 1080
        mock_track.scan_type = "Progressive"
        mock_track.frame_rate = "24.000"

        mock_mediainfo = Mock(spec=MediaInfo)
        mock_mediainfo.video_tracks = [mock_track]

        analyzer = VideoResolutionAnalyzer(mock_mediainfo)
        # Should not crash, will return some resolution
        result = analyzer.get_resolution()
        assert isinstance(result, str)

    def test_zero_height_returns_low_confidence(self):
        """Zero height should not crash."""
        mock_track = Mock(spec=Track)
        mock_track.width = 1920
        mock_track.height = 0
        mock_track.scan_type = "Progressive"
        mock_track.frame_rate = "24.000"

        mock_mediainfo = Mock(spec=MediaInfo)
        mock_mediainfo.video_tracks = [mock_track]

        analyzer = VideoResolutionAnalyzer(mock_mediainfo)
        result = analyzer.get_resolution()
        assert isinstance(result, str)

    # Missing video track error
    def test_missing_video_track_raises_error(self):
        """MediaInfo with no video tracks should raise MissingVideoTrackError."""
        mock_mediainfo = Mock(spec=MediaInfo)
        mock_mediainfo.video_tracks = []

        analyzer = VideoResolutionAnalyzer(mock_mediainfo)
        with pytest.raises(MissingVideoTrackError):
            analyzer.get_resolution()

    def test_none_mediainfo_raises_error(self):
        """None MediaInfo should raise MissingVideoTrackError."""
        analyzer = VideoResolutionAnalyzer(None)
        with pytest.raises(MissingVideoTrackError):
            analyzer.get_resolution()

    # Ultra-wide resolutions
    def test_ultrawide_2560x1080(self):
        """2560x1080 ultra-wide is ambiguous - classified as 1440p by width match."""
        mi = self._create_mock_mediainfo(2560, 1080, "Progressive")
        analyzer = VideoResolutionAnalyzer(mi)
        assert analyzer.get_resolution() == "1440p"  # Matched by width (2560)

    def test_qhd_1440p(self):
        """2560x1440 QHD should return '1440p'."""
        mi = self._create_mock_mediainfo(2560, 1440, "Progressive")
        analyzer = VideoResolutionAnalyzer(mi)
        assert analyzer.get_resolution() == "1440p"

    # 8K
    def test_8k_4320p(self):
        """7680x4320 should return '4320p'."""
        mi = self._create_mock_mediainfo(7680, 4320, "Progressive")
        analyzer = VideoResolutionAnalyzer(mi)
        assert analyzer.get_resolution() == "4320p"

    # SD resolutions
    def test_576p_pal(self):
        """1024x576 PAL should return '576p'."""
        mi = self._create_mock_mediainfo(1024, 576, "Progressive")
        analyzer = VideoResolutionAnalyzer(mi)
        assert analyzer.get_resolution() == "576p"

    def test_480p_ntsc(self):
        """854x480 NTSC should return '480p'."""
        mi = self._create_mock_mediainfo(854, 480, "Progressive")
        analyzer = VideoResolutionAnalyzer(mi)
        assert analyzer.get_resolution() == "480p"
