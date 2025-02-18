import asyncio
import xml.etree.ElementTree as ET
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

    async def get_xml_str(self, file_path: Path) -> str | None:
        xml_parse = MediaInfo.parse(file_path, output="OLDXML")
        if isinstance(xml_parse, str):
            xml_root = ET.fromstring(xml_parse)
            minified_xml = ET.tostring(xml_root, encoding="unicode", method="xml")
            return minified_xml

    async def write_xml_data(self, file_path: Path, data: str) -> None:
        output = self.output_dir / (file_path.stem + ".xml")
        with open(output, "w", encoding="utf-8") as xml_out:
            xml_out.write(data)

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
                data = await self.get_xml_str(file_path)
                if data:
                    await self.write_xml_data(file_path, data)
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
    xml_output_dir = Path(r"")
    max_concurrent_tasks = 2
    # change

    # logic
    processor = MediaInfoProcessor(
        xml_output_dir, directories, extensions, max_concurrent_tasks
    )
    asyncio.run(processor.process_files())
