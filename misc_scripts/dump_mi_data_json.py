import json
import asyncio
from pathlib import Path
from pymediainfo import MediaInfo


class MediaInfoProcessor:
    def __init__(
        self,
        output_dir: Path,
        directories: list,
        extensions: set,
        max_concurrent_tasks: int,
    ):
        self.output_dir = output_dir
        self.directories = directories
        self.extensions = extensions
        self.total_files = 0
        self.processed_files = 0
        self.semaphore = asyncio.Semaphore(max_concurrent_tasks)

    async def get_file_path_objects(self, directory) -> set:
        file_name_set = set()
        for item in Path(directory).rglob("*"):
            if item.suffix in self.extensions:
                file_name_set.add(item)
        return file_name_set

    async def get_mi_dict(self, file_path: Path) -> dict:
        mi_parse = MediaInfo.parse(file_path)
        return mi_parse.to_data()

    async def write_json_data(self, file_path: Path, data: dict) -> None:
        output = self.output_dir / (file_path.stem + ".json")
        with open(output, "w") as json_out:
            json_out.write(json.dumps(data, indent=2))

    async def process_files(self) -> None:
        tasks = []
        for directory in self.directories:
            files = await self.get_file_path_objects(directory)
            self.total_files += len(files)
            for file_path in files:
                task = self.process_file(file_path)
                tasks.append(task)
        await asyncio.gather(*tasks)

    async def process_file(self, file_path: Path) -> None:
        try:
            async with self.semaphore:
                data = await self.get_mi_dict(file_path)
                await self.write_json_data(file_path, data)
                self.processed_files += 1
                print(f"Processed file ({self.processed_files}/{self.total_files})")
        except Exception as parse_error:
            print(f"Failed to process {file_path}: {parse_error}")


if __name__ == "__main__":
    # change
    directories = [
        r"",
    ]
    extensions = {".mkv", ".avi", ".mp4", ".mov", ".m4v"}
    json_output_dir = Path(r"")
    max_concurrent_tasks = 2
    # change

    # logic
    processor = MediaInfoProcessor(
        json_output_dir, directories, extensions, max_concurrent_tasks
    )
    asyncio.run(processor.process_files())
