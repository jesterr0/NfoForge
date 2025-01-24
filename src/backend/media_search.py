import asyncio
import concurrent.futures
import re
import requests
import tvdb_v4_official

from guessit import guessit
from itertools import zip_longest
from imdb import Cinemagoer
from imdb.Movie import Movie
from typing import Any
from rapidfuzz import fuzz
from unidecode import unidecode

from src.enums.tmdb_genres import TMDBGenreIDsMovies, TMDBGenreIDsSeries
from src.exceptions import MediaParsingError


class MediaSearchBackEnd:
    def __init__(self, api_key: str | None = None):
        self.media_data = dict()
        self.session = requests.Session()
        self.params = {
            "api_key": api_key,
            "language": "en-US",
            "include_adult": "false",
        }

    def update_api_key(self, api_key: str) -> None:
        self.params["api_key"] = api_key

    def _parse_tmdb_api(self, media_str: str):
        media_title, media_year = self._guessit(media_str)

        # Create a list of URLs for movie and TV search
        movie_url = f"https://api.themoviedb.org/3/search/movie?page=1&query={media_title}&year={media_year}"
        tv_url = f"https://api.themoviedb.org/3/search/tv?page=1&query={media_title}&year={media_year}"

        # Execute requests concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            movie_results, tv_results = list(
                executor.map(self._fetch_tmdb_results, [movie_url, tv_url])
            )

        media_dict = {}
        base_num = 0

        for movie_result, tv_result in zip_longest(movie_results, tv_results):
            if movie_result:
                movie_imdb_id = self._fetch_tmdb_external_ids(movie_result["id"])
                if (
                    movie_imdb_id.ok
                    and movie_imdb_id.content
                    and movie_result["release_date"]
                ):
                    release_date = str(movie_result["release_date"]).split("-")
                    full_release_date = (
                        f"{release_date[1]}-{release_date[2]}-{release_date[0]}"
                    )
                    base_num += 1

                    mv_tvdb_id = str(movie_result.get("id", ""))
                    mv_imdb_id = movie_imdb_id.json().get("imdb_id", "")
                    mv_plot = movie_result.get("overview", "")
                    mv_vote_average = str(movie_result.get("vote_average", ""))
                    mv_vote_get = movie_result.get("vote_average")
                    mv_vote_average = str(round(mv_vote_get, 1)) if mv_vote_get else ""
                    mv_full_release_date = (
                        full_release_date if full_release_date else ""
                    )
                    mv_year = release_date[0]
                    mv_title = movie_result.get("title", "")
                    mv_original_title = movie_result.get("original_title", "")
                    mv_poster_path = movie_result.get("poster_path", "")

                    # get genre id's and convert them to enums
                    get_mv_genre_ids = movie_result.get("genre_ids")
                    mv_genre_ids = []
                    if get_mv_genre_ids:
                        for mv_genre in get_mv_genre_ids:
                            try:
                                mv_genre_ids.append(TMDBGenreIDsMovies(mv_genre))
                            except ValueError:
                                mv_genre_ids.append(TMDBGenreIDsMovies.UNDEFINED)

                    media_dict.update(
                        {
                            f"{str(base_num)}) {movie_result['title']} ({release_date[0]})": {
                                "tvdb_id": mv_tvdb_id,
                                "imdb_id": mv_imdb_id,
                                "plot": mv_plot,
                                "vote_average": mv_vote_average,
                                "full_release_date": mv_full_release_date,
                                "year": mv_year,
                                "title": mv_title,
                                "original_title": mv_original_title,
                                "poster_path": mv_poster_path,
                                "genre_ids": mv_genre_ids,
                                "media_type": "Movie",
                                "raw_data": movie_result,
                            }
                        }
                    )

            if tv_result:
                tv_imdb_id = self._fetch_tmdb_external_ids(tv_result["id"])
                if tv_imdb_id.ok and tv_imdb_id.content and tv_result["first_air_date"]:
                    release_date = str(tv_result["first_air_date"]).split("-")
                    full_release_date = (
                        f"{release_date[1]}-{release_date[2]}-{release_date[0]}"
                    )
                    base_num += 1

                    tv_tvdb_id = str(tv_result.get("id", ""))
                    tv_imdb_id = tv_imdb_id.json().get("imdb_id", "")
                    tv_plot = tv_result.get("overview", "")
                    tv_vote_get = tv_result.get("vote_average")
                    tv_vote_average = str(round(tv_vote_get, 1)) if tv_vote_get else ""
                    tv_full_release_date = (
                        full_release_date if full_release_date else ""
                    )
                    tv_year = release_date[0]
                    tv_title = tv_result.get("title", "")
                    tv_original_title = tv_result.get("original_title", "")
                    tv_poster_path = tv_result.get("poster_path", "")
                    tv_genre_ids = tv_result.get("genre_ids")

                    # get genre id's and convert them to enums
                    get_tv_genre_ids = tv_result.get("genre_ids")
                    tv_genre_ids = []
                    if get_tv_genre_ids:
                        for tv_genre in get_tv_genre_ids:
                            try:
                                tv_genre_ids.append(TMDBGenreIDsSeries(tv_genre))
                            except ValueError:
                                tv_genre_ids.append(TMDBGenreIDsSeries.UNDEFINED)

                    media_dict.update(
                        {
                            f"{str(base_num)}) {tv_result['name']} ({release_date[0]})": {
                                "tvdb_id": tv_tvdb_id,
                                "imdb_id": tv_imdb_id,
                                "plot": tv_plot,
                                "vote_average": tv_vote_average,
                                "full_release_date": tv_full_release_date,
                                "year": tv_year,
                                "title": tv_title,
                                "original_title": tv_original_title,
                                "poster_path": tv_poster_path,
                                "genre_ids": tv_genre_ids,
                                "media_type": "Series",
                                "raw_data": tv_result,
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
        except requests.exceptions.ConnectionError:
            return []

    def _fetch_tmdb_external_ids(self, media_id):
        url = f"https://api.themoviedb.org/3/movie/{media_id}/external_ids"
        with self.session.get(url, params=self.params) as response:
            return response

    @staticmethod
    def _guessit(input_string: str) -> tuple[str | None, str]:
        get_info = guessit(input_string)
        title = get_info.get("title")
        if not title:
            raise MediaParsingError(
                f"There was an error parsing the title from input '{input_string}'"
            )
        year = get_info.get("year", "")
        return title, year

    async def parse_other_ids(
        self,
        imdb_id: str,
        tmdb_title: str,
        tmdb_year: int,
        original_language: str,
        tmdb_genres: list[TMDBGenreIDsMovies],
        tvdb_api_key: str,
    ) -> dict[str, Any]:
        tasks = {
            "imdb_data": asyncio.create_task(self.parse_imdb_data(imdb_id)),
            "tvdb_data": asyncio.create_task(
                self.parse_tvdb_data(imdb_id, tvdb_api_key)
            ),
        }

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

    @staticmethod
    async def parse_imdb_data(imdb_id: str) -> Movie | None:
        imdb_parse = Cinemagoer()
        get_movie = imdb_parse.get_movie(imdb_id.replace("t", ""))
        if get_movie:
            return get_movie

    @staticmethod
    async def parse_tvdb_data(imdb_id: str, api_key: str) -> dict | None:
        tvdb_parse = tvdb_v4_official.TVDB(api_key)
        data = tvdb_parse.search_by_remote_id(imdb_id)
        if data and isinstance(data, list):
            return data[0]

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
            requests.post,
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
