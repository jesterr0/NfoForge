import aiohttp
import asyncio
import datetime
import re
from collections.abc import Sequence, Callable, Awaitable
from os import PathLike
from pathlib import Path

from src.packages.custom_types import ImageUploadData
from src.exceptions import ImageUploadError


def _clean_url(base_url: str) -> str:
    """Cleanse URL"""
    if base_url.endswith("/"):
        base_url = base_url[:-1]
    return base_url


def _generate_album_name(long_str: str | None) -> str:
    if long_str:
        movie_name = re.finditer(r"\d{4}(?!p)", long_str, re.IGNORECASE)
        movie_name_extraction = []

        # get the "span" from the title name
        for match in movie_name:
            movie_name_extraction.append(match.span())

        # extract the full title name (removing anything that is not needed from the filename)
        try:
            generated_album_name = (
                long_str[0 : int(movie_name_extraction[-1][-1])]
                .replace(".", " ")
                .strip()
            )

        # if for some reason there is an index error just generate a generic album name based off of the encoded input
        except IndexError:
            generated_album_name = long_str
    else:
        generated_album_name = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%d %H.%M.%S.%m"
        )

    # prevent errors when the album name could be to long
    if len(generated_album_name) > 52:
        generated_album_name = generated_album_name[:52] + "..."

    return generated_album_name


async def _login_to_chevereto_v3(
    session: aiohttp.ClientSession, base_url: str, user: str, password: str
) -> str | None:
    login_url = f"{base_url}/login"
    async with session.get(login_url) as response:
        get_login_page = await response.text()
        if not get_login_page:
            raise ImageUploadError("Failed to login (could not determine html text)")

        auth_code = (
            get_login_page.split("PF.obj.config.auth_token = ")[1]
            .split(";")[0]
            .replace('"', "")
        )
        if not auth_code:
            raise ImageUploadError("Failed to detect authorization code")

        form_data = aiohttp.FormData()
        form_data.add_field("login-subject", user)
        form_data.add_field("password", password)
        form_data.add_field("auth_token", auth_code)

        async with session.post(login_url, data=form_data) as login_response:
            confirm_login = re.search(
                r"CHV.obj.logged_user =(.+);", await login_response.text(), re.MULTILINE
            )
            if not confirm_login:
                raise ImageUploadError("Failed to login (invalid credentials)")

            return auth_code


async def _create_album(
    session: aiohttp.ClientSession, base_url: str, auth_code: str, album_name: str
) -> str | None:
    create_album_url = f"{base_url}/json"

    form_data = aiohttp.FormData()
    form_data.add_field("auth_token", auth_code)
    form_data.add_field("action", "create-album")
    form_data.add_field("type", "album")
    form_data.add_field("album[name]", album_name)
    form_data.add_field("album[description]", "FrameForge")
    form_data.add_field("album[password]", "")
    form_data.add_field("album[new]", "true")

    async with session.post(create_album_url, data=form_data) as album:
        if album.status != 200:
            raise ImageUploadError(f"Bad response (code: {album.status})")

        album_json = await album.json()
        album_id = album_json["album"]["id_encoded"]
        if not album_id:
            raise ImageUploadError("Failed to determine album id")
        return album_id


async def _upload_image(
    session: aiohttp.ClientSession,
    base_url: str,
    auth_code: str,
    album_id: str,
    img: Path,
    cb: Callable[[int], Awaitable] | None,
    idx: int,
) -> ImageUploadData:
    with open(img, "rb") as image_file:
        form_data = aiohttp.FormData()
        form_data.add_field("source", image_file, filename=Path(img).name)
        form_data.add_field("type", "file")
        form_data.add_field("action", "upload")
        form_data.add_field("auth_token", auth_code)
        form_data.add_field("album_id", album_id)
        form_data.add_field("nsfw", "0")

        async with session.post(f"{base_url}/json", data=form_data) as img_upload:
            response_data = (
                await img_upload.json() if img_upload.status == 200 else None
            )
            if not response_data:
                raise ImageUploadError("Failed to get response data from client")
            image_data = response_data.get("image", {})
            full_url = image_data.get("url", "")
            medium_url = image_data.get("medium", {}).get("url", "")
            response_data = ImageUploadData(full_url, medium_url)
            if cb:
                await cb(idx)
            return response_data


async def _upload_images(
    session: aiohttp.ClientSession,
    base_url: str,
    auth_code: str,
    album_id: str,
    filepaths: Sequence[PathLike[str] | Path | str],
    batch_size: int,
    cb: Callable[[int], Awaitable] | None,
) -> dict[int, ImageUploadData]:
    tasks = [
        asyncio.create_task(
            _upload_image(
                session, base_url, auth_code, album_id, Path(img), cb, idx + 1
            )
        )
        for idx, img in enumerate(filepaths)
    ]
    results = {}
    for i in range(0, len(tasks), batch_size):
        batch_results = await asyncio.gather(*tasks[i : i + batch_size])
        results.update({i + j: batch_results[j] for j in range(len(batch_results))})
    return results


async def chevereto_v3_upload(
    base_url: str,
    user: str,
    password: str,
    filepaths: Sequence[Path],
    batch_size: int = 4,
    album_name: str | None = None,
    cb: Callable[[int], Awaitable] | None = None,
) -> dict[int, ImageUploadData]:
    base_url = _clean_url(base_url)
    filepaths = sorted(filepaths)

    async with aiohttp.ClientSession() as session:
        auth_code = await _login_to_chevereto_v3(session, base_url, user, password)
        if not auth_code:
            raise ImageUploadError("Failed to log in to Chevereto v3")

        album_id = await _create_album(
            session,
            base_url,
            auth_code,
            _generate_album_name(album_name),
        )
        if not album_id:
            raise ImageUploadError("Failed to create album in Chevereto v3")

        uploaded_images = await _upload_images(
            session, base_url, auth_code, album_id, filepaths, batch_size, cb
        )
        return uploaded_images
