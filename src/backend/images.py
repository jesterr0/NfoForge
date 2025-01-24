import re
import platform
import oslex2
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Sequence
from os import PathLike
from pathlib import Path
from random import randint
from multiprocessing import cpu_count
from pymediainfo import MediaInfo

from PySide6.QtCore import SignalInstance

from src.logger.nfo_forge_logger import LOG
from src.config.config import Config
from src.enums.indexer import Indexer
from src.enums.image_host import ImageHost
from src.enums.image_plugin import ImagePlugin
from src.enums.subtitles import SubtitleAlignment
from src.backend.image_host_uploading.img_uploader import ImageUploader
from src.backend.utils.images import (
    determine_ffmpeg_trimmed_frames,
    generate_progress,
    get_ffmpeg_tone_map_str,
    get_total_frames,
    get_frame_rate,
    create_directories,
    vapoursynth_to_ffmpeg_crop,
)
from src.backend.utils.working_dir import RUNTIME_DIR
from src.backend.utils.images import compare_resolutions, compare_res
from src.packages.custom_types import (
    AdvancedResize,
    CropValues,
    SubNames,
    ImageUploadData,
)
from src.packages.crop_detect import CropDetect


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
            if platform.system == "Windows"
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
        compression: bool,
        ffmpeg_path: Path,
        signal: SignalInstance,
    ) -> int:
        img_comparison = create_directories(output_directory)[0]
        output = str(img_comparison / "%02d_output.png")

        total_frames = get_total_frames(mi_object)
        frame_rate = get_frame_rate(mi_object)

        available_frames, start_time = determine_ffmpeg_trimmed_frames(
            trim=trim, total_frames=total_frames, frame_rate=frame_rate
        )

        # determine mod(n, interval) where interval spaces out `total_images` within the available frames
        interval = max(1, available_frames // total_images)

        tone_map_str = ""
        if mi_object.video_tracks[0].other_hdr_format:
            tone_map_str = get_ffmpeg_tone_map_str()

        # determine threads and use half of them, defaulting back to ffmpeg default of 0 if needed
        cpu_cores = cpu_count() or 0
        thread_count = str(int(cpu_cores / 2)) if (cpu_cores and cpu_cores) > 0 else "0"

        # build vf filter
        rand_offset = randint(0, int(frame_rate) * 10)
        select_filter = f"not(mod(n+{rand_offset},{interval}))"
        vf_filter = f"select='{select_filter}'{tone_map_str}"

        command = [
            str(ffmpeg_path),
            "-ss",
            start_time,
            "-copyts",
            "-i",
            str(media_input),
            "-vf",
            vf_filter,
            "-frames:v",
            str(total_images),
            "-fps_mode",
            "vfr",
            "-compression_level",
            "9" if compression else "0",
            "-an",
            "-threads",
            thread_count,
            output,
            "-v",
            "error",
            "-hide_banner",
            "-stats",
        ]

        return self.run_ffmpeg_command(command, total_images, signal)


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
        sub_names: SubNames | None,
        sub_size: int,
        crop_values: CropValues | None,
        compression: bool,
        ffmpeg_path: Path,
        signal: SignalInstance,
    ) -> int:
        img_comparison = create_directories(output_directory)[0]

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
        if crop_values:
            user_crop_msg = (
                "Applying user defined crops "
                f"({', '.join(f'{field}={value}' for field, value in zip(crop_values._fields, crop_values))})."
            )
            LOG.info(LOG.LOG_SOURCE.BE, user_crop_msg)
            signal.emit(user_crop_msg, 0)
            detect_crop = vapoursynth_to_ffmpeg_crop(
                crop_values, source_width, source_height
            )
        elif not crop_values:
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

                split_crop = detect_crop.split("=")[1].split(":")
                detected_width = int(split_crop[0])
                detected_height = int(split_crop[1])

                if not compare_res(
                    detected_width, detected_height, media_width, media_height
                ):
                    crop_miss_match_msg = (
                        "Crop detection correction needed for mismatched resolution."
                    )
                    LOG.info(LOG.LOG_SOURCE.BE, crop_miss_match_msg)
                    signal.emit(
                        crop_miss_match_msg,
                        0,
                    )
                    detected_width = media_width
                    detected_height = media_height
                    detect_crop_msg = (
                        "Crop detection adjustment completed. "
                        f"(crop={detected_width}:{detected_height}:{split_crop[2]}:{split_crop[3]})."
                    )
                    LOG.info(LOG.LOG_SOURCE.BE, detect_crop_msg)
                    signal.emit(detect_crop_msg, 0)

        generate_enc_img_msg = "\nGenerating encode images."
        LOG.info(LOG.LOG_SOURCE.BE, generate_enc_img_msg)
        signal.emit(generate_enc_img_msg, 0)

        frame_rate = get_frame_rate(media_file_mi_obj)
        random_offset = randint(0, (int(frame_rate) * 10))

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
            compression=compression,
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
            compression=compression,
            ffmpeg=ffmpeg_path,
            signal=signal,
            ffmpeg_crop=detect_crop,
            width=media_width,
            height=media_height,
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
        compression: bool,
        ffmpeg: Path,
        signal: SignalInstance,
        ffmpeg_crop: str | None = None,
        width: int | None = None,
        height: int | None = None,
        offset_frames=0,
    ) -> int:
        # TODO: add ability to adjust sync?
        # if we decide not to, we can remove 'offset_frames'

        total_frames = get_total_frames(mi_object)

        available_frames, start_time = determine_ffmpeg_trimmed_frames(
            trim=trim, total_frames=total_frames, frame_rate=frame_rate
        )

        # determine mod(n, interval) where interval spaces out `total_images` within the available frames
        interval = max(1, available_frames // total_images)

        ffmpeg_crop = f",{ffmpeg_crop}" if ffmpeg_crop else ""
        resize = f",scale=w={width}:h={height}" if (width and height) else ""

        tone_map_str = ""
        if mi_object.video_tracks[0].other_hdr_format:
            tone_map_str = get_ffmpeg_tone_map_str()

        subtitle = ""
        draw_text_support = self.check_draw_text(ffmpeg)
        if text_overlay and draw_text_support:
            font_path = (
                Path(RUNTIME_DIR / "fonts" / "Montserrat-Medium.ttf")
                .as_posix()
                .replace(":", r"\:")
            )

            quoted_font_path = oslex2.quote(font_path)
            quoted_text_overlay = oslex2.quote(text_overlay)
            quoted_subtitle_color = oslex2.quote(subtitle_color)

            subtitle = (
                f",drawtext=fontfile={quoted_font_path}:"
                f"text={quoted_text_overlay}:"
                f"x=10:y=10:fontsize={sub_size}:fontcolor={quoted_subtitle_color}"
            )
        elif text_overlay and not draw_text_support:
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                "Your build of FFMPEG does not support the 'drawtext' filter",
            )

        # Build the vf filter for selecting frames
        select_filter = f"not(mod(n+{random_offset},{interval}))"
        vf_filter = (
            f"select='{select_filter}'{tone_map_str}{ffmpeg_crop}{resize}{subtitle}"
        )

        # determine threads and use half of them, defaulting back to ffmpeg default of 0 if needed
        cpu_cores = cpu_count() or 0
        thread_count = str(int(cpu_cores / 2)) if (cpu_cores and cpu_cores) > 0 else "0"

        command = [
            str(ffmpeg),
            "-ss",
            start_time,
            "-copyts",
            "-i",
            str(input_video),
            "-vf",
            vf_filter,
            "-frames:v",
            str(total_images),
            "-fps_mode",
            "vfr",
            "-compression_level",
            "9" if compression else "0",
            "-an",
            "-threads",
            thread_count,
            str(output_pattern),
            "-v",
            "error",
            "-hide_banner",
            "-stats",
        ]

        return self.run_ffmpeg_command(command, total_images, signal)

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
        sub_names: SubNames | None,
        sub_size: int,
        subtitle_alignment: SubtitleAlignment,
        crop_values: CropValues,
        advanced_resize: AdvancedResize | None,
        re_sync: int,
        compression: bool,
        indexer: Indexer,
        image_plugin: ImagePlugin,
        frame_forge_path: Path,
        signal: SignalInstance,
    ) -> int:
        generate_args = [
            str(frame_forge_path),
            "--source",
            str(source_input),
            "--encode",
            str(media_input),
        ]
        generate_args.extend(["--subtitle-color", subtitle_color])
        generate_args.extend(["--sub-size", str(sub_size)])
        generate_args.extend(["--sub-alignment", str(subtitle_alignment.value)])

        generate_args.extend(["--indexer", str(indexer)])
        generate_args.extend(["--img-lib", str(image_plugin)])

        img_comparison = create_directories(output_directory, sync_dir=True)[0]
        generate_args.extend(["--image-dir", str(img_comparison.parent)])

        if crop_values:
            generate_args.extend(["--left-crop", str(crop_values.left)])
            generate_args.extend(["--right-crop", str(crop_values.right)])
            generate_args.extend(["--top-crop", str(crop_values.top)])
            generate_args.extend(["--bottom-crop", str(crop_values.bottom)])

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
            # TODO: add support for source file release sub title when it's added for nfo forge
            generate_args.extend(["--release-sub-title", sub_names[1]])

        # TODO: add support for this later
        # if existing_frames:
        #     generate_args.extend(["--frames", existing_frames])

        # TODO: remove print
        print(generate_args)

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
    def upload_images(
        config: Config,
        filepaths: Sequence[PathLike[str] | Path | str],
        signal: SignalInstance,
    ) -> dict[int, ImageUploadData] | None:
        """
        Handles uploading images to image hosts.

        Parameters:
            config (Config): Config class.
            filepaths (Sequence[Union[PathLike[str], Path]]): Sequence object of filepaths.
            signal (SignalInstance[str, float]): The signal used to emit progress updates.

        Returns:
            Dictionary object numbered with ImageUploadData.
        """
        image_uploader = ImageUploader(config, signal)
        image_host = config.cfg_payload.image_host

        if image_host == ImageHost.CHEVERETO_V3:
            get_config = config.media_input_payload
            album_name = (
                get_config.renamed_file
                if get_config.renamed_file
                else get_config.encode_file
            )
            return image_uploader.chevereto_v3(
                filepaths=filepaths,
                album_name=Path(album_name).stem if album_name else None,
            )
        elif image_host == ImageHost.CHEVERETO_V4:
            return image_uploader.chevereto_v4(filepaths=filepaths)
        elif image_host == ImageHost.IMAGE_BOX:
            return image_uploader.img_box(filepaths=filepaths)
        elif image_host == ImageHost.IMAGE_BB:
            return image_uploader.imgbb(filepaths=filepaths)

    @staticmethod
    def basic_image_generation(
        media_input: Path,
        output_directory: Path,
        mi_object: MediaInfo,
        total_images: int,
        trim: tuple[int, int],
        compression: bool,
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
            compression (bool): If we want to compress the images.
            ffmpeg_path (Path): Path to FFMPEG executable.
            signal (SignalInstance[str, float]): The signal used to emit progress updates on the frontend.

        """
        return BasicImageGeneration().generate_images(
            media_input=media_input,
            output_directory=output_directory,
            mi_object=mi_object,
            total_images=total_images,
            trim=trim,
            compression=compression,
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
        sub_names: SubNames | None,
        sub_size: int,
        crop_values: CropValues | None,
        compression: bool,
        ffmpeg_path: Path,
        signal: SignalInstance,
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
            sub_names (Optional[SubNames]): Subtitle names.
            sub_size (int): Subtitle size.
            crop_values (Optional[CropValues]): Crop values.
            compression (bool): If we want to compress the images.
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
            sub_names=sub_names,
            sub_size=sub_size,
            crop_values=crop_values,
            compression=compression,
            ffmpeg_path=ffmpeg_path,
            signal=signal,
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
        sub_names: SubNames | None,
        sub_size: int,
        subtitle_alignment: SubtitleAlignment,
        crop_values: CropValues,
        advanced_resize: AdvancedResize | None,
        re_sync: int,
        compression: bool,
        indexer: Indexer,
        image_plugin: ImagePlugin,
        frame_forge_path: Path,
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
            sub_names (Optional[SubNames]): Subtitle names.
            sub_size (int): Subtitle size.
            subtitle_alignment (SubtitleAlignment): Subtitle alignment (.ass).
            crop_values (CropValues): Crop values.
            advanced_resize (Optional[AdvancedResize]): Crop values.
            re_sync (int): Re_sync value.
            compression (bool): If we want to compress the images.
            indexer (Optional[Indexer]): Indexer used for FrameForge.
            image_plugin (Optional[ImagePlugin]): Plugin used for image generation in FrameForge.
            frame_forge_path (Path): Path to FrameForge executable.
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
            sub_names=sub_names,
            sub_size=sub_size,
            subtitle_alignment=subtitle_alignment,
            crop_values=crop_values,
            advanced_resize=advanced_resize,
            re_sync=re_sync,
            compression=compression,
            indexer=indexer,
            image_plugin=image_plugin,
            frame_forge_path=frame_forge_path,
            signal=signal,
        )
