"""`nfoforge`: run NfoForge's workflow from a terminal.

    nfoforge upload PATH --trackers AITHER,HUNO
    nfoforge upload PATH --preset bhd-encode --mode unattended
    nfoforge search PATH
    nfoforge jobs list
    nfoforge jobs answer JOB 2

Every command reads the same config profiles the desktop app uses, read-only.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys
from typing import Any, TextIO

from nfoforge.backend.jobs import JobListing, list_jobs, load_job
from nfoforge.backend.media_search import MediaSearchBackEnd
from nfoforge.backend.upload_retry import TrackerRunOutcome
from nfoforge.backend.utils.title_inference import MediaTitleInferer
from nfoforge.cli.app import CliError, load_config
from nfoforge.cli.console import ConsoleSink, TerminalPrompter, is_interactive
from nfoforge.cli.exit_codes import ExitCode
from nfoforge.config.config import ConfigManager
from nfoforge.core.metadata.resolve import run_media_search
from nfoforge.core.workflow.decisions import Decision
from nfoforge.core.workflow.engine import Workflow, WorkflowResult
from nfoforge.core.workflow.presets import PresetError, build_request, find_preset
from nfoforge.core.workflow.steps import WorkflowError, collect_media_files
from nfoforge.enums.automation import AutomationMode, JobState
from nfoforge.version import __version__

PROGRAM = "nfoforge"
_FAILED_OUTCOMES = {
    TrackerRunOutcome.UPLOAD_FAILED,
    TrackerRunOutcome.INJECTION_FAILED,
    TrackerRunOutcome.MAY_HAVE_UPLOADED,
}


# --------------------------------------------------------------------------
# arguments
# --------------------------------------------------------------------------
def _pairs(values: Sequence[str] | None, option: str) -> dict[str, str]:
    """`NAME=VALUE` arguments as a dict."""
    pairs: dict[str, str] = {}
    for item in values or ():
        name, sep, value = item.partition("=")
        if not sep or not name.strip():
            raise CliError(f"{option} expects NAME=VALUE, got {item!r}")
        pairs[name.strip()] = value
    return pairs


def parse_answer(text: str) -> Any:
    """An answer typed on the command line: yes/no, JSON, or plain text."""
    lowered = text.strip().lower()
    if lowered in {"y", "yes"}:
        return True
    if lowered in {"n", "no"}:
        return False
    try:
        return json.loads(text)
    except ValueError:
        return text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="Run NfoForge without its interface, using the same config "
        "profiles the desktop app uses.",
    )
    parser.add_argument("--version", action="version", version=str(__version__))
    parser.add_argument(
        "-c", "--config", metavar="PROFILE", help="Config profile to use."
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Report only the outcome."
    )
    parser.add_argument(
        "--no-input",
        action="store_true",
        help="Never ask anything, even at a terminal (rehearses a scheduled run).",
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    upload = commands.add_parser(
        "upload", help="Take a release from a path all the way to its trackers."
    )
    upload.add_argument("path", type=Path, metavar="PATH", help="File or folder.")
    upload.add_argument("--preset", metavar="NAME", help="Fill options from a preset.")
    upload.add_argument(
        "--trackers",
        metavar="A,B",
        help="Trackers to upload to (required unless a preset names them).",
    )
    upload.add_argument(
        "--mode",
        choices=[str(mode) for mode in AutomationMode],
        help="What to do at a question: ask (interactive, the default at a "
        "terminal), save the job to answer later (safe), or stop (unattended).",
    )
    ids = upload.add_argument_group("identifying the release")
    ids.add_argument("--tmdb-id", metavar="ID")
    ids.add_argument("--imdb-id", metavar="ID")
    ids.add_argument("--tvdb-id", metavar="ID")
    ids.add_argument("--season", type=int, metavar="N")
    ids.add_argument("--episode", type=int, metavar="N")
    naming = upload.add_argument_group("renaming and tokens")
    rename = naming.add_mutually_exclusive_group()
    rename.add_argument(
        "--rename",
        dest="rename",
        action="store_true",
        default=None,
        help="Rename the files (confirms the rename).",
    )
    rename.add_argument(
        "--no-rename", dest="rename", action="store_false", help="Keep file names."
    )
    naming.add_argument("--filename-token", metavar="TEMPLATE")
    naming.add_argument(
        "--override",
        action="append",
        metavar="NAME=VALUE",
        help="Force a file/title token's value. Repeatable.",
    )
    naming.add_argument(
        "--token",
        action="append",
        metavar="NAME=VALUE",
        help="Answer an NFO template's prompt token. Repeatable.",
    )
    shots = upload.add_argument_group("screenshots")
    shots_mode = shots.add_mutually_exclusive_group()
    shots_mode.add_argument(
        "--screenshots", type=int, metavar="N", dest="screenshot_count"
    )
    shots_mode.add_argument("--screenshot-dir", type=Path, metavar="DIR")
    shots_mode.add_argument("--no-screenshots", action="store_true", default=None)
    shots.add_argument(
        "--image-host", metavar="NAME", help='e.g. "Pixhost", or "Disabled".'
    )
    safety = upload.add_argument_group("safety")
    safety.add_argument("--skip-dupe-check", action="store_true", default=None)
    safety.add_argument("--no-inject", action="store_true", default=None)
    safety.add_argument(
        "--dry-run",
        action="store_true",
        help="Work everything out and report it; rename, generate and upload nothing.",
    )
    safety.add_argument(
        "--answer",
        action="append",
        metavar="ID=VALUE",
        help="Answer a question in advance, by decision id. Repeatable.",
    )

    search = commands.add_parser("search", help="Show what TMDB matches a release.")
    search.add_argument("path", type=Path, metavar="PATH")
    search.add_argument(
        "--query", help="Search for this instead of the inferred title."
    )

    jobs = commands.add_parser("jobs", help="List, inspect and resume saved jobs.")
    job_commands = jobs.add_subparsers(
        dest="jobs_command", metavar="ACTION", required=True
    )
    job_list = job_commands.add_parser("list", help="Saved jobs, newest first.")
    job_list.add_argument(
        "--waiting", action="store_true", help="Only jobs waiting for input."
    )
    job_show = job_commands.add_parser(
        "show", help="One job, and what it is waiting on."
    )
    job_show.add_argument("job", metavar="JOB")
    job_answer = job_commands.add_parser(
        "answer", help="Answer the question a job is waiting on, and resume it."
    )
    job_answer.add_argument("job", metavar="JOB")
    job_answer.add_argument(
        "value", nargs="?", help="The answer. Asked for at a terminal when left out."
    )
    job_resume = job_commands.add_parser(
        "resume", help="Resume a waiting or failed job."
    )
    job_resume.add_argument("job", metavar="JOB")
    job_resume.add_argument("--answer", action="append", metavar="ID=VALUE")
    return parser


# --------------------------------------------------------------------------
# reporting a run
# --------------------------------------------------------------------------
def _job_id(path: Path | None) -> str:
    return path.name if path else "?"


def report(
    result: WorkflowResult,
    out: TextIO,
    err: TextIO,
    shown_errors: set[str] | frozenset[str] = frozenset(),
) -> ExitCode:
    """Say how a run ended, and the exit code that goes with it.

    `shown_errors` were already printed as the run went; they are not
    repeated.
    """
    for tracker, outcome in result.outcomes.items():
        out.write(f"{tracker}: {str(outcome.name).replace('_', ' ').lower()}\n")

    if result.state is JobState.WAITING_FOR_INPUT:
        decision = result.decision
        job = _job_id(result.job_path)
        err.write(f"Waiting for input: {decision.prompt if decision else ''}\n")
        if decision and decision.options:
            for option in decision.options:
                err.write(f"  {option}: {decision.context.get(option, option)}\n")
        err.write(
            f"Saved as job {job}. Answer it with: {PROGRAM} jobs answer {job} VALUE\n"
        )
        return ExitCode.WAITING

    if result.state is JobState.FAILED:
        if result.error not in shown_errors:
            err.write(f"error: {result.error}\n")
        if result.job_path is not None:
            err.write(f"Saved as failed job {_job_id(result.job_path)}.\n")
        return ExitCode.REFUSED if result.decision is not None else ExitCode.FAILED

    if any(outcome in _FAILED_OUTCOMES for outcome in result.outcomes.values()):
        return ExitCode.PARTIAL
    if result.job_path is not None:
        out.write(f"Archived as job {_job_id(result.job_path)}.\n")
    return ExitCode.OK


def _workflow(
    config: ConfigManager,
    args: argparse.Namespace,
    out: TextIO,
    err: TextIO,
    interactive: bool,
) -> tuple[Workflow, ConsoleSink]:
    sink = ConsoleSink(out, err, quiet=args.quiet)
    ask = TerminalPrompter(sys.stdin, out) if interactive else None
    return Workflow(config, sink=sink, ask=ask), sink


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_upload(
    args: argparse.Namespace, config: ConfigManager, out: TextIO, err: TextIO
) -> ExitCode:
    preset = find_preset(config.settings, args.preset) if args.preset else None
    given: dict[str, Any] = {
        "path": args.path,
        "trackers": tuple(t.strip() for t in args.trackers.split(",") if t.strip())
        if args.trackers
        else None,
        "mode": AutomationMode(args.mode) if args.mode else None,
        "tmdb_id": args.tmdb_id,
        "imdb_id": args.imdb_id,
        "tvdb_id": args.tvdb_id,
        "season": args.season,
        "episode": args.episode,
        "rename": args.rename,
        "filename_token": args.filename_token,
        "token_overrides": _pairs(args.override, "--override") or None,
        "prompt_tokens": _pairs(args.token, "--token") or None,
        "screenshot_count": args.screenshot_count,
        "screenshot_dir": args.screenshot_dir,
        "no_screenshots": args.no_screenshots,
        "image_host": args.image_host,
        "skip_dupe_check": args.skip_dupe_check,
        "no_inject": args.no_inject,
        "dry_run": args.dry_run or None,
    }
    request = build_request(given, preset, preset_name=args.preset)

    interactive = is_interactive(no_input=args.no_input)
    if request.mode is AutomationMode.INTERACTIVE and not interactive:
        err.write("note: nobody can be asked here, so this run is unattended\n")
        request = build_request(
            {**given, "mode": AutomationMode.UNATTENDED},
            preset,
            preset_name=args.preset,
        )

    answers = {
        key: parse_answer(value)
        for key, value in _pairs(args.answer, "--answer").items()
    }
    workflow, sink = _workflow(config, args, out, err, interactive)
    result = workflow.start(request, answers)
    sink.finish()
    return report(result, out, err, sink.shown_errors)


def cmd_search(
    args: argparse.Namespace, config: ConfigManager, out: TextIO, _err: TextIO
) -> ExitCode:
    path = args.path.expanduser()
    try:
        files = collect_media_files(path)
    except WorkflowError as error:
        raise CliError(str(error)) from error
    query = (
        args.query or MediaTitleInferer().infer(path, video_files=tuple(files)).title
    )
    settings = config.settings
    backend = MediaSearchBackEnd(
        language=settings.general.tmdb_language,
        timeout=settings.general.timeout,
        api_key=settings.api_keys.tmdb_api_key,
    )
    result = run_media_search(
        backend, query, path, tuple(files), settings.general.media_search_mode
    )
    out.write(f"TMDB results for {query!r}:\n")
    if not result.results:
        out.write("  none\n")
        return ExitCode.FAILED
    for key, item in result.results.items():
        marker = "*" if key == result.preferred_result_key else " "
        year = item.get("year") or "????"
        out.write(
            f" {marker} tmdb {item.get('tmdb_id') or key:<9} {item.get('title')} ({year}) "
            f"[{item.get('media_type')}]\n"
        )
    out.write("* closest title and year match\n")
    return ExitCode.OK


def _jobs(config: ConfigManager) -> list[JobListing]:
    return list_jobs([Path(config.settings.general.working_dir)])


def find_job(config: ConfigManager, reference: str) -> JobListing:
    """A job by its id, or an unambiguous start of one."""
    listings = _jobs(config)
    exact = [job for job in listings if reference in {job.job_id, job.path.name}]
    matches = exact or [
        job
        for job in listings
        if job.job_id.startswith(reference) or job.path.name.startswith(reference)
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise CliError(
            f"No job {reference!r} in this profile. See: {PROGRAM} jobs list"
        )
    raise CliError(f"{reference!r} matches {len(matches)} jobs; give more of the id")


def cmd_jobs(
    args: argparse.Namespace, config: ConfigManager, out: TextIO, err: TextIO
) -> ExitCode:
    action = args.jobs_command
    if action == "list":
        listings = [
            job
            for job in _jobs(config)
            if not args.waiting or job.state is JobState.WAITING_FOR_INPUT
        ]
        if not listings:
            out.write("No saved jobs.\n")
        for job in listings:
            out.write(
                f"{job.path.name}  {job.state:<17}  {job.created_at[:16]}  {job.name}\n"
            )
        return ExitCode.OK

    job = find_job(config, args.job)
    saved = load_job(job.path)
    if action == "show":
        out.write(f"{saved.name}\n  id:    {job.path.name}\n  state: {saved.state}\n")
        if saved.stage:
            out.write(f"  stage: {saved.stage}\n")
        if saved.error:
            out.write(f"  error: {saved.error}\n")
        if saved.pending_decision:
            decision = Decision.from_dict(saved.pending_decision)
            out.write(f"  waiting on [{decision.id}]: {decision.prompt}\n")
            for option in decision.options:
                out.write(f"    {option}: {decision.context.get(option, option)}\n")
            if decision.hint:
                out.write(f"  ({decision.hint})\n")
        return ExitCode.OK

    interactive = is_interactive(no_input=args.no_input)
    answers: dict[str, Any] = {}
    if action == "answer":
        if not saved.pending_decision:
            raise CliError(f"Job {job.path.name} is not waiting on a question")
        decision = Decision.from_dict(saved.pending_decision)
        if args.value is not None:
            value: Any = parse_answer(args.value)
        elif interactive:
            value = TerminalPrompter(sys.stdin, out)(decision)
        else:
            raise CliError("Give the answer as VALUE; there is nobody to ask here")
        answers[decision.id] = value
    else:
        answers = {
            key: parse_answer(value)
            for key, value in _pairs(args.answer, "--answer").items()
        }

    workflow, sink = _workflow(config, args, out, err, interactive)
    result = workflow.resume(job.path, answers)
    sink.finish()
    return report(result, out, err, sink.shown_errors)


COMMANDS = {"upload": cmd_upload, "search": cmd_search, "jobs": cmd_jobs}


def main(
    argv: Sequence[str] | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    stdout: TextIO = out or sys.stdout
    stderr: TextIO = err or sys.stderr
    args = build_parser().parse_args(argv)

    def warn(text: str) -> None:
        stderr.write(f"warning: {text}\n")

    try:
        config = load_config(args.config, warn=warn)
        return int(COMMANDS[args.command](args, config, stdout, stderr))
    except (CliError, PresetError) as error:
        stderr.write(f"error: {error}\n")
        return int(ExitCode.FAILED)
    except KeyboardInterrupt:
        stderr.write("interrupted\n")
        return 130
