"""Showing a run in a terminal, and asking its questions there.

`ConsoleSink` renders the workflow's events: stage headings and log lines on
stdout, warnings and errors on stderr, and progress on one line that rewrites
itself when stdout is a terminal (and is left out when it is not, so a log
file is not flooded with it).

`TerminalPrompter` is the `ask` an interactive run uses. It puts each kind of
decision the way a person can answer it at a prompt: a numbered choice, a
yes/no, or a value per item. Ending the input (Ctrl-D / Ctrl-Z) declines.
"""

from __future__ import annotations

import re
import sys
from typing import Any, TextIO

from nfoforge.core.workflow.decisions import DECLINED, Decision, DecisionKind
from nfoforge.core.workflow.events import (
    Event,
    LogLevel,
    LogLine,
    ProgressEvent,
    StageStarted,
)

_YES_NO = {
    DecisionKind.CONTINUE_WITHOUT_TVDB,
    DecisionKind.RENAME,
    DecisionKind.SCREENSHOTS,
    DecisionKind.MULTI_SEASON_PACK,
    DecisionKind.DUPES_FOUND,
    DecisionKind.DUPE_CHECK_FAILED,
    DecisionKind.TORRENT_OVERWRITE,
}
_EPISODE = re.compile(r"^\s*s?(\d+)\s*(?:e|x|\s)\s*(\d+)\s*$", re.IGNORECASE)
_SHOWN = 20
"""At most this many items of a list are printed with a question."""


def is_interactive(
    stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout, no_input: bool = False
) -> bool:
    """Whether a question can be put to somebody.

    It needs both ends of a terminal: something to read the answer from, and
    somewhere the question is visible. A piped stdout has nobody watching it,
    and prompting there would stall on a question nobody can see.
    """
    if no_input:
        return False
    return bool(stdin.isatty()) and bool(stdout.isatty())


class ConsoleSink:
    def __init__(
        self,
        out: TextIO = sys.stdout,
        err: TextIO = sys.stderr,
        *,
        quiet: bool = False,
    ) -> None:
        self.out = out
        self.err = err
        self.quiet = quiet
        self._live = bool(getattr(out, "isatty", lambda: False)())
        self._progress_open = False
        self.shown_errors: set[str] = set()
        """Errors already printed, so the closing report does not repeat them."""

    def _end_progress(self) -> None:
        if self._progress_open:
            self.out.write("\n")
            self._progress_open = False

    def emit(self, event: Event, /) -> None:
        if isinstance(event, ProgressEvent):
            if self.quiet or not self._live:
                return
            text = event.message
            if event.current is not None and event.total:
                text += f" ({event.current}/{event.total})"
            elif event.percent is not None:
                text += f" {event.percent:.0f}%"
            self.out.write(f"\r\x1b[2K{text}")
            self.out.flush()
            self._progress_open = True
            return

        if isinstance(event, StageStarted):
            if not self.quiet:
                self._end_progress()
                self.out.write(f"== {event.stage.replace('_', ' ')} ==\n")
            return

        if isinstance(event, LogLine):
            if event.level is LogLevel.DEBUG:
                return
            self._end_progress()
            if event.level in (LogLevel.WARNING, LogLevel.ERROR):
                # keep the two streams in order when both go to one place
                self.out.flush()
                self.err.write(f"{event.level}: {event.message}\n")
                if event.level is LogLevel.ERROR:
                    self.shown_errors.add(event.message)
            elif not self.quiet:
                self.out.write(f"{event.message}\n")

    def finish(self) -> None:
        self._end_progress()
        self.out.flush()


class TerminalPrompter:
    """Answers a run's decisions by asking at the terminal."""

    def __init__(self, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
        self.stdin = stdin
        self.stdout = stdout

    def _say(self, text: str) -> None:
        self.stdout.write(text + "\n")

    def _read(self, prompt: str) -> str | None:
        self.stdout.write(prompt)
        self.stdout.flush()
        line = self.stdin.readline()
        if not line:  # end of input
            self.stdout.write("\n")
            return None
        return line.strip()

    def _list(self, items: list[str]) -> None:
        for item in items[:_SHOWN]:
            self._say(f"  {item}")
        if len(items) > _SHOWN:
            self._say(f"  ... and {len(items) - _SHOWN} more")

    def __call__(self, decision: Decision) -> Any:
        self._say("")
        self._say(decision.prompt)
        kind = decision.kind
        if kind is DecisionKind.SEARCH_RESULT:
            return self._choose(decision)
        if kind in _YES_NO:
            for key in ("matches", "files"):
                shown = decision.context.get(key)
                if isinstance(shown, dict):
                    self._list([f"{src} -> {dst}" for src, dst in shown.items()])
                elif isinstance(shown, list):
                    self._list([str(item) for item in shown])
            return self._yes_no(bool(decision.default))
        if kind is DecisionKind.MAL_ID:
            return self._number("MyAnimeList ID (empty to skip): ")
        if kind is DecisionKind.PROMPT_TOKENS:
            return self._values(decision.context.get("tokens", []), "{}: ")
        if kind is DecisionKind.EPISODE_MAPPING:
            return self._episodes(decision.context.get("files", []))
        answer = self._read("> ")
        return DECLINED if answer is None else answer

    def _choose(self, decision: Decision) -> Any:
        options = list(decision.options)
        for index, option in enumerate(options, start=1):
            marker = "*" if option == decision.default else " "
            self._say(f" {marker}{index:>3}. {decision.context.get(option, option)}")
        hint = " (Enter for *)" if decision.default in options else ""
        while True:
            answer = self._read(f"Choose 1-{len(options)}{hint}, or q to stop: ")
            if answer is None or answer.lower() == "q":
                return DECLINED
            if not answer and decision.default in options:
                return decision.default
            if answer.isdecimal() and 1 <= int(answer) <= len(options):
                return options[int(answer) - 1]
            self._say("Not one of the choices.")

    def _yes_no(self, default: bool) -> Any:
        suffix = "[Y/n]" if default else "[y/N]"
        while True:
            answer = self._read(f"{suffix} ")
            if answer is None:
                return DECLINED
            if not answer:
                return default
            if answer.lower() in {"y", "yes"}:
                return True
            if answer.lower() in {"n", "no"}:
                return False
            self._say("Answer y or n.")

    def _number(self, prompt: str) -> Any:
        while True:
            answer = self._read(prompt)
            if answer is None:
                return DECLINED
            if not answer:
                return None
            if answer.isdecimal():
                return int(answer)
            self._say("Enter a number.")

    def _values(self, names: list[str], prompt: str) -> Any:
        values: dict[str, str] = {}
        for name in names:
            answer = self._read(prompt.format(name))
            if answer is None:
                return DECLINED
            values[name] = answer
        return values

    def _episodes(self, files: list[str]) -> Any:
        self._say("Give each file's season and episode, e.g. S01E02 or 1 2.")
        mapping: dict[str, dict[str, int]] = {}
        for name in files:
            while True:
                answer = self._read(f"{name}: ")
                if answer is None:
                    return DECLINED
                match = _EPISODE.match(answer)
                if match:
                    mapping[name] = {
                        "season": int(match.group(1)),
                        "episode": int(match.group(2)),
                    }
                    break
                self._say("Use S01E02 or 1 2.")
        return mapping
