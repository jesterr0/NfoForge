import csv
from pymediainfo import MediaInfo
from pathlib import Path


def get_audio_codec_info(file_path):
    try:
        media_info = MediaInfo.parse(file_path)
    except OSError as os_err:
        print(f"OSError: {os_err}. Skipping file: {file_path}")
        return []
    except Exception as e:
        print(f"Error parsing file: {file_path}. Skipping...")
        return []

    audio_codec_info = []

    for track in media_info.tracks:
        if track.track_type == "Audio":
            format = track.format
            other_format = track.other_format
            format_info = track.format_info
            commercial_name = track.commercial_name
            other_commercial_name = track.other_commercial_name
            codec_id = track.codec_id
            audio_codec_info.append(
                {
                    "format": format,
                    "other_format": other_format,
                    "format_info": format_info,
                    "commercial_name": commercial_name,
                    "other_commercial_name": other_commercial_name,
                    "codec_id": codec_id,
                }
            )

    return audio_codec_info


def process_directory(directory, output_file):
    file_count = 0
    with open(output_file, "a", newline="", encoding="utf-8") as csvfile:
        fieldnames = [
            "file",
            "format",
            "other_format",
            "format_info",
            "commercial_name",
            "other_commercial_name",
            "codec_id",
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        # Check if the file is empty, if so, write the header
        if Path(output_file).stat().st_size == 0:
            writer.writeheader()

        for file_path in Path(directory).rglob("*"):
            if file_path.is_file():
                try:
                    audio_codec_info = get_audio_codec_info(file_path)
                    for info in audio_codec_info:
                        writer.writerow(
                            {
                                "file": file_path.name,
                                "format": info["format"],
                                "other_format": info["other_format"],
                                "format_info": info["format_info"],
                                "commercial_name": info["commercial_name"],
                                "other_commercial_name": info["other_commercial_name"],
                                "codec_id": info["codec_id"],
                            }
                        )
                        csvfile.flush()
                    file_count += 1
                    print(f"Processed {file_count} files", end="\r")
                except Exception as e:
                    print(f"Error processing file: {file_path}. Skipping... Error: {e}")


if __name__ == "__main__":
    directory = r"PATH"
    output_file = "remux_files.csv"
    process_directory(directory, output_file)
