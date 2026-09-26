"""What each stage of a headless run does.

One function per `Stage`, each taking the `Run` it belongs to. They are built
from the same core functions the wizard pages call, in the same order, so a
release goes through the same decisions either way. Where a page would ask,
these raise a `Decision` through `run.decide`; where a page would show an
error, they raise `WorkflowError`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
import html
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any

from nfoforge.backend.images import ImagesBackEnd
from nfoforge.backend.media_input import MediaInputBackEnd
from nfoforge.backend.media_search import MediaSearchBackEnd
from nfoforge.backend.process import ProcessBackEnd
from nfoforge.backend.rename_encode import RenameEncodeBackEnd
from nfoforge.backend.rename_encode_series import RenameEncodeSeriesBackEnd
from nfoforge.backend.rename_files import RenameExecutor, RenamePlan
from nfoforge.backend.template_selector import TemplateSelectorBackEnd
from nfoforge.backend.upload_retry import TrackerRunOutcome
from nfoforge.backend.utils.episode_matching import rank_episode_orderings
from nfoforge.backend.utils.file_utilities import generate_unique_date_name
from nfoforge.backend.utils.media_files import filter_media_files
from nfoforge.backend.utils.title_inference import MediaTitleInferer, TitleWeight
from nfoforge.backend.utils.tmdb_reference import TmdbReference, parse_tmdb_reference
from nfoforge.backend.utils.working_dir import processing_dir
from nfoforge.context.processing_context import ProcessingContext
from nfoforge.core.metadata.resolve import (
    ReleaseIds,
    apply_search_result,
    lookup_metadata,
    metadata_errors,
    metadata_transformer_id,
    run_media_search,
    run_tmdb_id_lookup,
)
from nfoforge.core.rename.choices import quality_problem, rename_override_tokens
from nfoforge.core.rename.movie import (
    commit_movie_rename,
    detect_movie_choices,
    movie_name_problems,
    movie_rename_map,
    render_movie_name,
)
from nfoforge.core.rename.series import (
    SeriesRenameError,
    build_series_rename,
    commit_series_rename,
    detect_series_choices,
    detected_episode_claims,
    episode_token,
)
from nfoforge.core.screenshots.plan import (
    CropSource,
    auto_select_screenshots,
    generate_screenshots,
    plan_screenshots,
    resolve_crop,
)
from nfoforge.core.series.match import EpisodeMatcher, parsed_file_summary
from nfoforge.core.trackers.image_hosts import default_image_hosts
from nfoforge.core.trackers.validate import (
    missing_nfo_templates,
    multi_season_pack_warning,
    series_unsupported_trackers,
    tracker_profile_problems,
)
from nfoforge.core.workflow.decisions import (
    Decision,
    DecisionKind,
    DecisionPolicy,
    require,
)
from nfoforge.core.workflow.events import EventSink, LogLevel, LogLine, ProgressEvent
from nfoforge.core.workflow.request import ReleaseRequest
from nfoforge.core.workflow.stages import Stage
from nfoforge.core.workflow.upload import check_dupes, dupe_decision, run_tracker_data
from nfoforge.enums.media_type import MediaType
from nfoforge.enums.series import EpisodeFormat
from nfoforge.enums.tracker_selection import TrackerSelection
from nfoforge.enums.upload_process import RunPhase
from nfoforge.payloads.series import (
    build_series_release_info,
    describe_missing_upload_fields,
)

if TYPE_CHECKING:
    from nfoforge.config.config import ConfigManager


class WorkflowError(Exception):
    """A stage cannot go on, and no decision would change that."""


@dataclass(slots=True)
class Run:
    """Everything one run's stages share."""

    config: ConfigManager
    request: ReleaseRequest
    context: ProcessingContext
    policy: DecisionPolicy
    sink: EventSink
    process_backend: ProcessBackEnd
    search_backend: MediaSearchBackEnd
    images_backend: ImagesBackEnd
    stage: Stage = Stage.INPUT
    outcomes: dict[TrackerSelection, TrackerRunOutcome] = field(default_factory=dict)
    uploaded: bool = False
    """Whether anything was published, so the run is archived afterwards."""

    @property
    def settings(self) -> Any:
        return self.config.settings

    def decide(self, decision: Decision) -> Any:
        return require(self.policy, decision)

    def log(self, message: str, level: LogLevel = LogLevel.INFO) -> None:
        self.sink.emit(LogLine(message, level))

    def log_html(self, text: str) -> None:
        """A backend status line, which is HTML, as a plain log line."""
        plain = _plain(text)
        if plain:
            self.log(plain)

    def progress(
        self,
        message: str,
        *,
        current: int | None = None,
        total: int | None = None,
        percent: float | None = None,
    ) -> None:
        self.sink.emit(ProgressEvent(str(self.stage), message, current, total, percent))


class _ProgressSignal:
    """A backend progress signal that reports into the run."""

    def __init__(self, run: Run) -> None:
        self._run = run

    def emit(self, message: str, progress: float, /) -> None:
        self._run.progress(message, percent=progress)


class _FileProgressSignal:
    def __init__(self, run: Run) -> None:
        self._run = run

    def emit(self, percent: int, completed: int, total: int, /) -> None:
        self._run.progress(
            "Reading MediaInfo", current=completed, total=total, percent=percent
        )


class _ErrorSignal:
    def __init__(self, run: Run) -> None:
        self._run = run

    def emit(self, message: str, /) -> None:
        self._run.log(message, LogLevel.ERROR)


_TAG = re.compile(r"<[^>]+>")


def _plain(text: str) -> str:
    """The backend's HTML status lines, as plain text."""
    return html.unescape(_TAG.sub("", text.replace("<br />", "\n"))).strip()


# --------------------------------------------------------------------------
# input
# --------------------------------------------------------------------------
def collect_media_files(input_path: Path) -> list[Path]:
    """The release's video files, in a stable order.

    The same filter the input page applies: subtitles, NFOs and samples are
    not episodes. The rename step still moves sidecars with their episode.
    """
    if input_path.is_file():
        if not filter_media_files([input_path]):
            raise WorkflowError(f"Not a supported media file: {input_path}")
        return [input_path]
    if not input_path.is_dir():
        raise WorkflowError(f"Input does not exist: {input_path}")
    files = sorted(filter_media_files(sorted(input_path.rglob("*"))))
    if not files:
        raise WorkflowError(f"No supported video files found in {input_path}")
    return files


def read_input(run: Run) -> None:
    media_input = run.context.media_input
    input_path = run.request.path.expanduser()
    files = collect_media_files(input_path)

    media_input.input_path = input_path
    media_input.file_list[:] = files
    media_input.working_dir = processing_dir(
        run.settings.general.working_dir
    ) / generate_unique_date_name(input_path.stem)

    run.log(f"Reading {len(files)} file(s) from {input_path}")
    parsed, failures = MediaInputBackEnd(_FileProgressSignal(run)).get_media_info_files(
        files
    )
    if failures:
        # the input page refuses too: a file MediaInfo cannot read cannot be
        # described, sized or renamed
        details = "\n".join(f"  {path}: {reason}" for path, reason in failures.items())
        raise WorkflowError(f"MediaInfo could not read:\n{details}")
    media_input.file_list_mediainfo.update(parsed)


# --------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------
def _describe(item: Mapping[str, Any]) -> str:
    year = item.get("year")
    kind = item.get("media_type") or ""
    return f"{item.get('title')}{f' ({year})' if year else ''} [{kind}]"


def _equally_good(results: Mapping[str, Mapping[str, Any]], key: str) -> list[str]:
    """Other results sharing the chosen one's title and year -- a remake."""
    chosen = results[key]
    title = str(chosen.get("title") or "").casefold()
    return [
        other
        for other, item in results.items()
        if other != key
        and str(item.get("title") or "").casefold() == title
        and item.get("year") == chosen.get("year")
    ]


def _choose_result(
    run: Run, results: Mapping[str, Mapping[str, Any]], query: str
) -> str:
    """The search result this release is.

    The closest title-and-year match is taken when it is unambiguous: the
    search page pre-selects the same one. It is asked about when there is no
    confident match or when another result shares its title and year.
    """
    key = MediaSearchBackEnd.best_match_key(query, results)
    if key is not None and not _equally_good(results, key):
        return key
    reason = (
        f"None of the {len(results)} TMDB results for {query!r} is a confident match."
        if key is None
        else f"TMDB has several results for {query!r} with the same title and year."
    )
    return str(
        run.decide(
            Decision(
                DecisionKind.SEARCH_RESULT,
                f"{reason} Which one is this release?",
                options=tuple(results),
                default=key,
                hint="pass --tmdb-id to identify the release directly",
                context={name: _describe(item) for name, item in results.items()},
            )
        )
    )


def _search(run: Run) -> tuple[str, dict[str, Any]]:
    """Find the release on TMDB; returns the chosen result key and its row."""
    backend = run.search_backend
    mode = run.settings.general.media_search_mode

    if run.request.tmdb_id:
        reference = parse_tmdb_reference(run.request.tmdb_id) or TmdbReference(
            tmdb_id=run.request.tmdb_id.strip(), media_type=None
        )
        results = run_tmdb_id_lookup(backend, reference, mode).results
        if not results:
            raise WorkflowError(f"TMDB has no record for {run.request.tmdb_id!r}")
        key = next(iter(results))
        return key, results[key]

    input_path = run.context.media_input.require_input_path()
    try:
        inference = MediaTitleInferer().infer(
            input_path, video_files=tuple(run.context.media_input.file_list)
        )
    except Exception as error:
        raise WorkflowError(
            f"Could not work out a title to search for from {input_path.name}: {error}"
        ) from error
    # A title read only off enclosing folders ("downloads", "media") can still
    # produce one confident-looking hit; the release itself has to name it.
    if max((score for _title, score in inference.candidates), default=0) < (
        TitleWeight.VIDEO_FILENAME
    ):
        raise WorkflowError(
            f"The title {inference.title!r} came from the folder names around "
            f"{input_path.name}, not the release itself. Pass --tmdb-id."
        )

    run.log(f"Searching TMDB for {inference.title!r}")
    results = run_media_search(
        backend,
        inference.title,
        input_path,
        tuple(run.context.media_input.file_list),
        mode,
    ).results
    if not results:
        raise WorkflowError(f"TMDB has no results for {inference.title!r}")
    key = _choose_result(run, results, inference.title)
    return key, results[key]


def identify(run: Run) -> None:
    _key, item = _search(run)
    ids = ReleaseIds(
        # what the search page's ID entries show for the chosen row
        imdb_id=run.request.imdb_id or str(item.get("imdb_id") or ""),
        tmdb_id=run.request.tmdb_id or str(item.get("tmdb_id") or ""),
        tvdb_id=run.request.tvdb_id or "",
    )
    context = run.context
    apply_search_result(context, item, ids)
    run.log(f"Identified as {_describe(item)}")

    media_data = asyncio.run(
        lookup_metadata(
            run.search_backend,
            item,
            ids,
            config=run.config,
            context=context,
            transformer_id=metadata_transformer_id(
                run.settings, run.config.plugin_manager
            ),
        )
    )

    def ask_mal_id() -> int | None:
        answer = run.decide(
            Decision(
                DecisionKind.MAL_ID,
                "AniList has this release but no MyAnimeList ID. Enter it, or "
                "leave it empty to skip.",
            )
        )
        return int(answer) if answer else None

    apply_search_result(
        context, item, ids, media_data=media_data, ask_mal_id=ask_mal_id
    )

    errors = metadata_errors(media_data)
    if errors.transformer:
        run.log(
            f"Metadata transformer failed, TMDb data is used: {errors.transformer}",
            LogLevel.WARNING,
        )
    if context.media_search.media_type is MediaType.SERIES and errors.tvdb:
        if not run.decide(
            Decision(
                DecisionKind.CONTINUE_WITHOUT_TVDB,
                f"TVDB metadata could not be loaded ({errors.tvdb}). Continue and "
                "map episodes by hand?",
            )
        ):
            raise WorkflowError(f"TVDB metadata could not be loaded: {errors.tvdb}")


# --------------------------------------------------------------------------
# series episode matching
# --------------------------------------------------------------------------
def _release_format(type_data: Mapping[str, Any]) -> EpisodeFormat:
    order = f"{type_data.get('type', '')} {type_data.get('type_name', '')}".lower()
    if "absolute" in order:
        return EpisodeFormat.ANIME_ABSOLUTE
    if "dvd" in order:
        return EpisodeFormat.DVD
    return EpisodeFormat.STANDARD


def match_episodes(run: Run) -> None:
    media_input = run.context.media_input
    tvdb_data = run.context.media_search.tvdb_data or {}
    matcher = EpisodeMatcher(
        episodes_by_type=dict(tvdb_data.get("episodes_by_type") or {}),
        show_title=run.context.media_search.title,
    )
    files = list(media_input.file_list)

    series_format = media_input.series_episode_format
    if matcher.episodes_by_type:
        ranked = rank_episode_orderings(
            [parsed_file_summary(matcher.parse(path)) for path in files],
            matcher.episodes_by_type,
            allow_absolute=series_format is EpisodeFormat.ANIME_ABSOLUTE,
        )
        best = ranked[0].type_id if ranked else next(iter(matcher.episodes_by_type))
        matcher.use_ordering(best)
        if series_format is EpisodeFormat.STANDARD:
            series_format = _release_format(matcher.episodes_by_type[best])
    matcher.series_format = series_format
    matcher.match_files(files)

    # a single file whose name carries no numbering can be told them
    if (
        len(files) == 1
        and run.request.season is not None
        and run.request.episode is not None
    ):
        season, episode = run.request.season, run.request.episode
        data = matcher.available_episodes.get(season, {}).get(episode)
        if data is None:
            matcher.store_unverified_parse(files[0], season, episode)
        else:
            matcher.store_mapping(files[0], season, episode, data, 1.0, "given")

    unmapped = [path for path in files if path not in matcher.mappings]
    if unmapped:
        answers = run.decide(
            Decision(
                DecisionKind.EPISODE_MAPPING,
                f"{len(unmapped)} file(s) could not be matched to an episode.",
                hint="pass --season and --episode for a single file",
                context={"files": [path.name for path in unmapped]},
            )
        )
        by_name = {path.name: path for path in unmapped}
        for name, numbers in dict(answers or {}).items():
            path = by_name.get(name)
            if path is not None:
                matcher.store_unverified_parse(
                    path, int(numbers["season"]), int(numbers["episode"])
                )
        still = [path.name for path in unmapped if path not in matcher.mappings]
        if still:
            raise WorkflowError("No episode given for: " + ", ".join(still))

    media_input.series_episode_map = dict(matcher.mappings)
    media_input.series_episode_format = series_format
    missing = describe_missing_upload_fields(build_series_release_info(media_input))
    if missing:
        raise WorkflowError(missing)
    run.log(f"Matched {len(files)} file(s) to episodes")


# --------------------------------------------------------------------------
# rename
# --------------------------------------------------------------------------
def _execute_rename(run: Run, plan: RenamePlan) -> None:
    moves = {str(src): str(trg) for src, trg in plan.file_targets.items()}
    if not run.request.rename and not run.decide(
        Decision(
            DecisionKind.RENAME,
            f"Rename {len(moves)} file(s)?",
            hint="pass --rename to confirm, or --no-rename to skip renaming",
            context={"files": moves},
        )
    ):
        run.log("Rename declined; files keep their names", LogLevel.WARNING)
        return
    if run.request.dry_run:
        for src, trg in moves.items():
            run.log(f"Would rename {src} -> {trg}")
        return

    result = RenameExecutor.execute(plan)
    media_input = run.context.media_input
    if result.path_mapping or result.updated_input_path != media_input.input_path:
        media_input.apply_rename_mapping(result.path_mapping, result.updated_input_path)
    if not result.success:
        raise WorkflowError(result.message or "The rename failed")
    media_input.require_existing_media_paths(include_comparison=True)
    run.log(f"Renamed {len(moves)} file(s)")


def rename(run: Run) -> None:
    context, settings = run.context, run.settings
    media_input = context.media_input
    is_series = context.media_search.media_type is MediaType.SERIES

    choices = (
        detect_series_choices(context, settings)
        if is_series
        else detect_movie_choices(context, settings)
    )
    tokens = rename_override_tokens(choices) | dict(run.request.token_overrides)
    problem = quality_problem(choices.quality, media_input)
    if problem:
        raise WorkflowError(problem)

    if is_series:
        series_backend = RenameEncodeSeriesBackEnd(
            context.flat_filters, context.custom_edition_info, context.custom_cut_names
        )
        series_backend.override_tokens = tokens
        try:
            targets = build_series_rename(
                context,
                settings,
                series_backend,
                token=run.request.filename_token or episode_token(context, settings),
                episode_claims=detected_episode_claims(context, settings),
            )
        except SeriesRenameError as error:
            raise WorkflowError(str(error)) from error
        for path in targets.failed:
            run.log(f"No name could be generated for {path.name}", LogLevel.WARNING)
        if not targets.is_empty:
            _execute_rename(
                run,
                RenamePlan.build(
                    targets.files,
                    media_input.input_path,
                    directory_targets=targets.directories,
                ),
            )
        commit_series_rename(context, choices, tokens)
        return

    backend = RenameEncodeBackEnd(
        context.flat_filters, context.custom_edition_info, context.custom_cut_names
    )
    backend.override_tokens = tokens
    rendered = render_movie_name(context, settings, backend, run.request.filename_token)
    if rendered is None:
        raise WorkflowError("No filename could be generated from the token template")
    output_name = str(rendered.with_suffix(""))
    problems = movie_name_problems(output_name, media_input.file_list[0])
    if problems:
        raise WorkflowError(problems[0])
    rename_map = movie_rename_map(media_input, output_name)
    if rename_map:
        _execute_rename(run, RenamePlan.build(rename_map, media_input.input_path))
    commit_movie_rename(context, choices, tokens, output_name)


# --------------------------------------------------------------------------
# screenshots
# --------------------------------------------------------------------------
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def screenshots(run: Run) -> None:
    shared = run.context.shared_data
    chosen_dir = run.request.screenshot_dir
    if chosen_dir is not None:
        images = sorted(
            path
            for path in chosen_dir.expanduser().iterdir()
            if path.suffix.lower() in _IMAGE_SUFFIXES
        )
        if not images:
            raise WorkflowError(f"No images found in {chosen_dir}")
        shared.loaded_images = images
        shared.generated_images = False
        shared.is_comparison_images = False
        run.log(f"Using {len(images)} screenshot(s) from {chosen_dir}")
        return

    settings = run.settings
    source, script_values = resolve_crop(run.context, settings)
    if source is CropSource.MANUAL:
        run.log(
            "Manual cropping needs the desktop app; generating without a crop",
            LogLevel.WARNING,
        )
    plan = plan_screenshots(run.context, settings, script_values=script_values)
    if run.request.screenshot_count:
        plan = replace(plan, total_images=run.request.screenshot_count)
    if run.request.dry_run:
        run.log(f"Would generate {plan.total_images} screenshot(s) ({plan.mode})")
        return

    run.log(f"Generating {plan.total_images} screenshot(s) ({plan.mode})")
    code = generate_screenshots(plan, run.images_backend, _ProgressSignal(run))
    if code != 0:
        raise WorkflowError(f"Screenshot generation failed ({code})")

    shots = settings.screenshots
    images = auto_select_screenshots(
        plan.output_directory,
        comparison=plan.is_comparison,
        maximum=shots.max_required_selected,
    )
    if shots.min_required_selected and len(images) < shots.min_required_selected:
        if not run.decide(
            Decision(
                DecisionKind.SCREENSHOTS,
                f"Only {len(images)} screenshot(s) were produced; this profile "
                f"requires {shots.min_required_selected}. Continue anyway?",
            )
        ):
            raise WorkflowError("Not enough screenshots")
    shared.loaded_images = images
    shared.generated_images = True
    shared.is_comparison_images = plan.is_comparison


# --------------------------------------------------------------------------
# trackers
# --------------------------------------------------------------------------
def resolve_trackers(run: Run) -> list[TrackerSelection]:
    """The trackers named in the request. Never inferred from the profile."""
    by_selection = run.settings.trackers.by_selection()
    if not run.request.trackers:
        raise WorkflowError("No trackers were named for this release")
    known = {str(tracker).casefold(): tracker for tracker in by_selection}
    known |= {tracker.name.casefold(): tracker for tracker in by_selection}
    chosen: list[TrackerSelection] = []
    for name in run.request.trackers:
        tracker = known.get(name.strip().casefold())
        if tracker is None:
            raise WorkflowError(f"Unknown tracker {name!r}")
        if tracker not in chosen:
            chosen.append(tracker)
    order = run.settings.trackers.order
    return sorted(chosen, key=lambda t: order.index(t) if t in order else len(order))


def choose_trackers(run: Run) -> None:
    context = run.context
    trackers = resolve_trackers(run)
    by_selection = run.settings.trackers.by_selection()

    unsupported = series_unsupported_trackers(trackers, context.media_search.media_type)
    if unsupported:
        raise WorkflowError(
            "These trackers do not take series: " + ", ".join(map(str, unsupported))
        )
    problems = tracker_profile_problems(
        trackers, by_selection, TemplateSelectorBackEnd()
    )
    if problems:
        raise WorkflowError("\n".join(problems))
    missing = missing_nfo_templates(trackers, by_selection)
    if missing:
        raise WorkflowError(
            "No NFO template is assigned to: " + ", ".join(map(str, missing))
        )
    warning = multi_season_pack_warning(trackers, context)
    if warning and not run.decide(
        Decision(DecisionKind.MULTI_SEASON_PACK, f"{warning} Continue?")
    ):
        raise WorkflowError(warning)

    context.shared_data.selected_trackers = trackers
    try:
        hosts, notes = default_image_hosts(
            context,
            run.settings,
            run.config.plugin_manager,
            trackers,
            preferred=run.request.image_host,
        )
    except ValueError as error:
        raise WorkflowError(str(error)) from error
    context.shared_data.tracker_image_hosts = hosts
    for note in notes:
        run.log(f"No screenshots will be uploaded for {note}", LogLevel.WARNING)


def pre_upload(run: Run) -> None:
    """Nothing to settle headlessly: templates were checked with the trackers."""
    del run


# --------------------------------------------------------------------------
# process
# --------------------------------------------------------------------------
def _check_dupes(run: Run, trackers: list[TrackerSelection]) -> list[TrackerSelection]:
    """The trackers still going ahead once possible duplicates are settled."""
    result = asyncio.run(check_dupes(run.process_backend, run.context, trackers))
    if result.failure:
        run.log(f"Duplicate check failed: {result.failure}", LogLevel.ERROR)

    keep: list[TrackerSelection] = []
    for tracker in trackers:
        decision = dupe_decision(tracker, result)
        if decision is None or run.decide(decision):
            keep.append(tracker)
        else:
            run.log(f"Skipping {tracker}", LogLevel.WARNING)
            run.outcomes[tracker] = TrackerRunOutcome.SKIPPED
    return keep


def upload(run: Run) -> None:
    context, request = run.context, run.request
    shared = context.shared_data
    trackers = list(shared.tracker_image_hosts)

    if request.dry_run:
        run.log("Dry run: stopping before anything is uploaded")
        return

    if not request.skip_dupe_check:
        trackers = _check_dupes(run, trackers)
        shared.tracker_image_hosts = {
            tracker: shared.tracker_image_hosts[tracker] for tracker in trackers
        }
    if not trackers:
        run.log("Nothing left to upload", LogLevel.WARNING)
        return

    backend = run.process_backend
    backend.skip_injection = request.no_inject
    shared.prompt_token_answers.update(request.prompt_tokens)
    unanswered = backend.unresolved_prompt_tokens(trackers, shared.prompt_token_answers)
    if unanswered:
        answers = run.decide(
            Decision(
                DecisionKind.PROMPT_TOKENS,
                "The NFO templates ask for: " + ", ".join(unanswered),
                hint="pass --token NAME=VALUE for each",
                context={"tokens": unanswered},
            )
        )
        shared.prompt_token_answers.update(
            {token: str(value) for token, value in dict(answers or {}).items()}
        )

    if request.token_overrides:
        backend._seed_claim_overrides(context)
        context.shared_data.dynamic_data["override_tokens"] = dict(
            context.shared_data.dynamic_data.get("override_tokens") or {}
        ) | dict(request.token_overrides)

    tracker_data = run_tracker_data(context)
    for tracker in trackers:
        run.outcomes.setdefault(tracker, TrackerRunOutcome.NOT_ATTEMPTED)

    def record(tracker: TrackerSelection, outcome: TrackerRunOutcome) -> None:
        run.outcomes[tracker] = outcome

    backend.process_trackers(
        process_dict=tracker_data,
        queued_status_update=lambda tracker, status: run.log(f"{tracker}: {status}"),
        queued_text_update=lambda text: run.log_html(text),
        queued_text_update_replace_last_line=lambda text: run.progress(_plain(text)),
        progress_bar_cb=lambda percent: run.progress("Processing", percent=percent),
        caught_error=_ErrorSignal(run),
        context=context,
        run_outcome_cb=record,
        phase=RunPhase.FULL,
    )
    run.uploaded = True


STEPS: dict[Stage, Callable[[Run], None]] = {
    Stage.INPUT: read_input,
    Stage.SEARCH: identify,
    Stage.SERIES_MATCH: match_episodes,
    Stage.RENAME: rename,
    Stage.SCREENSHOTS: screenshots,
    Stage.TRACKERS: choose_trackers,
    Stage.PRE_UPLOAD: pre_upload,
    Stage.PROCESS: upload,
}
