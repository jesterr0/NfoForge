# Command Line

NfoForge can run a release from a path to its trackers without the desktop app:

```bash
nfoforge upload "/media/The.Movie.2024.1080p.BluRay.x264-GRP.mkv" --trackers AITHER
```

It runs the same steps the wizard does, reading the same config profiles, and asks the same questions. When nobody is there to answer them, it stops instead of guessing.

!!! note "Running it" A release ships the command line as its own download, `nfoforge-cli` (`nfoforge-cli.exe` on Windows), separate from the desktop app and without Qt, so it runs on a server with no display or graphics libraries. From a source checkout, run `uv run nfoforge ...` (or `uv run python -m nfoforge.cli ...`); the command line does not need the `gui` extra. This page writes `nfoforge` throughout; with a release, type `nfoforge-cli` instead.

!!! warning "Plugins that use Qt" A plugin that imports Qt when it loads cannot load in the command line, which has no Qt; the command line reports it as not loaded and carries on without it. A plugin that adds a wizard page avoids this by [naming the page as a string](../plugins/plugin-system.md#wizard-pages), so its other capabilities still work here.

## First-Time Setup

If you have used the desktop app on this machine, there is nothing to do. Otherwise, run:

```bash
nfoforge setup
```

It does what the desktop app does the first time it starts:

1. Sets up the data folder, offering to import the settings of a previous NfoForge installation. The previous installation is copied from, never changed.
2. Creates a profile, if there is none.
3. Upgrades any profile written by an older NfoForge, keeping a copy of the old one in `old_configs`.
4. Offers to update templates that use tokens which have since been renamed, keeping a copy of each.

Each step does nothing when there is nothing to do, so it is safe to run again, for example after an upgrade. Other commands tell you when it is needed.

Without a terminal to ask at, say what to import up front:

| Option | What it does |
| --- | --- |
| `--import-from PATH` | Import from the previous installation in this folder. On a data folder already set up, it imports the way **Settings** does: nothing is overwritten, and anything that clashes is set aside in `migration-conflicts` |
| `--no-import` | Start fresh |
| `--update-templates` | Update templates without asking |

```bash
nfoforge --data-dir /config setup --no-import
```

## Profiles

Every command reads a config profile, read-only, so it is safe to run while the desktop app is open. With one profile it is used automatically; with several, name one:

```bash
nfoforge --config main upload ...
```

Set up trackers, templates, image hosts and torrent clients in the desktop app, or by editing the profile's `.toml` file in `config/profiles` inside the data folder. `nfoforge config path` prints where that file and the rest of the data folder are.

### Checking a Profile

```bash
nfoforge --config main config check
```

Reports everything that would stop an upload, all at once, without uploading anything:

- **Problems** stop a run: no TMDB API key, a tracker with no NFO template or with uploads disabled, a template that no longer exists, an image host switched on without its credentials, a tool set to a file that is not there, a preset naming a tracker or image host that does not exist.
- **Warnings** may be deliberate: a tracker credential left empty, or FFmpeg not being set (so no screenshots can be generated).

It checks the trackers your presets name and every tracker with a credential filled in. Name others with `--trackers A,B`. It exits with `1` when there is a problem, so it can gate a script.

Profiles are read from the same data folder the desktop app uses. To use another one, give `--data-dir` before the command, or run a portable release; see [Where Your Settings Are Kept](../getting-started/install.md#where-your-settings-are-kept).

```bash
nfoforge --data-dir /config --config main upload ...
```

## Uploading

```bash
nfoforge upload PATH --trackers AITHER,HUNO [options]
```

Trackers are never inferred from the profile: name them with `--trackers` or a [preset](#presets).

Before any work starts, the run checks everything it can without reading the release: that the trackers exist, are enabled and have an NFO template, that `--image-host` and `--screenshot-dir` are usable, and that the profile has a TMDB API key. An unattended run also checks that every prompt token the templates ask for has a `--token`. Every problem found is reported at once, and nothing is renamed, generated or uploaded.

| Option | What it does |
| --- | --- |
| `--tmdb-id`, `--imdb-id`, `--tvdb-id` | Identify the release instead of searching for it |
| `--season`, `--episode` | Numbering for a single file whose name has none |
| `--rename` / `--no-rename` | Rename the files (and confirm the rename), or keep their names |
| `--filename-token TEMPLATE` | Rename with this template instead of the profile's |
| `--override NAME=VALUE` | Force a file/title token's value (repeatable) |
| `--token NAME=VALUE` | Answer an NFO template's prompt token (repeatable) |
| `--screenshots N` / `--screenshot-dir DIR` / `--no-screenshots` | Generate N, use existing images, or none |
| `--image-host NAME` | Upload every tracker's screenshots here, e.g. `Pixhost` (`Disabled` for none) |
| `--skip-dupe-check` | Upload without checking the trackers for duplicates |
| `--no-inject` | Do not hand the torrent to any torrent client |
| `--dry-run` | Work everything out and report it; rename, generate and upload nothing |
| `--answer ID=VALUE` | Answer a question in advance (see [Questions](#questions)) |

Without `--image-host`, each tracker uses the image host it last used in the desktop app. A tracker with none uploads no screenshots, and the run says so.

Screenshots are generated as the desktop app would, then chosen automatically: evenly spaced frames, up to the profile's maximum, with each source/encode comparison pair kept together.

## Questions

Some calls are left to a person: which search result is the release, whether to rename, whether to upload past a possible duplicate, what goes in a template's prompt tokens. What happens at one depends on `--mode`:

| Mode          | At a question                                                  |
| ------------- | -------------------------------------------------------------- |
| `interactive` | Asks at the terminal. The default when there is one.           |
| `safe`        | Saves the run as a job waiting for input, and stops.           |
| `unattended`  | Stops, naming the option that answers the question in advance. |

With no terminal -- a pipe, cron, `--no-input` -- an interactive run is treated as unattended.

A search result is taken without asking when it is the clear best title-and-year match. It is asked about when no result is a confident match, when two results share a title and year (a remake), or when the title was read only from folder names.

Answer questions in advance with `--answer`, using the question's id, which every stop reports:

```bash
nfoforge upload PATH --trackers AITHER --mode unattended --answer search_result=603
```

## Jobs

A safe-mode run that stops is kept as a job, with everything done so far:

```bash
nfoforge jobs list --waiting
nfoforge jobs show 4fHb2          # what it is waiting on
nfoforge jobs answer 4fHb2 603    # answer it and carry on
```

An unattended run that stops at a question is kept too, as a failed job holding the question, so `jobs answer` works on it the same way.

A job is named by its id, or any unambiguous start of it. `jobs resume JOB --answer ID=VALUE` resumes a waiting or failed job with any answers. A finished run is archived like a desktop run, so trackers can be added to it later from the Jobs dialog. So is a run that failed after a tracker had the release: it cannot be resumed from the command line, since that could upload the release twice, but the remaining trackers can be added from the Jobs dialog.

## Presets

A preset is a named set of options, kept in the config profile. Add it to the profile's `.toml` file by hand:

```toml
[presets.bhd-encode]
trackers = ["BHD"]
image_host = "Pixhost"
screenshot_count = 6
rename = true
mode = "unattended"
token_overrides = { edition = "Directors Cut" }
```

```bash
nfoforge upload PATH --preset bhd-encode
```

An option given on the command line wins over the preset, and the preset wins over the profile. Token tables merge. A preset can set `trackers`, `image_host`, `screenshot_count`, `no_screenshots`, `rename`, `filename_token`, `mode`, `skip_dupe_check`, `no_inject`, `token_overrides` and `prompt_tokens`. A misspelled key stops the profile from loading, naming it.

## Searching

```bash
nfoforge search PATH [--query "The Movie 2024"]
```

Lists TMDB's results for the release, marking the one an upload would take.

## Exit codes

| Code | Meaning                                                      |
| ---- | ------------------------------------------------------------ |
| 0    | Done                                                         |
| 1    | Failed                                                       |
| 2    | The command line was wrong                                   |
| 3    | Stopped at a question nobody answered; nothing was published |
| 4    | Saved as a job waiting for input                             |
| 5    | Finished, but at least one tracker did not upload            |
