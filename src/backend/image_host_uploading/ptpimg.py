# Will keep this file here for reference, this was the working PTPIMG uploader, in case it ever comes back.

# import aiohttp
# import asyncio
# from collections.abc import Callable, Sequence, Awaitable
# from os import PathLike
# from pathlib import Path

# from src.exceptions import ImageUploadError
# from src.packages.custom_types import ImageUploadData

# PTP_BASE_URL = "https://ptpimg.me"


# async def upload_image(
#     session,
#     url: str,
#     headers: dict[str, str],
#     data: dict[str, str],
#     file_path: PathLike,
# ) -> dict | str:
#     with open(file_path, "rb") as image_file:
#         form_data = aiohttp.FormData()
#         form_data.add_field("file-upload[0]", image_file, filename=Path(file_path).name)
#         form_data.add_field("format", "json")
#         form_data.add_field("api_key", data["api_key"])

#         async with session.post(url, headers=headers, data=form_data) as response:
#             if response.status == 200:
#                 response_json = await response.json()
#                 result = response_json[0]
#                 img_url = f"{PTP_BASE_URL}/{result['code']}.{result['ext']}"
#                 return img_url
#             else:
#                 return {"status": response.status, "reason": response.reason}


# async def _ptpimg_upload_batch(
#     api_key: str,
#     filepaths: Sequence[Path],
#     start_index: int,
#     cb: Callable[[int], Awaitable] | None = None,
# ) -> dict[int, ImageUploadData]:
#     async def upload_single_image(filepath: PathLike, index: int):
#         response = await upload_image(session, url, headers, payload, filepath)
#         if not isinstance(response, str):
#             raise ImageUploadError(
#                 f"Failure uploading image: {response.get('status')} ({response.get('reason')})"
#             )
#         image_data = ImageUploadData(response, None)
#         if cb:
#             await cb(index + 1)
#         return index, image_data

#     url = f"{PTP_BASE_URL}/upload.php"
#     headers = {"referer": f"{PTP_BASE_URL}/index.php"}
#     payload = {"api_key": api_key}

#     tasks = []
#     async with aiohttp.ClientSession() as session:
#         for i, filepath in enumerate(filepaths):
#             task = asyncio.create_task(upload_single_image(filepath, start_index + i))
#             tasks.append(task)

#         batch_results_list = await asyncio.gather(*tasks)

#     return {index: result for index, result in batch_results_list}


# async def ptpimg_upload(
#     api_key: str,
#     filepaths: Sequence[Path],
#     batch_size: int = 4,
#     cb: Callable[[int], Awaitable] | None = None,
# ) -> dict[int, ImageUploadData] | None:
#     if not api_key:
#         raise ValueError("You are required to have an API key")

#     if not filepaths:
#         return {}
#     filepaths = sorted(filepaths)

#     results = {}
#     tasks = []
#     for i in range(0, len(filepaths), batch_size):
#         batch = filepaths[i : i + batch_size]
#         task = asyncio.create_task(_ptpimg_upload_batch(api_key, batch, i, cb))
#         tasks.append(task)

#     batch_results_list = await asyncio.gather(*tasks)
#     for batch_results in batch_results_list:
#         results.update(batch_results)

#     return results
