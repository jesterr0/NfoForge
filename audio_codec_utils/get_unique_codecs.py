import os
import csv
from collections import OrderedDict


def remove_duplicates(input_files, output_file):
    unique_rows = (
        OrderedDict()
    )  # Using OrderedDict to maintain insertion order and remove duplicates

    # Iterate over each input CSV file
    for input_file in input_files:
        with open(input_file, "r", newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            # Read the title row
            title_row = next(reader)
            # Add title row to the output CSV file
            if not unique_rows:
                with open(output_file, "w", newline="", encoding="utf-8") as output_csv:
                    writer = csv.DictWriter(output_csv, fieldnames=title_row.keys())
                    writer.writerow(title_row)
            for row in reader:
                # Generate a unique key for each row based on selected fields
                key = tuple(
                    row[field]
                    for field in [
                        "format",
                        "other_format",
                        "format_info",
                        "commercial_name",
                        "other_commercial_name",
                        "codec_id",
                    ]
                )
                # Add row to unique_rows dictionary if key is not already present
                if key not in unique_rows:
                    unique_rows[key] = row

    # Append unique rows to the output CSV file
    with open(output_file, "a", newline="", encoding="utf-8") as output_csv:
        writer = csv.DictWriter(
            output_csv, fieldnames=list(unique_rows.values())[0].keys()
        )
        for row in unique_rows.values():
            writer.writerow(row)


if __name__ == "__main__":
    input_folder = r"audio_codec_utils\datasets"
    output_file = "combined_unique_rows.csv"

    # Get list of all CSV files in the input folder
    input_files = [
        os.path.join(input_folder, file)
        for file in os.listdir(input_folder)
        if file.endswith(".csv")
    ]

    # Remove duplicates and create combined CSV file
    remove_duplicates(input_files, output_file)
