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
    def __init__(self, api_key: str | None = None, language: str = "en-US"):
        self.media_data = dict()
        self.session = niquests.Session()
        self.params = {
            "api_key": api_key,
            "language": language,
            "include_adult": "false",
        }

    def update_api_key(self, api_key: str) -> None:
        self.params["api_key"] = api_key

    def update_language(self, language: str) -> None:
        self.params["language"] = language

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

            # use smart title selection based on language preference
            selected_title = self._select_preferred_title(
                title, None, original_language
            )

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
        self.session.close()
        return self.media_data

    def _fetch_tmdb_results(self, url):
        try:
            with self.session.get(url, params=self.params) as response:
                response.raise_for_status()
                return response.json()["results"]
        except niquests.exceptions.ConnectionError:
            return []

    def _fetch_tmdb_external_ids(
        self, media_id: str | int, media_type: str = "movie"
    ) -> dict:
        """Fetch external IDs for a movie or TV show"""
        endpoint = "movie" if media_type.lower() == "movie" else "tv"
        url = f"https://api.themoviedb.org/3/{endpoint}/{media_id}/external_ids"
        try:
            with self.session.get(url, params=self.params) as response:
                response.raise_for_status()
                return response.json()
        except niquests.exceptions.ConnectionError:
            return {}

    def fetch_external_ids_for_selection(self, tmdb_id: str, media_type: str) -> dict:
        """Public method to fetch external IDs when user makes final selection"""
        return self._fetch_tmdb_external_ids(tmdb_id, media_type)

    def _fetch_tmdb_movie_details(self, media_id: str | int) -> niquests.Response:
        """Fetch movie details with alternative titles"""
        url = f"https://api.themoviedb.org/3/movie/{media_id}?append_to_response=alternative_titles"
        with self.session.get(url, params=self.params) as response:
            return response

    def _fetch_tmdb_tv_details(self, media_id: str | int) -> niquests.Response:
        """Fetch TV details with alternative titles"""
        url = f"https://api.themoviedb.org/3/tv/{media_id}?append_to_response=alternative_titles"
        with self.session.get(url, params=self.params) as response:
            return response

    def _select_preferred_title(
        self,
        tmdb_title: str,
        alternative_titles_data: dict | None,
        original_language: str = "",
    ) -> str:
        """Select the preferred title based on language setting with intelligent fallback hierarchy"""
        if not alternative_titles_data:
            return tmdb_title

        current_language = self.params.get("language", "en-US")

        # Parse language components from user's preference
        language_parts = current_language.split("-")
        base_language = language_parts[0].lower()  # e.g., "es" from "es-419"
        country_code = language_parts[-1].upper() if len(language_parts) > 1 else None

        from src.logger.nfo_forge_logger import LOG

        # NEW: Check if user's language matches the original language
        if original_language and base_language == original_language.lower():
            LOG.info(
                LOG.LOG_SOURCE.BE,
                f"Using original title for {current_language} - matches original language '{original_language}': '{tmdb_title}'",
            )
            return tmdb_title

        titles = alternative_titles_data.get("titles", [])

        # try exact language-country match (e.g., es-419)
        if country_code:
            for title_data in titles:
                title_country = title_data.get("iso_3166_1", "").upper()
                if title_country == country_code:
                    exact_title = title_data.get("title", "").strip()
                    if exact_title:
                        LOG.info(
                            LOG.LOG_SOURCE.BE,
                            f"Exact match found for {current_language}: '{exact_title}' "
                            f"(country: {country_code})",
                        )
                        return exact_title

        # try language family match (e.g., any es-XX when looking for es-419)
        if base_language != "en":  # skip this for English to maintain existing logic
            language_family_titles = []
            for title_data in titles:
                title_country = title_data.get("iso_3166_1", "").upper()
                family_title = title_data.get("title", "").strip()
                if family_title and title_country:
                    # collect all titles from the same language family
                    language_family_titles.append((family_title, title_country))

            if language_family_titles:
                # use the first available title from the language family
                family_title, family_country = language_family_titles[0]
                LOG.info(
                    LOG.LOG_SOURCE.BE,
                    f"Language family match for {current_language}: '{family_title}' "
                    f"(from {base_language}-{family_country})",
                )
                return family_title

        # English fallback logic (for English users or final fallback)
        if current_language.startswith("en") or base_language == "en":
            # extract country code from language (e.g., "en-US" -> "US")
            en_country_code = country_code if country_code else "US"

            # look for country-specific English title
            for title_data in titles:
                if title_data.get("iso_3166_1") == en_country_code:
                    regional_title = title_data.get("title", "").strip()
                    if regional_title:
                        LOG.info(
                            LOG.LOG_SOURCE.BE,
                            f"Using {en_country_code} alternative title for {current_language}: "
                            f"'{regional_title}' instead of TMDB: '{tmdb_title}'",
                        )
                        return regional_title

            # if no exact English country match, try US as fallback
            if en_country_code != "US":
                for title_data in titles:
                    if title_data.get("iso_3166_1") == "US":
                        us_title = title_data.get("title", "").strip()
                        if us_title:
                            LOG.info(
                                LOG.LOG_SOURCE.BE,
                                f"Using US alternative title as fallback for {current_language}: "
                                f"'{us_title}' instead of TMDB: '{tmdb_title}'",
                            )
                            return us_title

        # final English fallback for non-English languages
        elif base_language != "en":
            for title_data in titles:
                if title_data.get("iso_3166_1") == "US":
                    en_fallback_title = title_data.get("title", "").strip()
                    if en_fallback_title:
                        LOG.info(
                            LOG.LOG_SOURCE.BE,
                            f"Using English fallback for {current_language}: '{en_fallback_title}' "
                            f"(no {base_language} alternatives found)",
                        )
                        return en_fallback_title

        # final fallback: use TMDB default title
        LOG.info(
            LOG.LOG_SOURCE.BE,
            f"Using TMDB default title for {current_language}: '{tmdb_title}' (no alternatives found)",
        )
        return tmdb_title

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
        # if no IMDb ID provided but we have TMDB ID, fetch external IDs first
        if not imdb_id and tmdb_id and media_type:
            external_ids = self.fetch_external_ids_for_selection(
                tmdb_id, media_type.lower()
            )
            imdb_id = external_ids.get("imdb_id", "")

        tasks = {}

        if imdb_id:
            tasks["imdb_data"] = asyncio.create_task(self.parse_imdb_data(imdb_id))
            tasks["tvdb_data"] = asyncio.create_task(self.parse_tvdb_data(imdb_id))

        # parse anime if needed
        if TMDBGenreIDsMovies.ANIMATION in tmdb_genres and original_language == "ja":
            tasks["ani_list_data"] = asyncio.create_task(
                self.parse_ani_list(tmdb_title, tmdb_year)
            )

        results = {}
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
