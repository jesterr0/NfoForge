import asyncio
import base64
from collections.abc import Mapping, Sequence
import re
from typing import Any, cast
import zlib

from guessit import guessit
import niquests
from rapidfuzz import fuzz
from unidecode import unidecode

from src.backend.utils.guessit_helpers import get_guessit_title
from src.backend.utils.super_sub import normalize_super_sub
from src.backend.utils.tvdb_client import AsyncTVDBClient, TVDBClient
from src.enums.media_type import MediaType
from src.enums.tmdb_genres import TMDBGenreIDsMovies, TMDBGenreIDsSeries
from src.enums.tvdb_season_type import TVDBSeasonType
from src.exceptions import MediaSearchError, MediaSearchUnavailableError
from src.logger.nfo_forge_logger import LOG


class MediaSearchBackEnd:
    def __init__(
        self,
        language: str = "en-US",
        use_base_language_for_images: bool = True,
        timeout: int = 60,
    ) -> None:
        self.media_data: dict[str, dict[str, Any]] = {}
        self.session = niquests.Session()
        self._tvdb_client: AsyncTVDBClient | None = None
        self.use_base_language_for_images = use_base_language_for_images
        self.timeout = max(1, timeout)
        self.params = {
            "api_key": self._get_tmdb_k(),
            "language": language,
            "include_adult": "false",
        }

    def update_language(self, language: str) -> None:
        self.params["language"] = language

    def close_session(self) -> None:
        """Properly close the session when done"""
        if hasattr(self, "session") and self.session:
            self.session.close()
        if hasattr(self, "_tvdb_client") and self._tvdb_client:
            self._tvdb_client.close()

    def __del__(self) -> None:
        """Cleanup when object is destroyed"""
        self.close_session()

    def _parse_tmdb_api(self, media_str: str) -> dict[str, dict[str, Any]]:
        media_title, media_year = self._guessit(media_str)

        # ensure we don't leave a previous successful search available while a new
        # request is in flight or if that request fails.
        self.media_data.clear()

        search_params: dict[str, Any] = {
            **self.params,
            "page": 1,
            "query": media_title,
        }
        if media_year:
            search_params["year"] = media_year

        multi_results = self._fetch_tmdb_results(
            "https://api.themoviedb.org/3/search/multi",
            params=search_params,
        )

        media_dict: dict[str, dict[str, Any]] = {}
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
                genre_enum_class: (
                    type[TMDBGenreIDsMovies] | type[TMDBGenreIDsSeries]
                ) = TMDBGenreIDsMovies
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

    def _fetch_tmdb_results(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            with self.session.get(
                url,
                params=params if params is not None else self.params,
                timeout=self.timeout,
            ) as response:
                response.raise_for_status()
                response_json = response.json()
                if not isinstance(response_json, dict):
                    raise MediaSearchError("TMDB returned an invalid search response.")
                response_data = cast(dict[str, Any], response_json)
                results = response_data.get("results", [])
                return (
                    cast(list[dict[str, Any]], results)
                    if isinstance(results, list)
                    else []
                )
        except (
            niquests.exceptions.ConnectionError,
            niquests.exceptions.Timeout,
            niquests.exceptions.ProxyError,
            niquests.exceptions.SSLError,
        ) as error:
            raise MediaSearchUnavailableError(
                "TMDB search is unavailable. Check your internet connection and try again."
            ) from error
        except niquests.exceptions.RequestException as error:
            raise MediaSearchError(f"TMDB search failed: {error}") from error
        except (TypeError, ValueError) as error:
            raise MediaSearchError(
                "TMDB returned an invalid search response."
            ) from error

    def fetch_complete_tmdb_data_for_selection(
        self, media_id: str | int, media_type: MediaType
    ) -> dict[str, Any]:
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
        endpoint = "movie" if media_type is MediaType.MOVIE else "tv"
        validated_media_id = self._validate_tmdb_id(media_id)
        url = f"https://api.themoviedb.org/3/{endpoint}/{validated_media_id}"

        # create modified params with base language for better image results
        image_params = self.params.copy()

        if self.use_base_language_for_images:
            current_language = image_params.get("language") or "en-US"
            # extract base language (e.g., 'en' from 'en-US')
            base_language = current_language.split("-")[0]
            image_params["language"] = base_language
        image_params["append_to_response"] = "alternative_titles,images,external_ids"

        try:
            with self.session.get(
                url, params=image_params, timeout=self.timeout
            ) as response:
                response.raise_for_status()
                response_json = response.json()
                if not isinstance(response_json, dict):
                    raise MediaSearchError(
                        "TMDB returned an invalid metadata response."
                    )
                response_data = cast(dict[str, Any], response_json)
                if not response_data:
                    raise MediaSearchError(
                        "TMDB returned no metadata for the selection."
                    )
                returned_id = response_data.get("id")
                try:
                    returned_numeric_id = (
                        int(str(returned_id))
                        if isinstance(returned_id, str | int)
                        and not isinstance(returned_id, bool)
                        else None
                    )
                except ValueError:
                    returned_numeric_id = None
                if returned_numeric_id is None or returned_numeric_id != int(
                    validated_media_id
                ):
                    raise MediaSearchError(
                        "TMDB returned metadata for a different ID than requested."
                    )
                return response_data
        except (
            niquests.exceptions.ConnectionError,
            niquests.exceptions.Timeout,
            niquests.exceptions.ProxyError,
            niquests.exceptions.SSLError,
        ) as error:
            raise MediaSearchUnavailableError(
                "TMDB metadata is unavailable. Check your internet connection and try again."
            ) from error
        except niquests.exceptions.RequestException as error:
            raise MediaSearchError(f"TMDB metadata lookup failed: {error}") from error
        except (TypeError, ValueError) as error:
            raise MediaSearchError(
                "TMDB returned an invalid metadata response."
            ) from error

    @staticmethod
    def _guessit(input_string: str) -> tuple[str, str]:
        get_info = guessit(input_string, {"excludes": ["language"]})
        title = get_guessit_title(get_info)
        year_value = get_info.get("year", "")
        year = str(year_value) if year_value else ""
        if not title and year:
            title = input_string.split(str(year))[0].strip()
        elif not title and not year:
            title = input_string
        return title, year

    async def parse_other_ids(
        self,
        media_type: MediaType,
        imdb_id: str,
        tmdb_title: str,
        tmdb_year: int,
        original_language: str,
        tmdb_genres: Sequence[TMDBGenreIDsMovies | TMDBGenreIDsSeries],
        tmdb_id: str = "",
        tvdb_id: str = "",
    ) -> dict[str, Any]:
        # fetch complete TMDB data if we have TMDB ID
        tmdb_complete_data: dict[str, Any] | None = None
        resolved_tvdb_id = int(tvdb_id) if tvdb_id.isdecimal() else None
        if tmdb_id:
            tmdb_complete_data = self.fetch_complete_tmdb_data_for_selection(
                tmdb_id, media_type
            )
            if tmdb_complete_data:
                external_ids = tmdb_complete_data.get("external_ids", {})
                if isinstance(external_ids, dict):
                    remote_imdb_id = external_ids.get("imdb_id")
                    remote_tvdb_id = external_ids.get("tvdb_id")
                    if not imdb_id and isinstance(remote_imdb_id, str):
                        imdb_id = remote_imdb_id
                    if isinstance(remote_tvdb_id, int) and resolved_tvdb_id is None:
                        resolved_tvdb_id = remote_tvdb_id

        tasks: dict[str, asyncio.Task[Any]] = {}

        # only add tvdb task if we're in a series and we have imdb or tvdb id
        if media_type is MediaType.SERIES and (imdb_id or resolved_tvdb_id):
            tasks["tvdb_data"] = asyncio.create_task(
                self.parse_tvdb_data(imdb_id, resolved_tvdb_id)
            )

        # `tmdb_genres` and `original_language` describe the search row that was
        # selected, which is not the record a manually entered TMDB ID resolves
        # to. Prefer the fetched record whenever we have one, or an anime found
        # by manual ID silently skips the AniList lookup.
        animation_id = TMDBGenreIDsMovies.ANIMATION.value
        genre_ids = {getattr(genre, "value", genre) for genre in tmdb_genres}
        anime_language = original_language
        if tmdb_complete_data:
            raw_genres = tmdb_complete_data.get("genres")
            if isinstance(raw_genres, list):
                genre_ids = {
                    entry["id"]
                    for entry in raw_genres
                    if isinstance(entry, dict) and isinstance(entry.get("id"), int)
                }
            fetched_language = tmdb_complete_data.get("original_language")
            if isinstance(fetched_language, str) and fetched_language:
                anime_language = fetched_language

        # parse anime if needed
        if animation_id in genre_ids and anime_language == "ja":
            tasks["ani_list_data"] = asyncio.create_task(
                self.parse_ani_list(tmdb_title, tmdb_year)
            )

        results: dict[str, dict[str, Any]] = {}

        results["resolved_ids"] = {
            "success": True,
            "result": {
                "imdb_id": imdb_id or None,
                "tvdb_id": resolved_tvdb_id,
            },
        }

        # add complete TMDB data to results
        if tmdb_complete_data:
            results["tmdb_complete_data"] = {
                "success": True,
                "result": tmdb_complete_data,
            }

        if media_type is MediaType.SERIES and not (imdb_id or resolved_tvdb_id):
            results["tvdb_data"] = {
                "success": False,
                "error": "A TVDB ID could not be located for this series.",
            }

        for key, task in tasks.items():
            try:
                result = await task
                if key == "tvdb_data" and not isinstance(result, dict):
                    results[key] = {
                        "success": False,
                        "error": "TVDB returned no metadata for this series.",
                    }
                    continue
                results[key] = {"success": True, "result": result}
            except Exception as e:
                results[key] = {"success": False, "error": str(e)}
        return results

    async def parse_tvdb_data(
        self, imdb_id: str | None, tvdb_id: int | None
    ) -> dict[str, Any] | None:
        tvdb_parse = self._get_tvdb_client()

        # if we have imdb_id but failed to detect tvdb_id we'll use tvdb api to find the id
        if not tvdb_id and imdb_id:
            find_tvdb_id = await tvdb_parse.search_by_remote_id(imdb_id)
            if find_tvdb_id and isinstance(find_tvdb_id, list):
                first_result = find_tvdb_id[0]
                if isinstance(first_result, dict):
                    tvdb_id_data = first_result.get("movie", first_result.get("series"))
                    if isinstance(tvdb_id_data, dict):
                        remote_tvdb_id = tvdb_id_data.get("id")
                        if isinstance(remote_tvdb_id, int):
                            tvdb_id = remote_tvdb_id

        # if we failed to determine tvdb id log it and return early
        if not tvdb_id:
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                f"Failed to determine TVDB_ID from API (IMDbID = {imdb_id}, TVDBID = {tvdb_id})",
            )
            return None

        # now we can extensively parse the data from the API
        if tvdb_id:
            # get the main series data (it will have a default type)
            raw_series_data = await tvdb_parse.get_series_extended(tvdb_id)

            if not isinstance(raw_series_data, dict):
                return None
            series_data = cast(dict[str, Any], raw_series_data)

            # extract available season types from the series data
            available_season_types: list[TVDBSeasonType] = []
            season_types_data = series_data.get("seasonTypes", [])

            # use enum's mapping functionality to convert TVDB data to our enums
            for season_type_info in (
                season_types_data if isinstance(season_types_data, list) else []
            ):
                season_type_enum = (
                    TVDBSeasonType.from_tvdb_season_type_info(season_type_info)
                    if isinstance(season_type_info, dict)
                    else None
                )
                if season_type_enum and season_type_enum not in available_season_types:
                    available_season_types.append(season_type_enum)

            # if no recognized season types found, fall back to our default main types
            if not available_season_types:
                LOG.warning(
                    LOG.LOG_SOURCE.BE,
                    f"No recognized season types found in series data for {tvdb_id}, using default types",
                )
                available_season_types = TVDBSeasonType.get_main_types()
            else:
                type_names = [st.display_name for st in available_season_types]
                LOG.info(
                    LOG.LOG_SOURCE.BE,
                    f"Available season types for series {tvdb_id}: {', '.join(type_names)}",
                )

            # get the default episodes (aired/official order) from the main series data
            # with meta="episodes", this will always include episodes
            default_episodes = series_data.get("episodes", [])
            if not isinstance(default_episodes, list):
                default_episodes = []

            # we have episodes in main data, fetch additional orderings for other season types
            LOG.info(
                LOG.LOG_SOURCE.BE,
                f"Using episodes from main series data, fetching additional orderings for series {tvdb_id}...",
            )

            async def fetch_episodes_for_type(
                season_type: TVDBSeasonType,
            ) -> list[dict[str, Any]]:
                """Fetch episodes for a specific season type"""
                try:
                    # for aired/official episodes, we already have them from main data, skip
                    if season_type.api_param == "official":
                        return default_episodes

                    episodes_response = await tvdb_parse.get_series_episodes(
                        tvdb_id,
                        season_type=season_type.api_param,
                    )

                    if isinstance(episodes_response, dict):
                        episodes = episodes_response.get("episodes")
                    else:
                        episodes = None
                    if isinstance(episodes, list):
                        LOG.info(
                            LOG.LOG_SOURCE.BE,
                            f"Fetched {len(episodes)} episodes for {season_type.display_name} "
                            f"(type {season_type.type_id}) for series {tvdb_id}",
                        )
                        return cast(list[dict[str, Any]], episodes)
                    else:
                        LOG.warning(
                            LOG.LOG_SOURCE.BE,
                            f"No episodes found for {season_type.display_name} "
                            f"(type {season_type.type_id}) for series {tvdb_id}",
                        )
                        return []

                except Exception as e:
                    LOG.error(
                        LOG.LOG_SOURCE.BE,
                        f"Failed to fetch episodes for {season_type.display_name} "
                        f"(type {season_type.type_id}) for series {tvdb_id}: {e}",
                    )
                    return []

            # create async tasks for available season types that need separate fetching
            # (Official/Aired episodes are already in default_episodes from main series data)
            additional_types = [
                st for st in available_season_types if st.api_param != "official"
            ]
            tasks: dict[int, asyncio.Task[list[dict[str, Any]]]] = {}
            for season_type in additional_types:
                tasks[season_type.type_id] = asyncio.create_task(
                    fetch_episodes_for_type(season_type)
                )

            # execute additional tasks concurrently (if any)
            if tasks:
                results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            else:
                results = []

            # build episodes_by_type dictionary for all available season types
            episodes_by_type: dict[int, dict[str, str | list[dict[str, Any]]]] = {}
            type_summary: list[str] = []

            # process all available season types
            additional_results_index = 0
            for season_type in available_season_types:
                if season_type.api_param == "official":
                    # use episodes from main series data
                    episodes_by_type[season_type.type_id] = {
                        "type_name": season_type.display_name,
                        "type": season_type.api_param,
                        "episodes": default_episodes,
                    }
                    type_summary.append(
                        f"{season_type.display_name}: {len(default_episodes)} episodes"
                    )
                else:
                    # use episodes from additional async results
                    if additional_results_index < len(results):
                        result = results[additional_results_index]
                        if (
                            result
                            and not isinstance(result, Exception)
                            and isinstance(result, list)
                        ):
                            episodes_by_type[season_type.type_id] = {
                                "type_name": season_type.display_name,
                                "type": season_type.api_param,
                                "episodes": result,
                            }
                            count = len(result)
                            type_summary.append(
                                f"{season_type.display_name}: {count} episodes"
                            )
                        elif isinstance(result, Exception):
                            LOG.error(
                                LOG.LOG_SOURCE.BE,
                                f"Exception fetching {season_type.display_name}: {result}",
                            )
                    additional_results_index += 1

            # add the episodes by type to the series data
            if episodes_by_type:
                series_data["episodes_by_type"] = episodes_by_type

                LOG.info(
                    LOG.LOG_SOURCE.BE,
                    f"Enhanced TVDB data for series {tvdb_id} with episode types: "
                    f"{', '.join(type_summary)}",
                )
            else:
                LOG.warning(
                    LOG.LOG_SOURCE.BE,
                    f"No enhanced episode data could be fetched for series {tvdb_id}",
                )

            return series_data

        return None

    def _get_tvdb_client(self) -> AsyncTVDBClient:
        if self._tvdb_client is None:
            self._tvdb_client = AsyncTVDBClient(
                TVDBClient(self._get_tvdb_k(), self.timeout)
            )
        return self._tvdb_client

    @staticmethod
    def _validate_tmdb_id(media_id: str | int) -> str:
        if isinstance(media_id, bool):
            raise MediaSearchError("TMDB ID must be a decimal number.")
        value = str(media_id).strip()
        if not value or not value.isdecimal():
            raise MediaSearchError("TMDB ID must be a decimal number.")
        try:
            return str(int(value))
        except ValueError as error:
            raise MediaSearchError("TMDB ID is too large to be valid.") from error

    async def parse_ani_list(
        self, tmdb_title: str, tmdb_year: int
    ) -> dict[str, Any] | None:
        matcher = MatchAnilistTitle(tmdb_title, tmdb_year, self.timeout)
        best_match = await matcher.match()
        if best_match:
            # {'id': 21519, 'idMal': 32281, 'title': {'romaji': 'Kimi no Na wa.', 'english': 'Your Name.', 'native': '君の名は。'}, 'seasonYear': 2016, 'episodes': 1}
            return best_match
        return None

    @staticmethod
    def _get_tmdb_k() -> str:
        # cSpell:disable
        k = b"eJwzT7MwNTVOsTA0ME4xTjM2NjIzMzIzTjU3sjQ2MUi2TAYAgTIH3A=="
        # cSpell:enable
        return zlib.decompress(base64.b64decode(k)).decode("ascii")

    @staticmethod
    def _get_tvdb_k() -> str:
        # cSpell:disable
        k = (
            b"MDEwMDExMTAwMTAxMDEwMDAxMDExMDAxMDAxMTAwMDAwMTAwMTEwMTAwMTEwMDEwMDE"
            b"wMTEwMDEwMDExMDEwMTAxMDAxMTAxMDEwMTAxMDAwMTAwMDEwMTAxMTEwMTAwMDEwMTEwMTA"
            b"wMTAwMDExMTAxMDAwMTAxMDAxMTAxMDEwMTAwMTEwMTAxMDAwMDExMDAxMTAwMDAwMDExMDA"
            b"wMDAxMDExMDEwMDEwMTAxMDAwMTEwMDExMTAwMTEwMTAxMDEwMDExMDAwMTAxMDExMTAxMDA"
            b"xMDAxMDAxMTAxMDEwMTAwMTEwMTAxMDEwMTAwMDEwMDAwMDEwMTExMDEwMDAxMDAxMTEwMDEw"
            b"MTAxMDAwMTEwMTAxMTAwMTEwMTAxMDEwMTEwMTAwMTEwMTAxMDAxMDAxMTAxMDExMTAxMTEwM"
            b"TAwMTExMDAxMTAxMDEwMDExMDEwMDAwMTEwMTEwMDAxMDAxMTEwMDEwMTAxMDAwMTAwMTAxMDAxMTAxMDEx"
        )
        # cSpell:enable
        binary_bytes = base64.b64decode(k)
        b64_bytes = bytes(
            int(binary_bytes[i : i + 8], 2) for i in range(0, len(binary_bytes), 8)
        )
        return base64.b64decode(b64_bytes).decode()


class MatchAnilistTitle:
    def __init__(self, title: str, year: int, timeout: int = 60) -> None:
        self.title = title
        self.year = year
        self.timeout = max(1, timeout)
        self.data: dict[str, Any] | None = None

    async def parse_ani_list(self, tmdb_title: str) -> dict[str, Any]:
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
            timeout=self.timeout,
        )
        response.raise_for_status()
        response_json = response.json()
        return cast(dict[str, Any], response_json)

    def normalize_text(self, text: str) -> str:
        """Normalize text by removing accents, lowercasing, and stripping non-alphanumeric characters."""
        text = unidecode(text.lower())
        return re.sub(r"[^a-z0-9]", "", text)

    def filter_by_year(
        self, media: list[dict[str, Any]], year: int
    ) -> list[dict[str, Any]]:
        """Filter media by the exact year."""
        return [anime for anime in media if anime.get("seasonYear") == year]

    def get_best_match(
        self, media: list[dict[str, Any]], search_name: str
    ) -> dict[str, Any] | None:
        """Find the best match for a title using fuzzy string matching."""
        search_name_normalized = self.normalize_text(search_name)
        best_match: dict[str, Any] | None = None
        highest_score = 0.0

        for anime in media:
            for _title_type, title in anime["title"].items():
                if title:
                    title_normalized = self.normalize_text(title)
                    score = fuzz.ratio(search_name_normalized, title_normalized)

                    if score > highest_score:
                        highest_score = score
                        best_match = anime

        return best_match

    async def match(self) -> dict[str, Any] | None:
        """Match the anime title from the filtered data."""
        # fetch the data asynchronously
        response_data = await self.parse_ani_list(self.title)
        self.data = response_data

        # filter by year
        if self.data is None:
            return None

        api_data = self.data.get("data")
        page_data = api_data.get("Page") if isinstance(api_data, dict) else None
        media = page_data.get("media") if isinstance(page_data, dict) else None
        if not isinstance(media, list):
            return None

        filtered_media = self.filter_by_year(
            cast(list[dict[str, Any]], media), self.year
        )

        # find best match
        if filtered_media:
            return self.get_best_match(filtered_media, self.title)
        return None
