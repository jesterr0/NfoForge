from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from pymediainfo import MediaInfo, Track

from src.exceptions import MissingVideoTrackError
from src.logger.nfo_forge_logger import LOG


@dataclass(slots=True, frozen=True)
class ResolutionResult:
    """
    Result of commercial resolution classification.

    Attributes:
        width: Actual video width in pixels
        height: Actual video height in pixels
        base_label: Resolution tier without scan type (e.g., "1080", "720")
        base_height: Standard height for this tier (e.g., 1080 for 1080p)
        confidence: Classification confidence from 0.0 to 1.0
        notes: Human-readable description of the match
        extras: Additional metadata (aspect ratios, error metrics, etc.)
    """
    
    width: int
    height: int
    base_label: str
    base_height: int
    confidence: float
    notes: str
    extras: dict[str, Any] = field(default_factory=dict)


class CommercialResolutionInfer:
    """
    Classify arbitrary pixel dimensions into standard commercial resolution tiers:
        480p, 576p, 720p, 1080p, 1440p, 2160p, 4320p, 8640p

    Handles multiple aspect ratios and orientations:
    - 16:9 widescreen (1920x1080, 1280x720, etc.)
    - 4:3 classic TV/Academy ratio (960x720, 640x480, etc.)
    - 2.39:1 / 2.35:1 cinemascope (letterboxed)
    - 21:9 ultra-wide
    - Portrait/vertical video

    Returns the base resolution tier and confidence score (0.0-1.0).
    """

    # Standard base tiers: (label, base_height, canonical width)
    # Includes both 16:9 (widescreen) and 4:3 (classic/academy) variants
    BASES: list[tuple[str, int, int]] = [
        ("480", 480, 854),    # 16:9 SD
        ("480", 480, 640),    # 4:3 SD
        ("576", 576, 1024),   # 16:9 PAL
        ("576", 576, 768),    # 4:3 PAL
        ("720", 720, 1280),   # 16:9 HD
        ("720", 720, 960),    # 4:3 HD (pillarboxed from 1080p)
        ("1080", 1080, 1920), # 16:9 Full HD
        ("1080", 1080, 1440), # 4:3 Full HD (pillarboxed)
        ("1440", 1440, 2560), # 16:9 QHD
        ("1440", 1440, 1920), # 4:3 QHD (pillarboxed)
        ("2160", 2160, 3840), # 16:9 4K/UHD
        ("2160", 2160, 2880), # 4:3 4K (pillarboxed)
        ("4320", 4320, 7680), # 16:9 8K
        ("4320", 4320, 5760), # 4:3 8K (pillarboxed)
        ("8640", 8640, 15360),# 16:9 16K
        ("8640", 8640, 11520),# 4:3 16K (pillarboxed)
    ]

    # Tolerances
    ABS_TOL = 8  # px slack for rounding errors
    REL_TOL = 0.03  # 3% relative tolerance
    MIN_CROP_FRAC = 0.55  # accept cropped width/height down to 55% of expected

    @classmethod
    def infer(cls, width: int, height: int) -> ResolutionResult:
        """
        Infer commercial resolution from pixel dimensions.

        Tries both (w,h) and swapped (h,w) to handle portrait videos,
        returning whichever has higher confidence.

        Args:
            width: Video width in pixels
            height: Video height in pixels

        Returns:
            ResolutionResult with classification and confidence
        """
        cand1 = cls._infer_one(width, height)
        cand2 = cls._infer_one(height, width)
        return cand1 if cand1.confidence >= cand2.confidence else cand2

    @classmethod
    def _infer_one(cls, w: int, h: int) -> ResolutionResult:
        """Internal: classify a single orientation (w,h)."""
        if h == 0:
            # Prevent division by zero
            return ResolutionResult(
                width=w,
                height=h,
                base_label="480",
                base_height=480,
                confidence=0.0,
                notes="Invalid dimensions (height=0)",
                extras={},
            )

        best = None
        best_err = float("inf")

        for label, bh, bw in cls.BASES:
            base_ar = bw / bh
            obs_ar = w / h

            # tolerance helpers
            def tol(b):
                return max(cls.ABS_TOL, cls.REL_TOL * b)

            # measure relative differences
            dw = abs(w - bw) / bw if bw > 0 else float("inf")
            dh = abs(h - bh) / bh if bh > 0 else float("inf")
            ar_err = abs(obs_ar - base_ar) / base_ar if base_ar > 0 else float("inf")

            # Three hypotheses: full-frame, cropped height (letterbox), cropped width (pillarbox)
            err_full = (dw + dh) / 2 + 0.25 * ar_err

            err_crop_h = None
            if w >= cls.MIN_CROP_FRAC * bw and h <= bh + tol(bh):
                deficit = max(0.0, (bh - h) / bh) if bh > 0 else 0.0
                err_crop_h = (abs(w - bw) / bw if bw > 0 else 0.0) + 0.5 * deficit + 0.25 * ar_err

            err_crop_w = None
            if h >= cls.MIN_CROP_FRAC * bh and w <= bw + tol(bw):
                deficit = max(0.0, (bw - w) / bw) if bw > 0 else 0.0
                err_crop_w = (abs(h - bh) / bh if bh > 0 else 0.0) + 0.5 * deficit + 0.25 * ar_err

            for err in (err_full, err_crop_h, err_crop_w):
                if err is None:
                    continue
                if err < best_err:
                    best_err = err
                    best = ResolutionResult(
                        width=w,
                        height=h,
                        base_label=label,
                        base_height=bh,
                        confidence=cls._err_to_conf(err),
                        notes=f"Matched to {label}p (base {bw}x{bh})",
                        extras={
                            "observed_ar": round(obs_ar, 5),
                            "base_ar": round(base_ar, 5),
                            "norm_error": round(err, 5),
                        },
                    )

                    # Early termination for excellent matches
                    if err < 0.01:
                        return best

        # Fallback if no match found (shouldn't happen)
        if best is None:
            label, bh, bw = min(cls.BASES, key=lambda b: abs(h - b[1]))
            best = ResolutionResult(
                width=w,
                height=h,
                base_label=label,
                base_height=bh,
                confidence=0.3,
                notes="Fallback by nearest base height",
                extras={"observed_ar": round(w / h, 5), "base_ar": round(bw / bh, 5)},
            )

        return best

    @staticmethod
    def _err_to_conf(err: float) -> float:
        """Map normalized error to confidence 0..1."""
        err = max(0.0, err)
        conf = 1.0 / (1.0 + 10.0 * err)
        return round(max(0.0, min(1.0, conf)), 3)


class VideoResolutionAnalyzer:

    def __init__(self, media_info_obj: Optional[MediaInfo]):
        self.media_info_obj = media_info_obj

    def get_resolution(self, remove_scan: bool = False) -> str:
        """
        Detect video resolution from MediaInfo data.

        Args:
            remove_scan: If True, returns only resolution tier (e.g., "1080").
                        If False, includes scan type (e.g., "1080p" or "1080i").

        Returns:
            Resolution string like "1080p", "720p", "2160p", etc.

        Raises:
            MissingVideoTrackError: If the media file has no video track
        """
        video_track = self._get_video_track()
        width = self._get_width(video_track)
        height = self._get_height(video_track)

        # Use new algorithm for dimension classification
        result = CommercialResolutionInfer.infer(width, height)

        # Log confidence and details
        LOG.debug(
            LOG.LOG_SOURCE.BE,
            f"Resolution detection: {width}x{height} → {result.base_label}p "
            f"(confidence: {result.confidence}, AR: {result.extras.get('observed_ar', 'N/A')})"
        )

        # Warn on low confidence matches
        if result.confidence < 0.6:
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                f"Low confidence resolution detection for {width}x{height}: {result.notes}"
            )

        # Return just the base resolution if scan type not needed
        if remove_scan:
            return result.base_label

        # Determine scan type and append
        scan_type = self._determine_scan_type(video_track)
        return f"{result.base_label}{scan_type}"

    def _determine_scan_type(self, track: Track) -> str:
        """
        Determine if video is progressive (p) or interlaced (i).

        Args:
            track: MediaInfo video track

        Returns:
            "p" for progressive, "i" for interlaced
        """
        fps = self._get_fps(track)
        scan = self._get_scan(track)

        # Default to progressive if unknown
        scan = "Progressive" if scan is None else scan

        # Progressive if explicitly marked, or if 25fps (PAL progressive)
        return "p" if scan == "Progressive" or (fps and fps == "25.000") else "i"

    @staticmethod
    def _get_width(track: Track) -> int:
        if not track.width or track.width == 0:
            LOG.warning(LOG.LOG_SOURCE.BE, "Failed to determine video width")
            return 0
        return track.width

    @staticmethod
    def _get_height(track: Track) -> int:
        if not track.height or track.height == 0:
            LOG.warning(LOG.LOG_SOURCE.BE, "Failed to determine video height")
            return 0
        return track.height

    @staticmethod
    def _get_fps(track: Track) -> Optional[str]:
        if not track.frame_rate:
            LOG.warning(LOG.LOG_SOURCE.BE, "Failed to determine video frame rate")
        return track.frame_rate

    @staticmethod
    def _get_scan(track: Track) -> Optional[str]:
        if not track.scan_type:
            LOG.debug(
                LOG.LOG_SOURCE.BE,
                "Video file contains no scan type, assuming Progressive",
            )
        return track.scan_type

    def _get_video_track(self) -> Track:
        """
        Extract the first video track from MediaInfo.

        Returns:
            First video track from the media file

        Raises:
            MissingVideoTrackError: If no video track exists
        """
        if self.media_info_obj and self.media_info_obj.video_tracks:
            return self.media_info_obj.video_tracks[0]
        else:
            error = "Input has no video track"
            LOG.critical(LOG.LOG_SOURCE.BE, error)
            raise MissingVideoTrackError(error)
