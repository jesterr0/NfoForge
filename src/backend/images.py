import platform
import random
import re
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

import oslex2
from pymediainfo import MediaInfo
from PySide6.QtCore import SignalInstance

from src.backend.utils.images import (
    compare_res,
    compare_resolutions,
    create_directories,
    determine_ffmpeg_trimmed_frames,
    ffmpeg_crop_to_crop_values,
    generate_progress,
    get_ffmpeg_tone_map_str,
    get_frame_rate,
    get_total_frames,
    vapoursynth_to_ffmpeg_crop,
)
from src.backend.utils.working_dir import RUNTIME_DIR
from src.enums.cropping import Cropping
from src.enums.image_plugin import ImagePlugin
from src.enums.indexer import Indexer
from src.enums.subtitles import SubtitleAlignment
from src.logger.nfo_forge_logger import LOG
from src.packages.crop_detect import CropDetect
from src.packages.custom_types import AdvancedResize, CropValues, SubNames


class ImageGeneration(ABC):
    @abstractmethod
    def generate_images(self, **kwargs):
        raise NotImplementedError()

    def run_ffmpeg_command(
        self, command: list[str], total_images: int, signal: "SignalInstance"
    ) -> int:
        try:
            LOG.debug(
                LOG.LOG_SOURCE.BE, f"FFMPEG command: {' '.join(map(str, command))}"
            )

            with subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW
                | subprocess.CREATE_NEW_PROCESS_GROUP
                if platform.system() == "Windows"
                else 0,
            ) as job:
                stdout_lines = []

                if job.stdout:
                    for line in job.stdout:
                        line = re.sub(r"\s{2,}", "", line).rstrip()
                        stdout_lines.append(line)
                        if "frame=" in line:
                            LOG.debug(LOG.LOG_SOURCE.BE, line)
                            progress = generate_progress(line, total_images)
                            if progress:
                                signal.emit(line, progress)

                if job.stdout:
                    job.stdout.close()

                job.wait()
                return_code = job.returncode
                LOG.info(LOG.LOG_SOURCE.BE, f"FFMPEG return code: {return_code}")

                if return_code != 0:
                    error_message = "\n".join(stdout_lines)
                    LOG.error(LOG.LOG_SOURCE.BE, f"FFMPEG error: {error_message}")

                return return_code
        except Exception as e:
            LOG.error(LOG.LOG_SOURCE.BE, f"Error while running FFMPEG command ({e}).")
            return 1

    def run_frame_forge_command(self, command: list, signal: SignalInstance) -> int:
        completed = False
        progress = 0
        LOG.debug(LOG.LOG_SOURCE.BE, f"FrameForge command: {' '.join(command)}")
        with subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW
            | subprocess.CREATE_NEW_PROCESS_GROUP
            if platform.system() == "Windows"
            else 0,
            bufsize=1,
            text=True,
        ) as job:
            if job and job.stdout:
                for img_progress in job.stdout:
                    LOG.info(LOG.LOG_SOURCE.BE, img_progress)
                    if "Source index complete" in img_progress:
                        progress += 15
                    elif "Encode index completed" in img_progress:
                        progress += 15
                    elif "No de-interlacing detected" in img_progress:
                        progress += 15
                    elif "Finished generating 12 'B' frames" in img_progress:
                        progress += 15
                    elif "Folder creation completed" in img_progress:
                        progress += 15
                    elif "Generating a few sync frames" in img_progress:
                        progress += 15
                    elif "Output:" in img_progress:
                        completed = True
                        progress = 100
                    signal.emit(img_progress.replace("\n", ""), progress)

                job.stdout.close()
                job.wait()
                LOG.info(LOG.LOG_SOURCE.BE, f"FrameForge return code: {job.returncode}")
                if completed and job.returncode == 0:
                    return job.returncode
        return 1


class BasicImageGeneration(ImageGeneration):
    def generate_images(self, **kwargs):
        return self.basic_image_generation(**kwargs)

    def basic_image_generation(
        self,
        media_input: Path,
        output_directory: Path,
        mi_object: MediaInfo,
        total_images: int,
        trim: tuple[int, int],
        ffmpeg_path: Path,
        signal: SignalInstance,
    ) -> int:
        """Basic image generation using direct seeks for optimal performance."""

        img_comparison = create_directories(output_directory)[0]
        output_pattern = str(img_comparison / "%02d_output.png")

        total_frames = get_total_frames(mi_object)
        frame_rate = get_frame_rate(mi_object)

        available_frames, start_time_str = determine_ffmpeg_trimmed_frames(
            trim=trim, total_frames=total_frames, frame_rate=frame_rate
        )

        # convert start time to seconds (start_time_str is already in seconds as a string)
        start_seconds = float(start_time_str)

        # calculate the duration we're working with
        duration_seconds = available_frames / frame_rate

        # add random offset
        rand_offset = random.randint(0, int(frame_rate) * 10)
        random_time_offset = rand_offset / frame_rate

        # calculate timestamps for each frame we want
        timestamps = []
        for i in range(total_images):
            # distribute frames evenly across the available duration
            progress = i / max(1, total_images - 1) if total_images > 1 else 0
            offset_seconds = (
                start_seconds + (progress * duration_seconds) + random_time_offset
            )

            # format back to HH:MM:SS.mmm
            hours = int(offset_seconds // 3600)
            minutes = int((offset_seconds % 3600) // 60)
            seconds = offset_seconds % 60
            timestamp = f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"
            timestamps.append(timestamp)

        # build filter chain
        filters = []

        # HDR tone mapping if needed
        if mi_object.video_tracks[0].other_hdr_format:
            tone_map_str = get_ffmpeg_tone_map_str()
            if tone_map_str:
                filters.append(tone_map_str.lstrip(","))

        vf_filter = ",".join(filters) if filters else "copy"

        # extract each frame individually using seeks
        success_count = 0
        for i, timestamp in enumerate(timestamps):
            output_file = output_pattern.replace("%02d", f"{i + 1:02d}")

            command = [
                str(ffmpeg_path),
                "-ss",
                timestamp,
                "-i",
                str(media_input),
                "-vf",
                vf_filter,
                "-frames:v",
                "1",
                "-compression_level",
                "6",
                "-an",
                "-y",
                output_file,
                "-v",
                "error",
                "-hide_banner",
            ]

            # run the command
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW
                    if platform.system() == "Windows"
                    else 0,
                )

                if result.returncode == 0:
                    success_count += 1
                    # emit progress
                    progress = (i + 1) / total_images * 100
                    signal.emit(f"Extracted frame {i + 1}/{total_images}", progress)
                else:
                    LOG.error(
                        LOG.LOG_SOURCE.BE,
                        f"Failed to extract frame at {timestamp}: {result.stderr}",
                    )

            except subprocess.TimeoutExpired:
                LOG.error(LOG.LOG_SOURCE.BE, f"Timeout extracting frame at {timestamp}")
            except Exception as e:
                LOG.error(
                    LOG.LOG_SOURCE.BE, f"Error extracting frame at {timestamp}: {e}"
                )

        return 0 if success_count == total_images else 1


class ComparisonImageGeneration(ImageGeneration):
    def generate_images(self, **kwargs):
        return self.comparison_image_generation(**kwargs)

    def comparison_image_generation(
        self,
        source_input: Path,
        source_file_mi_obj: MediaInfo,
        media_input: Path,
        media_file_mi_obj: MediaInfo,
        output_directory: Path,
        total_images: int,
        trim: tuple[int, int],
        subtitle_color: str,
        subtitle_outline_color: str,
        sub_names: SubNames | None,
        sub_size: int,
        crop_mode: Cropping,
        crop_values: CropValues | None,
        ffmpeg_path: Path,
        signal: SignalInstance,
        re_sync: int = 0,
    ) -> int:
        directories = create_directories(output_directory, sync_dir=True)
        img_comparison = directories[0]
        img_sync = directories[2] if len(directories) == 3 else None

        enc_output = str(img_comparison / "%02db_encode.png")
        src_output = str(img_comparison / "%02da_source.png")

        source_width, source_height = (
            source_file_mi_obj.video_tracks[0].width,
            source_file_mi_obj.video_tracks[0].height,
        )

        media_width, media_height = (
            media_file_mi_obj.video_tracks[0].width,
            media_file_mi_obj.video_tracks[0].height,
        )

        detect_crop = ""
        if crop_values and crop_mode != Cropping.DISABLED:
            user_crop_msg = (
                "Applying user defined crops "
                f"({', '.join(f'{field}={value}' for field, value in zip(crop_values._fields, crop_values))})."
            )
            LOG.info(LOG.LOG_SOURCE.BE, user_crop_msg)
            signal.emit(user_crop_msg, 0)
            detect_crop = vapoursynth_to_ffmpeg_crop(
                crop_values, source_width, source_height
            )
        elif not crop_values and crop_mode == Cropping.AUTO:
            if not compare_resolutions(media_file_mi_obj, source_file_mi_obj):
                auto_crop_detect_msg = "Automatically detecting crop, please wait."
                LOG.info(LOG.LOG_SOURCE.BE, auto_crop_detect_msg)
                signal.emit(
                    auto_crop_detect_msg,
                    0,
                )
                detect_crop = CropDetect(ffmpeg_path, source_input, 15, 4).get_result()
                crop_detection_complete_msg = (
                    f"Crop detection complete ({detect_crop})."
                )
                LOG.info(LOG.LOG_SOURCE.BE, crop_detection_complete_msg)
                signal.emit(crop_detection_complete_msg, 0)

                if not detect_crop:
                    raise ValueError(f"Couldn't detect crop ({detect_crop})")

                split_crop = detect_crop.split("=")[1].split(":")
                detected_width = int(split_crop[0])
                detected_height = int(split_crop[1])
                if not compare_res(
                    detected_width, detected_height, media_width, media_height
                ):
                    crop_miss_match_msg = (
                        "Crop detection found different aspect ratio, "
                        "will crop and scale to match encode resolution."
                    )
                    LOG.info(LOG.LOG_SOURCE.BE, crop_miss_match_msg)
                    signal.emit(
                        crop_miss_match_msg,
                        0,
                    )
                    # keep the original crop (which removes letter boxing) and let the scaling handle the resize
                    detect_crop_msg = (
                        "Crop detection will use original crop and scale to encode resolution."
                        f"(crop={detected_width}:{detected_height}:{split_crop[2]}:{split_crop[3]} "
                        f"+ scale to {media_width}x{media_height})."
                    )
                    LOG.info(LOG.LOG_SOURCE.BE, detect_crop_msg)
                    signal.emit(detect_crop_msg, 0)

        generate_enc_img_msg = "\nGenerating encode images."
        LOG.info(LOG.LOG_SOURCE.BE, generate_enc_img_msg)
        signal.emit(generate_enc_img_msg, 0)

        frame_rate = get_frame_rate(media_file_mi_obj)
        random_offset = random.randint(0, (int(frame_rate) * 10))

        # convert re_sync frames to seconds (positive value means source is ahead, so we delay source)
        # this matches FrameForge behavior where positive re_sync delays the source
        source_re_sync_offset = re_sync / frame_rate if re_sync != 0 else 0.0

        if source_re_sync_offset != 0:
            re_sync_msg = (
                f"Applying re-sync offset: {re_sync} frames "
                f"({source_re_sync_offset:.3f} seconds) to source."
            )
            LOG.info(LOG.LOG_SOURCE.BE, re_sync_msg)
            signal.emit(re_sync_msg, 0)

        generate_encode_images = self.generate_comp_frames(
            input_video=media_input,
            output_pattern=enc_output,
            text_overlay=sub_names.encode if sub_names else None,
            sub_size=sub_size,
            mi_object=media_file_mi_obj,
            total_images=total_images,
            trim=trim,
            random_offset=random_offset,
            frame_rate=frame_rate,
            subtitle_color=subtitle_color,
            subtitle_outline_color=subtitle_outline_color,
            ffmpeg=ffmpeg_path,
            signal=signal,
        )

        generate_src_img_msg = "\nGenerating source images."
        LOG.info(LOG.LOG_SOURCE.BE, generate_src_img_msg)
        signal.emit(generate_src_img_msg, 0)
        generate_source_images = self.generate_comp_frames(
            input_video=source_input,
            output_pattern=src_output,
            text_overlay=sub_names.source if sub_names else None,
            sub_size=sub_size,
            mi_object=source_file_mi_obj,
            total_images=total_images,
            trim=trim,
            random_offset=random_offset,
            frame_rate=frame_rate,
            subtitle_color=subtitle_color,
            subtitle_outline_color=subtitle_outline_color,
            ffmpeg=ffmpeg_path,
            signal=signal,
            ffmpeg_crop=detect_crop,
            width=media_width,
            height=media_height,
            re_sync_offset_seconds=source_re_sync_offset,
        )

        # generate sync frames similar to FrameForge
        if img_sync:
            self.generate_sync_frames(
                source_input=source_input,
                media_input=media_input,
                media_file_mi_obj=media_file_mi_obj,
                img_sync=img_sync,
                total_images=total_images,
                trim=trim,
                random_offset=random_offset,
                frame_rate=frame_rate,
                subtitle_color=subtitle_color,
                subtitle_outline_color=subtitle_outline_color,
                sub_size=sub_size,
                ffmpeg_path=ffmpeg_path,
                signal=signal,
                ffmpeg_crop=detect_crop,
                width=media_width,
                height=media_height,
                source_re_sync_offset=source_re_sync_offset,
            )

        if generate_encode_images != 0 and generate_source_images != 0:
            return 1
        else:
            return 0

    def generate_comp_frames(
        self,
        input_video,
        output_pattern,
        text_overlay: str | None,
        sub_size: int,
        mi_object: MediaInfo,
        total_images: int,
        trim: tuple[int, int],
        random_offset: int,
        frame_rate: float,
        subtitle_color: str,
        subtitle_outline_color: str,
        ffmpeg: Path,
        signal: SignalInstance,
        ffmpeg_crop: str | None = None,
        width: int | None = None,
        height: int | None = None,
        re_sync_offset_seconds: float = 0.0,
    ) -> int:
        """Frame generation using direct seeks for optimal performance."""

        total_frames = get_total_frames(mi_object)
        available_frames, start_time_str = determine_ffmpeg_trimmed_frames(
            trim=trim, total_frames=total_frames, frame_rate=frame_rate
        )

        # convert start time to seconds (start_time_str is already in seconds as a string)
        start_seconds = float(start_time_str)

        # calculate the duration we're working with
        duration_seconds = available_frames / frame_rate

        # calculate timestamps for each frame we want
        timestamps = []
        for i in range(total_images):
            # distribute frames evenly across the available duration
            progress = i / max(1, total_images - 1) if total_images > 1 else 0
            offset_seconds = start_seconds + (progress * duration_seconds)

            # add random offset (convert from frame offset to time offset)
            random_time_offset = random_offset / frame_rate
            offset_seconds += random_time_offset

            # apply re-sync offset
            offset_seconds += re_sync_offset_seconds

            # ensure we don't go negative
            offset_seconds = max(0, offset_seconds)

            # format back to HH:MM:SS.mmm
            hours = int(offset_seconds // 3600)
            minutes = int((offset_seconds % 3600) // 60)
            seconds = offset_seconds % 60
            timestamp = f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"
            timestamps.append(timestamp)

        # build filter chain for processing
        filters = []

        # HDR tone mapping if needed
        if mi_object.video_tracks[0].other_hdr_format:
            tone_map_str = get_ffmpeg_tone_map_str()
            if tone_map_str:
                filters.append(tone_map_str.lstrip(","))

        # crop and resize - crop first, then resize
        if ffmpeg_crop:
            # remove leading comma if present, since we're building a list
            crop_filter = ffmpeg_crop.lstrip(",")
            filters.append(crop_filter)

        if width and height:
            filters.append(f"scale={width}:{height}")

        # subtitle
        if text_overlay and self.check_draw_text(ffmpeg):
            font_path = (
                Path(RUNTIME_DIR / "fonts" / "Montserrat-Medium.ttf")
                .as_posix()
                .replace(":", r"\:")
            )
            quoted_font_path = oslex2.quote(font_path)
            quoted_text_overlay = oslex2.quote(text_overlay)
            quoted_subtitle_color = oslex2.quote(subtitle_color)
            quoted_subtitle_outline_color = oslex2.quote(subtitle_outline_color)

            subtitle_filter = (
                f"drawtext=fontfile={quoted_font_path}:"
                f"text={quoted_text_overlay}:"
                f"x=10:y=10:fontsize={sub_size}:fontcolor={quoted_subtitle_color}:"
                f"borderw=1:bordercolor={quoted_subtitle_outline_color}"
            )
            filters.append(subtitle_filter)

        vf_filter = ",".join(filters) if filters else "copy"

        # debug logging
        LOG.debug(LOG.LOG_SOURCE.BE, f"Filter chain: {vf_filter}")
        LOG.debug(
            LOG.LOG_SOURCE.BE,
            f"Crop: {ffmpeg_crop}, Resize: {width}x{height} if provided",
        )
        if re_sync_offset_seconds != 0.0:
            LOG.debug(
                LOG.LOG_SOURCE.BE,
                f"Applying re-sync offset: {re_sync_offset_seconds:.3f} seconds",
            )

        # extract each frame individually using seeks
        success_count = 0
        for i, timestamp in enumerate(timestamps):
            # handle different output pattern formats
            if "%02d" in output_pattern:
                output_file = output_pattern.replace("%02d", f"{i + 1:02d}")
            elif "%03d" in output_pattern:
                output_file = output_pattern.replace("%03d", f"{i + 1:03d}")
            else:
                # fallback: add frame number before extension
                path_obj = Path(output_pattern)
                output_file = str(
                    path_obj.parent / f"{path_obj.stem}_{i + 1:02d}{path_obj.suffix}"
                )

            command = [
                str(ffmpeg),
                "-ss",
                timestamp,
                "-i",
                str(input_video),
                "-vf",
                vf_filter,
                "-frames:v",
                "1",
                "-compression_level",
                "6",
                "-an",
                "-y",
                output_file,
                "-v",
                "error",
                "-hide_banner",
            ]

            # run the command
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW
                    if platform.system() == "Windows"
                    else 0,
                )

                if result.returncode == 0:
                    success_count += 1
                    # emit progress
                    progress = (i + 1) / total_images * 100
                    signal.emit(f"Extracted frame {i + 1}/{total_images}", progress)
                else:
                    LOG.error(
                        LOG.LOG_SOURCE.BE,
                        f"Failed to extract frame at {timestamp}: {result.stderr}",
                    )

            except subprocess.TimeoutExpired:
                LOG.error(LOG.LOG_SOURCE.BE, f"Timeout extracting frame at {timestamp}")
            except Exception as e:
                LOG.error(
                    LOG.LOG_SOURCE.BE, f"Error extracting frame at {timestamp}: {e}"
                )

        return 0 if success_count == total_images else 1

    @staticmethod
    def check_draw_text(ffmpeg_path: Path) -> bool:
        result = subprocess.run(
            [str(ffmpeg_path), "-filters"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if "drawtext" in result.stdout:
            return True
        else:
            return False

    def generate_sync_frames(
        self,
        source_input: Path,
        media_input: Path,
        media_file_mi_obj: MediaInfo,
        img_sync: Path,
        total_images: int,
        trim: tuple[int, int],
        random_offset: int,
        frame_rate: float,
        subtitle_color: str,
        subtitle_outline_color: str,
        sub_size: int,
        ffmpeg_path: Path,
        signal: SignalInstance,
        ffmpeg_crop: str | None = None,
        width: int | None = None,
        height: int | None = None,
        source_re_sync_offset: float = 0.0,
    ) -> None:
        """Generate sync frames similar to FrameForge for manual synchronization."""

        signal.emit("\nGenerating sync frames for manual offset adjustment", 0)
        LOG.info(
            LOG.LOG_SOURCE.BE, "Generating sync frames for manual offset adjustment"
        )

        # create sync subdirectories
        sync1_dir = img_sync / "sync1"
        sync2_dir = img_sync / "sync2"
        sync1_dir.mkdir(exist_ok=True)
        sync2_dir.mkdir(exist_ok=True)

        # calculate frames similar to the main comparison generation
        total_frames = get_total_frames(media_file_mi_obj)
        available_frames, start_time_str = determine_ffmpeg_trimmed_frames(
            trim=trim, total_frames=total_frames, frame_rate=frame_rate
        )

        start_seconds = float(start_time_str)
        duration_seconds = available_frames / frame_rate

        # generate frame list similar to main comparison
        comparison_frames = []
        for i in range(total_images):
            progress = i / max(1, total_images - 1) if total_images > 1 else 0
            offset_seconds = start_seconds + (progress * duration_seconds)
            random_time_offset = random_offset / frame_rate
            offset_seconds += random_time_offset

            # convert back to frame number for easier manipulation
            frame_number = int(offset_seconds * frame_rate)
            comparison_frames.append(frame_number)

        # select 2 random frames from the comparison frames (similar to FrameForge)
        sync_frame_1 = random.choice(comparison_frames)
        remaining_frames = [f for f in comparison_frames if f != sync_frame_1]
        sync_frame_2 = (
            random.choice(remaining_frames)
            if remaining_frames
            else sync_frame_1 + int(frame_rate * 30)
        )

        # generate reference frames (encode frames with frame number subtitle)
        self._generate_reference_frames(
            media_input=media_input,
            sync_frames=[sync_frame_1, sync_frame_2],
            img_sync=img_sync,
            frame_rate=frame_rate,
            subtitle_color=subtitle_color,
            subtitle_outline_color=subtitle_outline_color,
            sub_size=sub_size,
            ffmpeg_path=ffmpeg_path,
        )

        # generate sync ranges around each reference frame (±5 frames)
        sync_range_1 = [sync_frame_1 + i for i in range(-5, 6)]
        sync_range_2 = [sync_frame_2 + i for i in range(-5, 6)]

        # generate sync frames for sync1 directory
        self._generate_sync_range_frames(
            source_input=source_input,
            sync_frames=sync_range_1,
            output_dir=sync1_dir,
            frame_rate=frame_rate,
            subtitle_color=subtitle_color,
            subtitle_outline_color=subtitle_outline_color,
            sub_size=sub_size,
            ffmpeg_path=ffmpeg_path,
            ffmpeg_crop=ffmpeg_crop,
            width=width,
            height=height,
            source_re_sync_offset=source_re_sync_offset,
        )

        # generate sync frames for sync2 directory
        self._generate_sync_range_frames(
            source_input=source_input,
            sync_frames=sync_range_2,
            output_dir=sync2_dir,
            frame_rate=frame_rate,
            subtitle_color=subtitle_color,
            subtitle_outline_color=subtitle_outline_color,
            sub_size=sub_size,
            ffmpeg_path=ffmpeg_path,
            ffmpeg_crop=ffmpeg_crop,
            width=width,
            height=height,
            source_re_sync_offset=source_re_sync_offset,
        )

        signal.emit("Sync frame generation completed", 100)
        LOG.info(LOG.LOG_SOURCE.BE, "Sync frame generation completed")

    def _generate_reference_frames(
        self,
        media_input: Path,
        sync_frames: list[int],
        img_sync: Path,
        frame_rate: float,
        subtitle_color: str,
        subtitle_outline_color: str,
        sub_size: int,
        ffmpeg_path: Path,
    ) -> None:
        """Generate reference frames (encode frames with frame number subtitle)."""

        for i, frame_number in enumerate(sync_frames):
            # convert frame to timestamp
            timestamp_seconds = frame_number / frame_rate
            hours = int(timestamp_seconds // 3600)
            minutes = int((timestamp_seconds % 3600) // 60)
            seconds = timestamp_seconds % 60
            timestamp = f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"

            output_file = str(img_sync / f"{i + 1:02d}b_encode__{frame_number}.png")

            # build filter chain with reference subtitle
            filters = []

            # add subtitle with frame reference info
            if self.check_draw_text(ffmpeg_path):
                font_path = (
                    Path(RUNTIME_DIR / "fonts" / "Montserrat-Medium.ttf")
                    .as_posix()
                    .replace(":", r"\:")
                )
                quoted_font_path = oslex2.quote(font_path)
                text = f"Reference Frame {frame_number}"
                quoted_subtitle_color = oslex2.quote(subtitle_color)
                quoted_subtitle_outline_color = oslex2.quote(subtitle_outline_color)

                subtitle_filter = (
                    f"drawtext=fontfile={quoted_font_path}:"
                    f"text={text}:"
                    f"fontsize={sub_size + 5}:"
                    f"fontcolor={quoted_subtitle_color}:"
                    f"bordercolor={quoted_subtitle_outline_color}:"
                    f"borderw=1:x=(w-text_w)/2:y=h-text_h-10"
                )
                filters.append(subtitle_filter)

            vf_filter = ",".join(filters) if filters else "copy"

            command = [
                str(ffmpeg_path),
                "-ss",
                timestamp,
                "-i",
                str(media_input),
                "-vf",
                vf_filter,
                "-frames:v",
                "1",
                "-compression_level",
                "6",
                "-an",
                "-y",
                output_file,
                "-v",
                "error",
                "-hide_banner",
            ]

            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW
                    if platform.system() == "Windows"
                    else 0,
                )

                if result.returncode != 0:
                    LOG.error(
                        LOG.LOG_SOURCE.BE,
                        f"Failed to generate reference frame {frame_number}: {result.stderr}",
                    )

            except Exception as e:
                LOG.error(
                    LOG.LOG_SOURCE.BE,
                    f"Error generating reference frame {frame_number}: {e}",
                )

    def _generate_sync_range_frames(
        self,
        source_input: Path,
        sync_frames: list[int],
        output_dir: Path,
        frame_rate: float,
        subtitle_color: str,
        subtitle_outline_color: str,
        sub_size: int,
        ffmpeg_path: Path,
        ffmpeg_crop: str | None = None,
        width: int | None = None,
        height: int | None = None,
        source_re_sync_offset: float = 0.0,
    ) -> None:
        """Generate sync frames (source frames with frame number subtitle and offset)."""

        for i, frame_number in enumerate(sync_frames):
            # apply re-sync offset to timestamp
            timestamp_seconds = (frame_number / frame_rate) + source_re_sync_offset
            timestamp_seconds = max(0, timestamp_seconds)  # Ensure non-negative

            hours = int(timestamp_seconds // 3600)
            minutes = int((timestamp_seconds % 3600) // 60)
            seconds = timestamp_seconds % 60
            timestamp = f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"

            output_file = str(output_dir / f"{i + 1:02d}a_source__{frame_number}.png")

            # build filter chain
            filters = []

            # crop and resize - crop first, then resize
            if ffmpeg_crop:
                crop_filter = ffmpeg_crop.lstrip(",")
                filters.append(crop_filter)

            if width and height:
                filters.append(f"scale={width}:{height}")

            # add subtitle with sync frame info
            if self.check_draw_text(ffmpeg_path):
                font_path = (
                    Path(RUNTIME_DIR / "fonts" / "Montserrat-Medium.ttf")
                    .as_posix()
                    .replace(":", r"\:")
                )
                quoted_font_path = oslex2.quote(font_path)
                text = f"Sync Frame {frame_number}"
                quoted_subtitle_color = oslex2.quote(subtitle_color)
                quoted_subtitle_outline_color = oslex2.quote(subtitle_outline_color)

                subtitle_filter = (
                    f"drawtext=fontfile={quoted_font_path}:"
                    f"text={text}:"
                    f"fontsize={sub_size + 5}:"
                    f"fontcolor={quoted_subtitle_color}:"
                    f"bordercolor={quoted_subtitle_outline_color}:"
                    f"borderw=1:x=(w-text_w)/2:y=10"
                )
                filters.append(subtitle_filter)

            vf_filter = ",".join(filters) if filters else "copy"

            command = [
                str(ffmpeg_path),
                "-ss",
                timestamp,
                "-i",
                str(source_input),
                "-vf",
                vf_filter,
                "-frames:v",
                "1",
                "-compression_level",
                "6",
                "-an",
                "-y",
                output_file,
                "-v",
                "error",
                "-hide_banner",
            ]

            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW
                    if platform.system() == "Windows"
                    else 0,
                )

                if result.returncode != 0:
                    LOG.error(
                        LOG.LOG_SOURCE.BE,
                        f"Failed to generate sync frame {frame_number}: {result.stderr}",
                    )

            except Exception as e:
                LOG.error(
                    LOG.LOG_SOURCE.BE,
                    f"Error generating sync frame {frame_number}: {e}",
                )


class FrameForgeImageGeneration(ImageGeneration):
    def generate_images(self, **kwargs):
        return self.frame_forge_image_generation(**kwargs)

    # TODO: need to remove all extra args we don't need
    def frame_forge_image_generation(
        self,
        source_input: Path,
        source_file_mi_obj: MediaInfo,
        media_input: Path,
        media_file_mi_obj: MediaInfo,
        output_directory: Path,
        total_images: int,
        trim: tuple[int, int],
        subtitle_color: str,
        subtitle_outline_color: str,
        sub_names: SubNames | None,
        sub_size: int,
        subtitle_alignment: SubtitleAlignment,
        crop_mode: Cropping,
        crop_values: CropValues | None,
        advanced_resize: AdvancedResize | None,
        re_sync: int,
        indexer: Indexer,
        image_plugin: ImagePlugin,
        frame_forge_path: Path,
        ffmpeg_path: Path | None,
        signal: SignalInstance,
    ) -> int:
        generate_args = [
            str(frame_forge_path),
            "--source",
            str(source_input),
            "--encode",
            str(media_input),
        ]
        generate_args.extend(["--sub-color", subtitle_color])
        generate_args.extend(["--sub-outline-color", subtitle_outline_color])
        generate_args.extend(["--sub-size", str(sub_size)])
        generate_args.extend(["--sub-alignment", str(subtitle_alignment.value)])

        generate_args.extend(["--indexer", str(indexer)])
        generate_args.extend(["--img-lib", str(image_plugin)])

        img_comparison = create_directories(output_directory, sync_dir=True)[0]
        generate_args.extend(["--image-dir", str(img_comparison.parent)])

        # if crop values are provided manually utilize them
        if crop_values and crop_mode != Cropping.DISABLED:
            # we're using ABS to prevent negative numbers being sent to VapourSynth
            generate_args.extend(["--left-crop", str(abs(crop_values.left))])
            generate_args.extend(["--right-crop", str(abs(crop_values.right))])
            generate_args.extend(["--top-crop", str(abs(crop_values.top))])
            generate_args.extend(["--bottom-crop", str(abs(crop_values.bottom))])

        # if no manual crop values we're provided and cropping is set to AUTO
        elif not crop_values and ffmpeg_path and crop_mode == Cropping.AUTO:
            if not compare_resolutions(media_file_mi_obj, source_file_mi_obj):
                auto_crop_detect_msg = "Automatically detecting crop, please wait."
                LOG.info(LOG.LOG_SOURCE.BE, auto_crop_detect_msg)
                signal.emit(
                    auto_crop_detect_msg,
                    0,
                )
                detect_crop = CropDetect(ffmpeg_path, source_input, 15, 4).get_result()
                if detect_crop:
                    crop_detection_complete_msg = (
                        f"Crop detection complete ({detect_crop})."
                    )
                    LOG.info(LOG.LOG_SOURCE.BE, crop_detection_complete_msg)
                    signal.emit(crop_detection_complete_msg, 0)

                    split_crop = detect_crop.split("=")[1].split(":")
                    detected_width = int(split_crop[0])
                    detected_height = int(split_crop[1])

                    media_width, media_height = (
                        media_file_mi_obj.video_tracks[0].width,
                        media_file_mi_obj.video_tracks[0].height,
                    )

                    auto_crop_values = ffmpeg_crop_to_crop_values(
                        f"crop={detected_width}:{detected_height}:{split_crop[2]}:{split_crop[3]}",
                        media_width,
                        media_height,
                    )

                    if not compare_res(
                        detected_width, detected_height, media_width, media_height
                    ):
                        crop_miss_match_msg = "Crop detection correction needed for mismatched resolution."
                        LOG.info(LOG.LOG_SOURCE.BE, crop_miss_match_msg)
                        signal.emit(
                            crop_miss_match_msg,
                            0,
                        )
                        detected_width = media_width
                        detected_height = media_height
                        detect_crop_msg = (
                            "Crop detection adjustment completed."
                            f"(crop={detected_width}:{detected_height}:{split_crop[2]}:{split_crop[3]})."
                        )
                        auto_crop_values = ffmpeg_crop_to_crop_values(
                            f"crop={detected_width}:{detected_height}:{split_crop[2]}:{split_crop[3]}",
                            media_width,
                            media_height,
                        )
                        LOG.info(LOG.LOG_SOURCE.BE, detect_crop_msg)
                        signal.emit(detect_crop_msg, 0)
                    if auto_crop_values:
                        # we're using ABS to prevent negative numbers being sent to VapourSynth
                        generate_args.extend(
                            ["--left-crop", str(abs(auto_crop_values.left))]
                        )
                        generate_args.extend(
                            ["--right-crop", str(abs(auto_crop_values.right))]
                        )
                        generate_args.extend(
                            ["--top-crop", str(abs(auto_crop_values.top))]
                        )
                        generate_args.extend(
                            ["--bottom-crop", str(abs(auto_crop_values.bottom))]
                        )
                else:
                    crop_detection_failed_msg = f"Crop detection failed, could not determine crop ({detect_crop})..."
                    LOG.warning(LOG.LOG_SOURCE.BE, crop_detection_failed_msg)
                    signal.emit(crop_detection_failed_msg, 0)

        if advanced_resize:
            if advanced_resize.src_left:
                generate_args.extend(
                    ["--adv-resize-left", str(advanced_resize.src_left)]
                )
            if advanced_resize.src_top:
                generate_args.extend(["--adv-resize-top", str(advanced_resize.src_top)])
            if advanced_resize.src_width:
                generate_args.extend(
                    ["--adv-resize-right", str(advanced_resize.src_width)]
                )
            if advanced_resize.src_height:
                generate_args.extend(
                    ["--adv-resize-bottom", str(advanced_resize.src_height)]
                )

        if media_file_mi_obj.video_tracks[0].other_hdr_format:
            generate_args.extend(["--tone-map"])

        generate_args.extend(["--comparison-count", str(total_images)])

        sync_video = self._convert_re_sync(re_sync)
        if sync_video:
            generate_args.extend([f"--re-sync={sync_video[0]}{sync_video[1]}"])

        if sub_names:
            if sub_names.source:
                generate_args.extend(["--source-sub-title", sub_names.source])
            if sub_names.encode:
                generate_args.extend(["--encode-sub-title", sub_names.encode])

        # log final args
        LOG.debug(LOG.LOG_SOURCE.BE, str(generate_args))

        return self.run_frame_forge_command(generate_args, signal)

    @staticmethod
    def _convert_re_sync(re_sync: int | None) -> tuple[str, str] | None:
        if re_sync and re_sync != 0:
            re_sync_str = str(re_sync)
            if "-" in re_sync_str:
                return "-", re_sync_str.replace("-", "")
            else:
                return "", re_sync_str


class ImagesBackEnd:
    @staticmethod
    def basic_image_generation(
        media_input: Path,
        output_directory: Path,
        mi_object: MediaInfo,
        total_images: int,
        trim: tuple[int, int],
        ffmpeg_path: Path,
        signal: SignalInstance,
    ) -> int:
        """
        Generate images and emit progress signals.

        Parameters:
            media_input (Path): The input file path.
            output_directory (Path): The output directory path.
            mi_object (MediaInfo): MediaInfo object of the input file.
            total_images (int): The total number of images to generate.
            trim (tuple[int, int]): The percentage of the file to trim from start and end.
            ffmpeg_path (Path): Path to FFMPEG executable.
            signal (SignalInstance[str, float]): The signal used to emit progress updates on the frontend.

        """
        return BasicImageGeneration().generate_images(
            media_input=media_input,
            output_directory=output_directory,
            mi_object=mi_object,
            total_images=total_images,
            trim=trim,
            ffmpeg_path=ffmpeg_path,
            signal=signal,
        )

    @staticmethod
    def comparison_image_generation(
        source_input: Path,
        source_file_mi_obj: MediaInfo,
        media_input: Path,
        media_file_mi_obj: MediaInfo,
        output_directory: Path,
        total_images: int,
        trim: tuple[int, int],
        subtitle_color: str,
        subtitle_outline_color: str,
        sub_names: SubNames | None,
        sub_size: int,
        crop_mode: Cropping,
        crop_values: CropValues | None,
        ffmpeg_path: Path,
        signal: SignalInstance,
        re_sync: int = 0,
    ) -> int:
        """
        Generate comparison images and emit progress signals.

        Parameters:
            source_input (Path): The input file path.
            source_file_mi_obj (Path): MediaInfo object of the input file.
            media_input (Path): The input file path.
            media_file_mi_obj (MediaInfo): MediaInfo object of the input file.
            output_directory (Path): The output directory path.
            total_images (int): The total number of images to generate.
            trim (tuple[int, int]): The percentage of the file to trim from start and end.
            subtitle_color (str): Hex color.
            subtitle_outline_color (str): Hex color.
            sub_names (Optional[SubNames]): Subtitle names.
            sub_size (int): Subtitle size.
            crop_mode (Cropping): Crop mode.
            crop_values (Optional[CropValues]): Crop values.
            ffmpeg_path (Path): Path to FFMPEG executable.
            signal (SignalInstance[str, float]): The signal used to emit progress updates on the frontend.

        """
        return ComparisonImageGeneration().generate_images(
            source_input=source_input,
            source_file_mi_obj=source_file_mi_obj,
            media_input=media_input,
            media_file_mi_obj=media_file_mi_obj,
            output_directory=output_directory,
            total_images=total_images,
            trim=trim,
            subtitle_color=subtitle_color,
            subtitle_outline_color=subtitle_outline_color,
            sub_names=sub_names,
            sub_size=sub_size,
            crop_mode=crop_mode,
            crop_values=crop_values,
            ffmpeg_path=ffmpeg_path,
            signal=signal,
            re_sync=re_sync,
        )

    @staticmethod
    def frame_forge_image_generation(
        source_input: Path,
        source_file_mi_obj: MediaInfo,
        media_input: Path,
        media_file_mi_obj: MediaInfo,
        output_directory: Path,
        total_images: int,
        trim: tuple[int, int],
        subtitle_color: str,
        subtitle_outline_color: str,
        sub_names: SubNames | None,
        sub_size: int,
        subtitle_alignment: SubtitleAlignment,
        crop_mode: Cropping,
        crop_values: CropValues | None,
        advanced_resize: AdvancedResize | None,
        re_sync: int,
        indexer: Indexer,
        image_plugin: ImagePlugin,
        frame_forge_path: Path,
        ffmpeg_path: Path | None,
        signal: SignalInstance,
    ) -> int:
        """
        Generate comparison images utilizing FrameForge and emit progress signals.

        Parameters:
            source_input (Path): The input file path.
            source_file_mi_obj (Path): MediaInfo object of the input file.
            media_input (Path): The input file path.
            media_file_mi_obj (MediaInfo): MediaInfo object of the input file.
            output_directory (Path): The output directory path.
            total_images (int): The total number of images to generate.
            trim (tuple[int, int]): The percentage of the file to trim from start and end.
            subtitle_color (str): Hex color.
            subtitle_outline_color (str): Hex color.
            sub_names (Optional[SubNames]): Subtitle names.
            sub_size (int): Subtitle size.
            subtitle_alignment (SubtitleAlignment): Subtitle alignment (.ass).
            crop_mode (Cropping): Crop mode.
            crop_values (CropValues): Crop values.
            advanced_resize (Optional[AdvancedResize]): Crop values.
            re_sync (int): Re_sync value.
            indexer (Indexer): Indexer used for FrameForge.
            image_plugin (ImagePlugin): Plugin used for image generation in FrameForge.
            frame_forge_path (Path): Path to FrameForge executable.
            ffmpeg_path (Optional[Path]): Path to FFMPEG executable.
            signal (SignalInstance[str, float]): The signal used to emit progress updates on the frontend.

        """
        return FrameForgeImageGeneration().generate_images(
            source_input=source_input,
            source_file_mi_obj=source_file_mi_obj,
            media_input=media_input,
            media_file_mi_obj=media_file_mi_obj,
            output_directory=output_directory,
            total_images=total_images,
            trim=trim,
            subtitle_color=subtitle_color,
            subtitle_outline_color=subtitle_outline_color,
            sub_names=sub_names,
            sub_size=sub_size,
            subtitle_alignment=subtitle_alignment,
            crop_mode=crop_mode,
            crop_values=crop_values,
            advanced_resize=advanced_resize,
            re_sync=re_sync,
            indexer=indexer,
            image_plugin=image_plugin,
            frame_forge_path=frame_forge_path,
            ffmpeg_path=ffmpeg_path,
            signal=signal,
        )
