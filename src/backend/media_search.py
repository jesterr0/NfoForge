import asyncio
import base64
import re
from typing import Any

from guessit import guessit
from imdb import Cinemagoer
from imdb.Movie import Movie
import niquests
from rapidfuzz import fuzz
import tvdb_v4_official
from unidecode import unidecode

from src.backend.utils.super_sub import normalize_super_sub
from src.enums.tmdb_genres import TMDBGenreIDsMovies, TMDBGenreIDsSeries


class MediaSearchBackEnd:
    def __init__(
        self,
        api_key: str | None = None,
        language: str = "en-US",
        use_base_language_for_images: bool = True,
    ):
        self.media_data = dict()
        self.session = niquests.Session()
        self.use_base_language_for_images = use_base_language_for_images
        self.params = {
            "api_key": api_key,
            "language": language,
            "include_adult": "false",
        }

    def update_api_key(self, api_key: str) -> None:
        self.params["api_key"] = api_key

    def update_language(self, language: str) -> None:
        self.params["language"] = language

    def close_session(self) -> None:
        """Properly close the session when done"""
        if hasattr(self, "session") and self.session:
            self.session.close()

    def __del__(self):
        """Cleanup when object is destroyed"""
        self.close_session()

    def _parse_tmdb_api(self, media_str: str):
        media_title, media_year = self._guessit(media_str)

        multi_url = (
            f"https://api.themoviedb.org/3/search/multi?page=1&query={media_title}"
        )
        if media_year:
            multi_url += f"&year={media_year}"

        multi_results = self._fetch_tmdb_results(multi_url)

        media_dict = {}
        base_num = 0

        for result in multi_results:
            media_type = result.get("media_type")

            # skip person results, only process movie and tv
            if media_type not in ["movie", "tv"]:
                continue

            # check if the result has a valid release date and extract it
            release_date = None
            if media_type == "movie" and result.get("release_date"):
                release_date = str(result["release_date"]).split("-")
            elif media_type == "tv" and result.get("first_air_date"):
                release_date = str(result["first_air_date"]).split("-")

            if not release_date:
                continue

            full_release_date = f"{release_date[1]}-{release_date[2]}-{release_date[0]}"
            base_num += 1

            tmdb_id = str(result.get("id", ""))
            plot = result.get("overview", "")
            vote_get = result.get("vote_average")
            vote_average = str(round(vote_get, 1)) if vote_get else ""
            year = release_date[0]

            if media_type == "movie":
                title = result.get("title", "")
                original_title = result.get("original_title", "")
                genre_enum_class = TMDBGenreIDsMovies
                display_media_type = "Movie"
            else:
                title = result.get("name", "")
                original_title = result.get("original_name", "")
                genre_enum_class = TMDBGenreIDsSeries
                display_media_type = "Series"

            poster_path = result.get("poster_path", "")
            original_language = result.get("original_language", "")

            # convert genre IDs to enums
            get_genre_ids = result.get("genre_ids")
            genre_ids = []
            if get_genre_ids:
                for genre in get_genre_ids:
                    try:
                        genre_ids.append(genre_enum_class(genre))
                    except ValueError:
                        genre_ids.append(genre_enum_class.UNDEFINED)

            # use TMDB title directly since we don't have alternative titles at this stage
            # proper title selection happens later with complete TMDB data
            selected_title = title

            media_dict.update(
                {
                    f"{str(base_num)}) {selected_title} ({year})": {
                        "tmdb_id": tmdb_id,
                        "plot": plot,
                        "vote_average": vote_average,
                        "full_release_date": full_release_date,
                        "year": year,
                        "title": normalize_super_sub(selected_title),
                        "original_title": original_title,
                        "poster_path": poster_path,
                        "genre_ids": genre_ids,
                        "media_type": display_media_type,
                        "raw_data": result,
                        "original_language": original_language,
                    }
                }
            )
        self.media_data.clear()
        self.media_data = media_dict
        return self.media_data

    def _fetch_tmdb_results(self, url):
        try:
            with self.session.get(url, params=self.params) as response:
                response.raise_for_status()
                return response.json()["results"]
        except niquests.exceptions.ConnectionError:
            return []

    def _fetch_tmdb_complete_data(
        self, media_id: str | int, media_type: str = "movie"
    ) -> dict:
        """
        Fetch complete TMDB data with alternative titles, images, and external IDs

        This method fetches comprehensive data from TMDB including:
        - Basic movie/TV show information (title, overview, release date, etc.)
        - Alternative titles for different regions/languages
        - All available images (posters, backdrops, logos)
        - External IDs (IMDb, TVDB, etc.)

        Note: Uses base language (e.g., 'en' instead of 'en-US') for image requests
        to ensure all images are returned, as TMDB filters images by specific regions
        when using country-specific language codes.

        Example URL: https://api.themoviedb.org/3/movie/603?append_to_response=alternative_titles,images,external_ids&language=en
        """
        endpoint = "movie" if media_type.lower() == "movie" else "tv"
        url = f"https://api.themoviedb.org/3/{endpoint}/{media_id}?append_to_response=alternative_titles,images,external_ids"

        # create modified params with base language for better image results
        image_params = self.params.copy()

        if self.use_base_language_for_images:
            current_language = image_params.get("language", "en-US")
            # extract base language (e.g., 'en' from 'en-US')
            base_language = current_language.split("-")[0]
            image_params["language"] = base_language

        try:
            with self.session.get(url, params=image_params) as response:
                response.raise_for_status()
                return response.json()
        except niquests.exceptions.ConnectionError:
            return {}

    def fetch_complete_tmdb_data_for_selection(
        self, tmdb_id: str, media_type: str
    ) -> dict:
        """Public method to fetch complete TMDB data when user makes final selection"""
        return self._fetch_tmdb_complete_data(tmdb_id, media_type)

    @staticmethod
    def _guessit(input_string: str) -> tuple[str | None, str]:
        get_info = guessit(input_string)
        title = get_info.get("title")
        year = get_info.get("year", "")
        if not title and year:
            title = input_string.split(str(year))[0].strip()
        elif not title and not year:
            title = input_string
        return title, year

    async def parse_other_ids(
        self,
        imdb_id: str,
        tmdb_title: str,
        tmdb_year: int,
        original_language: str,
        tmdb_genres: list[TMDBGenreIDsMovies],
        tmdb_id: str = "",
        media_type: str = "",
    ) -> dict[str, Any]:
        # fetch complete TMDB data if we have TMDB ID
        tmdb_complete_data = None
        if tmdb_id and media_type:
            tmdb_complete_data = self.fetch_complete_tmdb_data_for_selection(
                tmdb_id, media_type.lower()
            )
            # extract IMDb ID from complete data if not already provided
            if not imdb_id and tmdb_complete_data:
                external_ids = tmdb_complete_data.get("external_ids", {})
                imdb_id = external_ids.get("imdb_id", "")

        tasks = {}

        # only add tasks if we have valid IMDb ID
        if imdb_id:
            tasks["imdb_data"] = asyncio.create_task(self.parse_imdb_data(imdb_id))
            tasks["tvdb_data"] = asyncio.create_task(self.parse_tvdb_data(imdb_id))

        # parse anime if needed
        if TMDBGenreIDsMovies.ANIMATION in tmdb_genres and original_language == "ja":
            tasks["ani_list_data"] = asyncio.create_task(
                self.parse_ani_list(tmdb_title, tmdb_year)
            )

        results = {}

        # add complete TMDB data to results
        if tmdb_complete_data:
            results["tmdb_complete_data"] = {
                "success": True,
                "result": tmdb_complete_data,
            }

        for key, task in tasks.items():
            try:
                result = await task
                results[key] = {"success": True, "result": result}
            except Exception as e:
                results[key] = {"success": False, "error": str(e)}
        return results

    async def parse_tvdb_data(self, imdb_id: str) -> dict | None:
        tvdb_parse = tvdb_v4_official.TVDB(self._get_tvdb_k())
        data = tvdb_parse.search_by_remote_id(imdb_id)
        if data and isinstance(data, list):
            return data[0]

    @staticmethod
    def _get_tvdb_k() -> str:
        k = (
            b"MDEwMDExMTAwMTAxMDEwMDAxMDExMDAxMDAxMTAwMDAwMTAwMTEwMTAwMTEwMDEwMDE"
            b"wMTEwMDEwMDExMDEwMTAxMDAxMTAxMDEwMTAxMDAwMTAwMDEwMTAxMTEwMTAwMDEwMTEwMTA"
            b"wMTAwMDExMTAxMDAwMTAxMDAxMTAxMDEwMTAwMTEwMTAxMDAwMDExMDAxMTAwMDAwMDExMDA"
            b"wMDAxMDExMDEwMDEwMTAxMDAwMTEwMDExMTAwMTEwMTAxMDEwMDExMDAwMTAxMDExMTAxMDA"
            b"xMDAxMDAxMTAxMDEwMTAwMTEwMTAxMDEwMTAwMDEwMDAwMDEwMTExMDEwMDAxMDAxMTEwMDEw"
            b"MTAxMDAwMTEwMTAxMTAwMTEwMTAxMDEwMTEwMTAwMTEwMTAxMDAxMDAxMTAxMDExMTAxMTEwM"
            b"TAwMTExMDAxMTAxMDEwMDExMDEwMDAwMTEwMTEwMDAxMDAxMTEwMDEwMTAxMDAwMTAwMTAxMDAxMTAxMDEx"
        )
        binary_bytes = base64.b64decode(k)
        b64_bytes = bytes(
            int(binary_bytes[i : i + 8], 2) for i in range(0, len(binary_bytes), 8)
        )
        return base64.b64decode(b64_bytes).decode()

    @staticmethod
    async def parse_imdb_data(imdb_id: str) -> Movie | None:
        imdb_parse = Cinemagoer()
        get_movie = imdb_parse.get_movie(imdb_id.replace("t", ""))
        if get_movie:
            return get_movie

    @staticmethod
    async def parse_ani_list(tmdb_title: str, tmdb_year: int) -> dict[str, Any] | None:
        matcher = MatchAnilistTitle(tmdb_title, tmdb_year)
        best_match = await matcher.match()
        if best_match:
            # {'id': 21519, 'idMal': 32281, 'title': {'romaji': 'Kimi no Na wa.', 'english': 'Your Name.', 'native': '君の名は。'}, 'seasonYear': 2016, 'episodes': 1}
            return best_match


class MatchAnilistTitle:
    def __init__(self, title: str, year: int) -> None:
        self.title = title
        self.year = year
        self.data = None

    @staticmethod
    async def parse_ani_list(tmdb_title: str):
        query = """
            query ($search: String) {
                Page (page: 1) {
                    pageInfo {
                        total
                    }
                    media (search: $search, type: ANIME, sort: SEARCH_MATCH) {
                        id
                        idMal
                        title {
                            romaji
                            english
                            native
                        }
                        seasonYear
                        episodes
                    }
                }
            }
        """
        variables = {"search": tmdb_title}
        response = await asyncio.to_thread(
            niquests.post,
            "https://graphql.anilist.co",
            json={"query": query, "variables": variables},
        )
        response_json = response.json()
        return response_json

    def normalize_text(self, text: str) -> str:
        """Normalize text by removing accents, lowercasing, and stripping non-alphanumeric characters."""
        text = unidecode(text.lower())
        return re.sub(r"[^a-z0-9]", "", text)

    def filter_by_year(self, media: list, year: int) -> list:
        """Filter media by the exact year."""
        return [anime for anime in media if anime.get("seasonYear") == year]

    def get_best_match(self, media: list, search_name: str) -> dict[str, Any] | None:
        """Find the best match for a title using fuzzy string matching."""
        search_name_normalized = self.normalize_text(search_name)
        best_match: dict[str, Any] | None = None
        highest_score = 0

        for anime in media:
            for _title_type, title in anime["title"].items():
                if title:
                    title_normalized = self.normalize_text(title)
                    score = fuzz.ratio(search_name_normalized, title_normalized)

                    if score > highest_score:
                        highest_score = score
                        best_match = anime

        return best_match

    async def match(self) -> dict | None:
        """Match the anime title from the filtered data."""
        # fetch the data asynchronously
        response_data = await self.parse_ani_list(self.title)
        self.data = response_data

        # filter by year
        filtered_media = self.filter_by_year(
            self.data["data"]["Page"]["media"], self.year
        )

        # find best match
        if filtered_media:
            return self.get_best_match(filtered_media, self.title)
