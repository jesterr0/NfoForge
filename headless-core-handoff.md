# Headless Core + CLI: Handoff

Status as of 2026-09-30, for picking this up in a fresh thread. The design rationale is in `cli-and-more.md`.

## Where things stand

Everything is merged into **`refactor/headless-core`** (46 commits ahead of `dev`, CI green on every PR). It has **not** been merged into `dev`.

| Phase | What landed |
| --- | --- |
| 0 | Package renamed `src` → `nfoforge` (flat, at the repo root). Hatchling build-system. No `src` alias (**breaking for plugins**). |
| 1 | Everything outside `nfoforge/frontend` imports without Qt. `tests/test_core/test_core_is_qt_free.py` enforces it. `ConfigManager(read_only=True)`. |
| 2 | Wizard page logic moved into `nfoforge/core/`: stage routing, job save/archive, tracker checks, screenshot planning plus auto-select, movie and series rename, search/metadata merge, series episode matching. |
| 3 | Workflow models (request, events, decisions, job state), the `Workflow` engine, and one upload-stage implementation (dupes and tracker data) shared by the engine, the job queue and the Process page. |
| 4 | `[presets.NAME]` in config profiles, feeding `ReleaseRequest`. |
| 5 | `nfoforge` CLI: `upload`, `search`, `jobs list/show/answer/resume`. Docs page at `docs/view/cli/command-line.md`. |
| 6 | CLI-only users (PRs #337–#343): see below. |

### Phase 6, in PR order

- **#337** `start_ui.py` → `nfoforge/frontend/app.py`; `nfoforge-gui` gui-script. **Breaking.**
- **#338** Upload preflight (`core/workflow/preflight.py`): trackers, templates, image host, screenshot dir, TMDB key, unattended prompt tokens are checked before any work; every problem reported at once.
- **#339** (carried the build change too) `--data-dir PATH` and portable mode (a `data` folder beside the release). Resolution order: `--data-dir` → `NFOFORGE_DATA_DIR` (dev only) → portable → per-user. Every entry point goes through `nfoforge/launcher.py`, which applies `--data-dir` before anything imports the logger.
- **#340** `nfoforge setup`: data folder migration (`--import-from PATH` / `--no-import`, asks at a terminal, refuses to guess otherwise), default profile, profile upgrades (active profile preserved), template token updates (`--update-templates`). `--import-from` on a set-up folder imports like Settings does.
- **#341** `nfoforge config path` and `config check [--trackers A,B]` (`core/config_check.py`): problems exit 1; empty tracker credentials are warnings only.
- **#342** Qt optional: PySide6/qtawesome are the `gui` extra (`dev` and `build` include it). The build makes two bundles, `dist/NfoForge` (GUI + debug) and `dist/nfoforge-cli` (no Qt; contents dir `bundle-cli`, so both unpack into one folder and share a portable `data`). Release workflow uploads `NfoForge-CLI-<tag>-<platform>` too. Qt test fixtures in `tests/qt_fixtures.py`, loaded only with PySide6; CI job `without-qt`. **Breaking** for source/pip installs.
- **#343** `PluginDefinition.wizard_page` accepts `"package.module:ClassName"`, resolved by `plugins.manager.resolve_wizard_page` only in the desktop app, so a plugin with a wizard page loads in the Qt-free CLI.

Housekeeping: phase branches are deleted. `stash@{0}` (appdata layout migration) was kept.

## Architecture map

```text
nfoforge/
  launcher.py                cli() / gui(): every entry point; --data-dir first
  core/                      <- Qt-free; every interface calls this
    signals.py               ErrorSignal / ProgressSignal / FileProgressSignal protocols
    config_check.py          check_profile -> Findings (problem/warning)
    workflow/
      stages.py              Stage enum, plan_stages, next_stage (the route)
      request.py             ReleaseRequest (JSON round-trip)
      events.py              Event types + EventSink (collect/callback/log/fan-out)
      decisions.py           Decision, DecisionKind, Interactive/Safe/Unattended policies
      preflight.py           preflight_problems (run by Workflow.start)
      steps.py               one function per Stage (input ... process)
      engine.py              Workflow.start / Workflow.resume, job persistence
      upload.py              DupeCheckResult, check_dupes, dupe_decision, run_tracker_data
      presets.py             build_request (flags > preset > profile), find_preset
    metadata/resolve.py      TMDB search, lookup_metadata, apply_search_result
    series/match.py          EpisodeMatcher (all matching stages)
    rename/                  choices.py (shared), movie.py, series.py
    screenshots/plan.py      ScreenshotPlan, generate, auto_select_screenshots
    trackers/                validate.py (profile checks, resolve_tracker_names), image_hosts.py
  backend/jobs/capture.py    save_new_job, archive_completed_run, update_prepared_archive
  config/paths.py            data folder resolution (--data-dir, portable, per-user)
  config/presets.py          RunPreset, parse_presets
  cli/                       main.py, app.py (startup, PROGRAM), setup.py, console.py
  frontend/                  wizard pages: widgets + dialogs, calling core
```

## Before merging into `dev`

The test suite fakes TMDB, TVDB and trackers, so nothing below has been exercised end to end against real services except where ticked.

### Live CLI checks

Use the `testing` profile and one tracker you're happy to test against. Global options (`-c`, `--data-dir`, `-q`, `--no-input`) go **before** the command.

- [x] `nfoforge -c testing search "<movie file>"` marks the right TMDB result (source and frozen CLI)
- [x] `nfoforge -c testing config check` runs against a real profile
- [x] `setup --no-import` and `setup --import-from <old install>` on the frozen CLI
- [ ] `upload ... --trackers X --dry-run`: reports the rename, screenshots and trackers; changes nothing
- [ ] Real movie upload to one tracker with `--image-host <name>`: uploaded, injected, archived (appears in the desktop Jobs dialog)
- [ ] Real upload with the `hallowed` profile: its token replacer fills the NFO (this is the only thing that exercises a plugin token replacer headlessly)
- [ ] Series pack upload (folder): episodes matched, rename previewed, uploaded
- [ ] `--mode safe` on an ambiguous title → `jobs list --waiting` → `jobs answer <id> <tmdb key>` completes
- [ ] `--mode unattended` stops with a hint and exit code 3
- [ ] Running with `--no-input` from a pipe behaves as unattended

### Frozen builds

- [x] Both bundles build; `dist/nfoforge-cli` has no Qt files
- [ ] `dist/NfoForge/NfoForge.exe` starts (the GUI bundle was built but not launched this session)
- [ ] `nfoforge-cli.exe --data-dir <nfoforge-dev> -c hallowed config check` shows no "plugin not loaded" for hallowed

### Desktop regression pass

Phase 2 changed nearly every wizard page.

- [ ] Movie: search, rename (edit combos, preview), screenshots (basic plus comparison with crop), trackers, pre-upload, dupe check, upload
- [ ] Series pack: series match (auto-match, manual fix, Re-match All keeps typed seasons), rename, upload
- [ ] Save job, resume job, prepare job, job queue run, archive then "Add Trackers"
- [ ] Settings theme switch (the Qt mapping moved into the General settings page)
- [ ] PTP upload where the TOTP code is rejected still shows the 2FA prompt
- [ ] Hallowed profile: its wizard page appears (now resolved from a string reference)

### Plugins

- [x] `hallowed` checkout updated: `nfoforge.` imports, `wizard_page` as a string reference. Its tests pass except `test_version_matches` (its `pyproject.toml` says 2.5.2, `version.py` 2.5.3).
- [ ] Reinstall hallowed (and rebuild `bhdstudio`, which fails with a DLL error) into `%LOCALAPPDATA%\nfoforge-dev\plugins`; the installed copies are stale.
- [ ] Decide whether plugin authors need a notice beyond the CHANGELOG: `src` → `nfoforge`, and the recommended `wizard_page` string form.

Then open `refactor/headless-core` → `dev`.

## Pre-merge audit (2026-10-01)

Static checks, suite (4247 passed), leftover `src`/`start_ui` references, release workflow, and a simulated frozen-CLI load of hallowed were all clean. Four engine bugs were found and fixed on `fix/engine-resume-safety`:

- A run failing after a tracker uploaded was saved as a plain failed job, so `jobs resume` uploaded it again. It is now archived (state failed), as the GUI does.
- `Workflow.resume` refuses archives; `steps.upload` sends only to `selected_trackers` (an archive keeps image-host entries for "may have uploaded" trackers).
- A resumed job that ended with nothing to upload stayed `waiting_for_input`. It is now marked complete.
- Unattended refusals name `--answer ID=VALUE` and keep the question on the saved failed job, so `jobs answer` works. A non-numeric MAL ID answer fails cleanly.

Also fixed (#345, stacked on #344): `NOT_ATTEMPTED` now exits 5 and a partial run prints its archive id; pip installs are no longer advertised, since a built wheel has no `assets/` (only checkouts and release builds run).

Still open from the audit:

- ~~`resume` doesn't re-run preflight~~: fixed in #346 (re-checks the profile for what is still ahead; a refusal leaves the job untouched).
- Shipping a real wheel would mean moving `assets/` into the package (or hatch `force-include` plus an `asset_root()` fallback).

## Known gaps

Roughly in order of how likely they are to bite.

1. **No comparison screenshots headless.** `ReleaseRequest` has no way to name a comparison source (or script), so the engine only generates basic screenshots. It needs `comparison_source` (and optionally `comparison_script`) fields that fill `media_input.comparison_pair` in `steps.read_input`.
2. **Global options must precede the command.** `nfoforge config check --config testing` is rejected. Declaring `-c`, `--data-dir`, `-q`, `--no-input` on the subcommands too (argparse `parents`, `default=SUPPRESS`) would fix it; about 20 minutes.
3. **Image hosts.** Without `--image-host` or a preset, each tracker uses its desktop last-used host, and gets no screenshots if it has none (a warning is logged).
4. **Engine skips some interactive steps.** The overview/NFO edit and the upload/image retry prompts aren't decisions: failures retry automatically and then move on. There is no "edit the NFO before upload" headlessly.
5. **Manual crop mode** isn't supported headless; it generates without a crop and warns.
6. **Desktop-saved jobs can't be resumed headlessly.** `Workflow.resume` needs `job.request`, so jobs from the GUI are refused with "open it in NfoForge". Archives (including a run that failed after a tracker uploaded) are refused too; their remaining trackers are added from the desktop Jobs dialog.
7. **PTP 2FA** headless works only with a stored TOTP secret.
8. **`nfoforge search`** has `--query` but no `--tmdb-id`/`--imdb-id`.
9. **No presets editor in the GUI**, and no `config get/set`: profiles are hand-edited TOML (`config path` finds them, `config check` validates them).
10. **Plugin wizard pages** never run headless (by design); a plugin that still passes its page *class* can't load in the CLI at all.

Resolved this round: CLI in the builds, PySide6 as a hard dependency, plugin wizard pages blocking CLI plugin loads.

Scoped out on purpose: the Process page's dialogs and the job queue's settlement stay GUI/queue-owned. Only the upload step is shared.

## Toward a WebUI / daemon

The models were built for this, but it isn't started. Things to know:

- **Events and decisions are JSON-ready** (`Event.to_dict`, `Decision.to_dict`/`from_dict`, stable `Decision.id`). An SSE/WebSocket endpoint is just another `EventSink`. `POST /jobs/{id}/answers` maps onto `Workflow.resume(path, answers)`.
- **The job store is the queue.** `list_jobs` already reports each job's `state`, so a "Needs attention" view is jobs in `waiting_for_input`.
- **Run the engine in a thread, not on the server's event loop.** `steps.py` uses `asyncio.run(...)` for the TMDB and dupe calls, which fails inside a running loop.
- **Global state stands in the way of concurrent runs:**
  - `clear_restored_mediainfo()` (a module-level MediaInfo cache, reset on resume)
  - the `LOG` singleton
  - `ProcessBackEnd` holding per-run fields (`skip_injection`, client handles). Use one `ProcessBackEnd` per run.
  - `paths._chosen_data_dir` (set once per process by the launcher)
- **Config:** use `ConfigManager(profile, read_only=True)` for each run. The desktop app may be writing the same profile.
- **Qt-free already:** a server can depend on the base install (no `gui` extra), like the CLI does.

## Conventions for the next thread

- **Branching:** branch from `refactor/headless-core` (or `dev` after the merge). One PR per piece of work. Push to the `github` remote and open PRs with `gh` (installed at `C:\Program Files\GitHub CLI\gh.exe`, not on Git Bash's PATH).
- **Attribution:** none. No Co-Authored-By trailer or "Generated with" footer; commits are jesterr0's.
- **Breaking changes:** make them cleanly. No compatibility shims or aliases; note the break in the CHANGELOG `[Unreleased]` section.
- **Environment:** `uv sync --all-extras`, then `uv run --all-extras <tool>`. `uv sync` without extras (including the one `build.py` runs) removes the dev tools.
- **Checks before pushing:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run basedpyright`, `uv run pytest -q -p no:cacheprovider` (about 5 minutes; 4247 passed at handoff). Without Qt, about 3500 run and the rest are skipped at collection.
- **Building:** build from PowerShell, not Git Bash: Git Bash puts its own OpenSSL on PATH and PyInstaller bundles it, breaking `import ssl`. `build.py`'s `uv sync` fails if the editor's basedpyright server has files open.
- **Testing without Qt:** use a separate env (`UV_PROJECT_ENVIRONMENT=<temp>` for sync/run), and uninstall with `uv pip uninstall --python <temp>/Scripts/python.exe ...`. Plain `uv pip uninstall` ignores `UV_PROJECT_ENVIRONMENT` and hits the main `.venv`.
- **Test files need unique basenames** across `tests/` folders; there's no `__init__.py`, so duplicates collide.
- **Editing gotcha:** Python edit scripts written through a shell heredoc turn `\n` inside strings into real newlines. Write edit scripts with the file tool, using raw strings, or use the editor directly.
- **`docs/snippets/generated_templates/*.md`** get regenerated by builds and some test runs; restore them (`git checkout -- docs/snippets`) rather than committing.
