# Changelog

## [Unreleased]

### Fixed

- LST torrents now use the tracker-required `LST.GG` source flag instead of `LST`.
- JSON tracker API uploads now explicitly request `application/json`, preventing validation failures from being returned as HTML redirects that obscure the API error.
- Updated HUNO uploads for its new auto-mode API: descriptions and MediaInfo are uploaded as `.txt` files, season packs omit the episode field, and the registered torrent is resolved from HUNO's nested response before download. HUNO title overrides are no longer offered because auto mode generates the name from the torrent filename, MediaInfo and TMDB rather than accepting one; its Stream Optimized toggle is also removed because HUNO now detects that value from the audio format.
- LST's staff freeleech option now accepts and uploads the API's required 0–100 percentage instead of sending a boolean as 0 or 1. Existing enabled settings migrate to 100% automatically.

### Removed

- NFO template validation, this is up to the users to ensure they have a proper template per tracker

## [1.1.6] - 2026-08-13

### Changed

- Improved plugin collection for frozen builds (i.e. exe)
- Strip local state from local builds (not a issue with CI builder)

## [1.1.5] - 2026-08-13

### Added

- `{streaming_service}` token and a Service combo on the rename pages, for the streaming-service abbreviation (`NF`, `AMZN`, etc.) that Aither and LST require on web releases.
- `only_if`, `unless` and `default` token filters, documented under Token Replacer -> Flat Strings.

### Changed

- Per-tracker title overrides are no longer locked. Aither, LST, ReelFliX, HUNO, DarkPeers, ShareIsland, UploadCX and OnlyEncodes previously showed a read-only enforced title; every tracker's title is now the user's to edit, since what a tracker's site actually requires is still applied automatically at upload regardless. Existing profiles have the previously-locked value refreshed to the corrected packaged default on first load.
- PassThePopcorn no longer offers a title-override row -- its upload has no release-name field for one to fill.
- Aither, LST, ReelFliX and BeyondHD's packaged titles now match each tracker's published naming rules (correct component order for a remux/full disc vs. an encode/web release, REPACK/HYBRID, HDR omitted for SDR, BeyondHD's `-NOGROUP` for an untagged release). BeyondHD ships a packaged title for the first time.

### Fixed

- Some minor bugs (UI only) for users edit from overview
- Tracker titles could silently drop REPACK, REMUX and HYBRID.
- A remux's video codec could render as an encode's (`x264`/`x265` instead of `AVC`/`HEVC`).
- `{source}` rendered `WEBDL` instead of `WEB-DL`.
- The same token used twice with different filters in one template collapsed to a single value instead of resolving independently.

## [1.1.4] - 2026-08-11

### Changed

- Series title overrides are now editable for trackers that don't actually enforce a series title format (TorrentLeech, HUNO, ReelFliX, DarkPeers, ShareIsland, UploadCX, OnlyEncodes). These were greyed out on the Series Config screen while nothing was being enforced behind the lock. Aither and LST stay locked, since they do enforce one. Titles are unchanged unless you choose to set an override.
- TorrentLeech's title override is no longer locked on either screen. TorrentLeech dictates no title format -- the space-separated naming it wants is applied automatically to every upload -- so the override is yours to use like any other tracker's. Existing configs have the old setting cleared on first load.
- Token filters now apply to user tokens and to values overridden on the rename page, which previously ignored them -- `{usr_something|upper}` starts being honoured. An optional `:opt=` string is a literal and is no longer altered by the token's filters, so `{:opt=ep :episode_number|upper}` renders `ep 2` rather than `EP 2`.
- Updated dependencies:
  - platformdirs

### Fixed

- Fixed Aither and LST single-episode titles rendering as `S01E2` instead of `S01E02`. An optional prefix such as the `E` in `{:opt=E:episode_number|zfill(2)}` was attached before the token's own filters ran, so `zfill(2)` saw a value that was already two characters and padded nothing. Season packs and multi-episode files were unaffected.
- Fixed audio channel layouts such as `5.1` and `7.1.4` being mangled in tracker titles.
- Fixed HUNO titles ending in a stray `- )` when a release has no group tag.
- Fixed SeedPool uploads being named in prose rather than after the release. SeedPool wants the dot-separated release name (`Show.S01E02.1080p.WEB-DL.H.264-GRP`), but it was sharing the spaced formatting the other UNIT3D trackers use.
- Fixed TorrentLeech titles still mangling those layouts (`TrueHD Atmos 7.1` became `TrueHD Atmos 7 1`). Its packaged title rule replaced every period with a space before the layout-aware formatting could run.
- Fixed edited UNIT3D titles bypassing automatic title formatting.
- Fixed generated `.torrent` and `.nfo` files losing the end of the release name for season packs and any release opened as a folder. A folder named `Show.S01.1080p.BluRay.x264-Group` produced `Show.S01.1080p.BluRay.torrent`, dropping the codec and release group.
- Fixed the same truncation affecting trackers that read the release name off the input path, which could give a pack the wrong type, source or codec, and could shorten a duplicate-check search.

## [1.1.3] - 2026-08-10

### Changed

- Piece size is now chosen by one fixed curve based on release size alone, rather than by whichever tracker happened to be hashed first. One hash is shared by every tracker in a run, but mkbrr prescribes a different exact piece size per tracker, so the torrent was previously shaped by one tracker's rules and handed to all the others. The curve tops out at 16 MiB, which is at or below every supported tracker's limit, so it is valid for any combination of trackers -- including a prepared job resumed with trackers it was not built for. Two consequences:
  - Piece sizes change for some releases. Trackers that permit larger pieces than 16 MiB (TorrentLeech among them) now get more, smaller pieces on very large releases, and a correspondingly larger `.torrent` file. This is legal everywhere and is the safer direction to err.
  - The torf fallback now produces a torrent identical to mkbrr's. Both are given the same explicit piece size, so an mkbrr failure no longer silently changes the shape of the torrent.
- The per-tracker **Max Piece Size** setting is retired, since the curve is now the sole source. It is removed from new configs and dropped from existing ones the next time settings are saved; no action is needed.

### Fixed

- Torrents no longer inherit another tracker's identity. A run hashes the media once and clones that torrent for every other tracker, but the file it cloned from was the _first tracker's own torrent_ -- and for a UNIT3D tracker, uploading replaces that file in place with the copy the tracker's server hands back, before the next tracker is cloned. Every later tracker therefore cloned from a torrent a tracker's server had already edited. On a real LST, ReelFliX, TorrentLeech job this produced a ReelFliX torrent whose `created by` read `Edited by LST.GG. Edited by ReelFliX`, and a TorrentLeech torrent reading `Edited by LST.GG` with no edit of its own -- TorrentLeech is not UNIT3D, so it never redownloads and the wrong value reached its users. The run now hashes into a neutral base torrent that carries no announce, source or comment, is never uploaded, and lives outside every tracker's folder. Every tracker, the first included, gets a stamped clone of it, so no tracker's artifact is ever another tracker's clone source.
- A saved job no longer carries a stamped torrent forward. Jobs stored whichever tracker folder sorted first, so a resumed job could seed an entire run from one tracker's server-rewritten torrent. Jobs now store the neutral base, and a base saved by an earlier release is stripped of its announce, source, comment and `created by` when it loads, rather than being used as-is or thrown away.
- A tracker whose configured announce URL is not a URL now fails with a message naming the tracker and the setting. Previously the run stopped on a raw validation error that identified neither, and quoted the offending value back in full -- unreadable when what had been saved into the field was something like an NFO template.

### Removed

- MoreThanTV support is removed. The tracker no longer appears in the tracker list, the settings pages, the duplicate checker or the upload flow, and its uploader, search client and title formatting are gone from the codebase. No config migration is needed: an existing profile keeps its `[tracker.more_than_tv]` section as an inert block that the app never reads or rewrites, and a stale `MoreThanTV` entry in the tracker order or the last-used image hosts is ignored on load. Delete the section by hand if you would rather not leave its saved credentials on disk.

## [1.1.2] - 2026-08-10

### Changed

- Aither, LST and ReelFliX now send the title with its punctuation intact. Their enforced formats opened with `{title_clean}`, which runs the global title-clean rules, and the packaged rules replace every non-alphanumeric character with a space, so `Alice & Bob: A Tale - Part One` reached those trackers as `Alice and Bob A Tale Part One`. The enforced formats now use `{title_exact}` and `{episode_title_exact}`, with colon handling set to Keep. Three consequences:
  - Titles change on these three trackers for every user, not only those who had set an override. Colons, hyphens, apostrophes and ampersands now appear where they previously became spaces.
  - Titles are no longer folded to ASCII, so accented and non-Latin characters reach these trackers as the metadata source spells them. Characters that are illegal in a filename are no longer stripped either, since a tracker title is not a path.
  - Episode titles keep their punctuation apart from a colon, which `{episode_title_exact}` still replaces with a space.
- Renaming is unaffected. Filenames and season-pack folder names still use `{title_clean}`, so they keep the stripped, dotted form.

## [1.1.1] - 2026-08-10

### Changed

- LST and ReelFliX now use the same enforced release title format as Aither. ReelFliX previously had no enforced format; LST's was incorrect, using `{edition}` where it should use `{cut}` and a flat audio token with no Atmos handling. Four consequences for existing users:
  - ReelFliX movie titles change for every user, not only those who had set an override. ReelFliX had no enforced format before, so its titles came from the user's global movie template; an enforced token now governs instead.
  - LST movie titles change. `{cut}` is a subset of `{edition}`, so marketing editions (Remastered, Criterion, Special, Collectors, Deluxe, Limited, Ultimate, Uncensored) no longer appear in the title, and neither does any other edition text NfoForge can't classify as a Cut, including a manual edition override that matches no known cut. The audio token also changes, from `{audio_codec} {audio_channel_s}` to `{audio_codec_no_atmos} {audio_channel_s} {atmos}`, which reorders Atmos releases: `TrueHD Atmos 7.1` becomes `TrueHD 7.1 Atmos`.
  - Series titles change on Aither and LST. Both trackers enforced a movie title but not a series one, so series uploads used the global series template. They now use the tracker's enforced series format.
  - ReelFliX's saved title override was being used and no longer is. LST's was already ignored before this change, since LST already dictated its own title format, and is now hidden from the settings page as well. Both stay in the config file rather than being deleted.
- Jobs saved before this release upload the titles stored with them. Saved jobs are snapshots by design; re-run from the wizard to pick up the new format.

### Fixed

- Trackers that hand out no announce URL are now fully supported. A growing number of UNIT3D trackers (LST among them) issue none, stamping their own into the torrent they return on upload. Two things got in the way:
  - Torrent creation with mkbrr refused outright, reporting `mkbrr failed: Cannot create a torrent without a tracker announce URL (falling back to torf)`. The upload still worked via the fallback, but the red error was alarming and the fast hasher was skipped. mkbrr's `--tracker` is optional, so the flag is now simply omitted.
  - When a torrent was cloned for a second tracker, a blank announce URL left the base torrent's announce in place, so the tracker received a torrent pointing at whichever tracker was hashed first. The announce is now cleared instead.
- Season packs were rejected by every UNIT3D tracker (Aither, LST, HUNO, DarkPeers, ShareIsland, UploadCX, OnlyEncodes, Blutopia, Seedpool, UTP, Yu-Scene, FearNoPeer) with an error about a missing episode number. UNIT3D requires `episode_number` on every TV upload and expresses a pack as episode `0`; NfoForge was omitting the field entirely for packs.
- Absolute-numbered anime could upload mis-categorized as a special. When a release had no episode mapping to fall back on, filenames like `Anime.Title.-.087.1080p...` were read as season 0 (the leading zero of `087`), which UNIT3D files under "Special 87". Season 0 is now only accepted when the filename actually names a specials season, so a genuine `S00E03` release is unaffected.
- A release whose season or episode number could not be determined — absolute-numbered anime, or a date-based episode like `The.Daily.Show.2024.01.15...` with no episode data to map against — reached the uploader with the fields silently dropped, and the tracker rejected it. The Series Match page now refuses to advance and names the missing value, with a backend guard covering the paths that skip that page.
- When only some of the season/episode data was mapped, the filename-parsing fallback appended its own guesses on top of the mapped values, which could widen a pack's season range beyond what the user chose.
- The series settings page let users edit and save title overrides for trackers that dictate their own title format, including ones that ship no packaged series format at all. Those values were never used. The page now locks every such tracker: Aither and LST show their enforced series format read-only, matching the movies page; the rest show a locked, empty field, since they enforce no series format and the global series format applies instead.

## [1.1.0] - 2026-08-09

### Added

- Support for trackers:
  - HDB
  - Blutopia
  - SeedPool
  - UTP
  - Yu-Scene
  - FearNoPeer
- image hosts:
  - OnlyImage
  - Pixhost
  - Lensdump
- Added tracker format policy for titles:
  - MTV, TL, Aither, Huno, LST, DarkPeers, ShareIsland, UploadCX, and OnlyEncodes
- New **file token**s:
  - `{cut}`: subset of `{edition}` providing only **cut** editions
- Saveable jobs. The process page now offers **Save Job** alongside Process, storing a fully configured upload (media, metadata, screenshots, trackers and their image-host choices) as JSON under `<working directory>/jobs`. **Jobs** on the start page opens the saved-job window; picking one restores it and jumps straight to the process page, ready to upload. The saved-job window filters, sorts, shows what a job contains, and builds the queue as an explicit ordered list. Saved jobs keep their own MediaInfo so restoring never re-reads the source file, and duplicate checks still run at process time rather than at save time, so results are never stale.
  - When a run ends with trackers that were never uploaded -- a tracker that was down and got skipped, or trackers left unprocessed after cancelling -- NfoForge offers to save just those as a new job. Only trackers whose upload provably did not reach the tracker are included, so a deferred job can never re-upload something that already went out. The titles and NFOs from the run are saved with the deferred job, including overview edits, so it uploads exactly what was prepared.
  - Jobs record the config profile they were built under. Jobs belonging to other configs are still listed, but greyed out and only openable via **Switch profile and load**, since resuming under a different config would silently use its credentials, templates and per-tracker settings. Loading also warns when the active config has a job's tracker disabled or is missing an NFO template it needs.
  - Each job is a self-contained folder holding its own screenshots, MediaInfo, NFOs, and a copy of the generated torrent, so a saved job keeps working after the working directory is cleaned up and deleting a job reclaims exactly what it was using. Resuming reuses all of it: screenshots already uploaded are not sent to the image host a second time (while the tracker's image host is unchanged), MediaInfo is served from the stored OLDXML and text dumps rather than re-reading the media, and the torrent is cloned instead of being re-hashed. A saved torrent is only reused when every file it covers is unchanged, so editing one episode of a pack sends the run back to hashing.
  - **Prepare && Save Job** on the process page runs everything except the upload itself -- image uploads, torrent, titles and NFOs -- and saves a job that only needs uploading. Running a prepared job asks nothing: prompt-token answers and any edits made in the overview dialog are saved with it, and its NFOs are uploaded exactly as prepared rather than regenerated. If an NFO template is edited afterwards, loading the job says which one changed, since the saved NFO is what will actually be sent.
  - A **job queue**: select several prepared jobs on the current config and upload them one after another. Only prepared jobs qualify, since anything else would stop at a prompt there is nobody to answer. A job is skipped and left saved for review when its duplicate check finds something _or_ when that check could not complete -- unverified is treated the same as found, since the queue has nobody to ask what the interactive flow asks. Once a job has uploaded, the trackers that went out are removed from it, and a job with nothing left is deleted, so re-running a queue does not re-upload what already landed -- short of that bookkeeping update itself failing, which is logged and leaves the job to try again next run. A tracker that fails is retried automatically and then passed by without blocking, and no single job failing stops the ones behind it.
- Plugins:
  - Added optional post-upload plugins. Processors run once per tracker after that tracker's upload and torrent-client injection finish (or fail), reporting one of four outcomes (success, upload failed, injection failed, skipped) with a scrubbed error message when applicable.
  - Added optional image host uploader plugins. A plugin can contribute a custom screenshot upload destination, selectable per tracker as **Plugin** alongside the built-in hosts, without needing its own entry in Settings -> Image Hosts.
  - Added optional duplicate-checker plugins. A plugin can supplement the built-in per-tracker dupe search with results from an additional source (e.g. a private cross-tracker database); results are merged into the existing dupe-check log and never block or auto-skip an upload.
  - Added optional custom edition/cut contribution plugins. A plugin can extend the closed `{edition}`/`{cut}` detection table with its own recognized phrases, each flagged as Cut or Edition-only the same way the built-in entries are.

### Changed

- Aither title format now uses `{cut}` instead of `{edition}`
- The working directory is now organized into subfolders: generated artifacts (screenshots, torrents, NFOs) go under `processing/` and saved jobs under `jobs/`. Settings -> General **Clean Up** empties everything except `jobs/`, so housekeeping can no longer delete saved work, and its size readout now reports only what it can actually reclaim. Run folders left at the root by earlier versions are still cleaned up, so no manual migration is needed.
- Update dependencies:
  - Platformdirs

### Fixed

- Disc detection bug in all UNIT3D trackers, PTP, and BHD

## [1.0.0] - 2026-08-04

### Added

- Real-time token example updates in Movie Management settings when Global Management settings change (title clean rules and video dynamic range).
- Added new settings tab **Global Management**. This tab will hold global rename settings for both Series/Movies.
- Tokens:
  - **FileTokens**:
    - `{original_title}` - Original title from the transformed metadata payload or TMDB.
    - `{original_title_fallback_title}` - Original title with a fallback to {title}.
    - `{original_title_fallback_title_clean}` - Original title with a fallback to {title_clean}.
    - `{original_language}` - Original language (English).
    - `{original_language_iso_639_1}` - Original language (EN).
    - `{original_language_iso_639_2}`- Original language (ENG).
    - `{release_date}`- Release date (movies - UTC).
    - `{air_date}`- Air date (series - UTC).
    - `{season_number}`- Season number (1, 2, 3, etc.).
    - `{episode_air_date}`- Episode air date (UTC).
    - `{episode_number}`- Episode number (1, 2, 3, etc.).
    - `{episode_number_absolute}`- Episode number (1, 2, 3, etc.).
    - `{episode_title}`- Title parsed from media databases with minimal formatting.
    - `{episode_title_clean}`- Clean title parsed from media databases.
    - `{episode_title_exact}`- Title parsed from media databases with no modifications.
    - `{audio_codec_no_atmos}`- Audio codec with Atmos removed (TrueHD).
    - `{atmos}`- Returns 'Atmos' if Atmos was detected.
  - **NfoTokens**:
    - `{total_seasons}`- Total seasons in series.
    - `{total_episodes}`- Total episodes in season/series.
    - `{episode_mediainfo}` - Synopsis of all episodes mediainfo.
    - `{episode_metadata}` - Synopsis of all episodes metadata.
    - `{episode_metadata_mediainfo}` - Synopsis of all episodes metadata + mediainfo.
    - `{media_type}`- Media type (Movie/Series).
    - `{is_anime}`- Returns 'Anime' if the release is anime.
- Built **Series Mapper** _(for series)_:
  - New widget that will allow the user to match their episode(s) with aired, dvd, or absolute data parsed from **TVDB**. This data will allow NfoForge to accurately rename/manage files throughout the rest of the work flow.
  - New wizard page for the user to access this during the workflow.
- Support for plugin **filters** and **functions** for flat strings _(no documentation yet on this https://github.com/jesterr0/NfoForge/issues/97)_.
- Built a dialog crop widget that wraps the existing crop widget.
- Rename Preview dialogue:
  - Pops up to preview the renamed folder(s) and file(s) showing a **diff** in red/green colors.
  - Gives the user a chance to confirm the rename or go back and make changes.
- ImageViewer widget now has a draggable splitter, this way the user can resize/collapse the log/image portion of the widget.
- Series support during flow to handle mapping/renaming
- Now checks tracker health before attempting to upload
- Template editor now highlights tokens that will not resolve when the template renders. The highlight color is configurable in Settings > Templates, and the save status tip reports how many were found.
- Implemented torrent upload retries with user control.
- Add ability to set file save location when adding a torrent to qBittorrent.
- Added a pre-upload wizard page that combines smaller wizard pages into one.
- Added a versioned, typed plugin API with stable plugin IDs, local `nfoforge-plugin.toml` manifests, and installed-package entry-point support.
- Added optional metadata-transformer plugins. Transformers receive an isolated copy of the completed media-search payload; valid results are applied atomically and failures fall back to the canonical TMDB metadata.
- TMDB metadata search now uses the bundled API v3 key and no longer requires users to configure or store a TMDB credential.
- Added a dedicated **Plugins** settings tab for enabling plugin execution, selecting each single-provider capability, and inspecting loaded, failed, or configured-but-unavailable plugins.

### Changed

- Re worked input pages completely
- Template management widget delete button now requires a confirmation before deleting a template.
- Sandbox changes:
  - Rebuilt the input for sandbox, it is now a _mini wizard_ that works very similarly to the normal work flow. For series we needed more widgets to gather input from the user, so this allows a nice easy to use flow for the user.
  - When the user is opening a series, the user will now see **Series Episode Matcher** page, to allow them to confirm/match their episodes with TVDB data.
- Token changes:
  - `{movie_title}` has been replaced with `{title}`.
  - `{movie_clean_title}` has been replaced with `{title_clean}`.
  - `{movie_exact_title}` has been replaced with `{title_exact}`.
  - All MediaInfo tokens have had the `mi_` prefix removed (e.g., `{mi_audio_codec}` is now `{audio_codec}`, `{mi_video_width}` is now `{video_width}`).
- FileTree widget changes:
  - Now display system icons before using any custom defined icons.
  - Massively optimized filetype detection.
  - Now properly clears item cache on reset (this wouldn't have caused any major issues).
- MediaInput wizard page has been been modified:
  - No longer considered **Basic** input, this wizard page will handle all inputs _(besides plugin wizard pages)_.
  - Can accept any input, single, comparison etc.
  - Added a new button to enable comparison mode:
    - This allows the user to open a **source** and click the matching file from the input file-tree below.
    - Allows **script** files _(.vpy, .avs, or .txt)_ files to be opened to read the crop for comparison image workflows.
  - Now tells how many files are being parsed when the user is clicking next in the status bar.
  - File tree now shows up regardless if it's a single file or directory input.
    - When opening comparison source file and the file tree only has **one** file in the tree, that file will be automatically selected.
- MediaInput backend has been reworked:
  - Now supports series.
  - Now utilizes async to parse MediaInfo of multiple files concurrently, this greatly speeds up read speeds for anything over a single file.
- Error dialog can now be maximized and grows to it's parent geometry on error.
- Movie management settings changes:
  - Example indentation has been adjusted.
  - Example input boxes are now frameless and set to readonly instead of disabled.
  - Modify labels.
  - Move example preview button to top right of controls box (removes multiple buttons that did the same thing for each example section).
  - Example mediainfo/file input info window will now be the exact same size as the parent when opened.
  - Colon replace drop downs now stretch to the width of the parent.
- Media Search changes:
  - For movies TVDB is no longer accessed.
  - Now returns **extended** data from TVDB's API for the series to the media search payload (useful for NfoForge internally/plugins).
  - Small optimization for un-needed calls to the API.
  - Added some logging for TVDB API related errors.
  - Now simply just says **Parsing metadata, please wait...** instead of **Parsing IMDB/TVDb...** since this is now dynamic based on media type.
  - TVDB failures can now be retried or bypassed for manual series mapping.
  - IMDb, TMDB, and TVDB IDs can be entered manually and are validated before lookup.
- Update niquests.
- All calls to mediainfo includes legacy stream data now _(to detect DTS core)_.
- Plugin controls have moved out of **General** and into the dedicated **Plugins** settings tab. Disabling external plugins now preserves saved selections while preventing local plugins and entry points from being imported at startup.
- Main window status label now updates with the current wizard plugin when selected.
- Crop Widget:
  - Improved script detection logic for AviSynth/VapourSynth scripts for manual crops.
  - Re-organized the widget to make things look nicer.
  - Added a description label.
  - Adjusted widget margins.
  - You can now pop out the text editor widget for the text input.
  - Text window is now read only.
- Plugin Changes:
  - Plugin API version 2 replaces the live metadata-transformer processing context with an isolated, typed context snapshot.
  - Plugins now export one `PluginDefinition` and use typed request objects for token replacement, pre-upload processing, and metadata transformation.
  - Plugin discovery and execution are centralized through `PluginManager`. One invalid plugin no longer prevents other plugins or NfoForge from loading.
  - Duplicate plugin IDs and conflicting Jinja/flat-filter contribution names are rejected instead of silently overwriting existing behavior.
  - Local plugin modules are loaded directly from their repository without temporarily modifying Python's global import path.
  - Metadata transformers receive an immutable context snapshot whose media-search reference is the same isolated payload supplied by the request.
  - Plugin selections are stored using stable manifest or entry-point IDs rather than display names. Config schema 4 resets legacy display-name selections so compatible plugins can be selected again explicitly.
  - Run state has moved off of `ConfigManager` and on to the `ProcessingContext` that plugins are passed. `config.shared_data` and `config.media_input_payload` no longer exist - use `context.shared_data`, `context.media_input`, `context.media_search` and `context.jinja_engine` instead.
  - `MediaInputPayload` no longer describes a single encode. `encode_file_mi_obj` has been replaced by `file_list`, `file_list_mediainfo` _(keyed by path)_ and `comparison_pair`, so a plugin can reach every file in a series pack rather than only one.
    - Input paths are **not** stable for the length of a run. The rename page renames the media and re-points `file_list`, `file_list_mediainfo`, `series_episode_map` and `comparison_pair` at the new paths. A plugin holding its own data keyed by an input path has to re-key it when that happens, or keep what it needs directly rather than looking it up again later.
  - `token_replacer` plugins are now called from the template preview as well as during processing using `TokenReplaceRequest`; its `preview` flag identifies preview rendering where screenshots have not yet been uploaded.
    - The preview only calls the plugin when the selected template belongs to exactly one tracker, which matches how processing calls it. A template shared by several trackers (or assigned to none) has its plugin tokens left as they are.
    - A plugin error during preview is now reported instead of discarded. **This affects existing plugins**: one that has always failed in the preview will begin surfacing that failure, where before it failed silently.
- Improved the visuals of tracker format override widget.
- File rename no longer happens during processing stage.
- Updated dependencies:
  - tomlkit
  - pillow
  - platformdirs
  - pyside6
  - psutil
  - aiohttp
  - qbittorrent-api
  - niquests **with speedups enabled**
  - regex
  - rapidfuzz
  - lxml
  - certifi
  - setuptools
  - urllib3
  - guessit
- Plugin load failures are collected into one startup warning and retained for inspection in Settings without disabling successfully loaded plugins.
- Checks for incompatible schema of configs on selection and allows the user to generate a new config if one is detected backing up the old
- New template button is now a drop down menu that allows the user to select a series vs. movies template for a basic default template designed for that media type
- Added early tracker UX guard
  - Series workflows disable known unsupported trackers: PTP and ReelFliX.
- Added BasedPyright static type checking for the application and tracked plugin examples
- Now supports latest deluge-web-client (=>2.x.x)
- Remove support for PTPIMG
- Optimized UNIT3D torrent re-download with regression testing
- Properly detect and pass anime to TorrentLeech
- Block/stop processing when media search is unavailable due to network issues/no internet
- Handle where guessit can return two titles causing a runtime error with specific filenames
- Added typed configurations for qBittorrent, Deluge, rTorrent, and Transmission
- Improved the splash screen
  - Startup time is a tad quicker
  - The **Continue** button has been changed to a check icon
  - Added a **Cancel** button that is an icon of X (to close the application instead of choosing a config if desired)
  - Now opens up on your active monitor and falls back to the primary monitor
  - Attempts to raise above all other windows on launch
  - All buttons now use pointed hand cursor
  - Config selection/button control has been moved to the bottom above the status bar
  - Can now use arrow keys/enter key to accept current config
  - Will now remember last used config (best effort only, on failures it just defaults to the first config)
- Now logs all other QT messages to debug logging
  - Program will look for a .env file beside executable/start_ui.py that accepts **LOG_LEVEL** \*(mainly used for debugging QT errors in dev)\_
- All console logs (when program is ran in **debug**) will be output to stdout
- Defensively handles log files clean up and is best effort (will log if any issues arise when attempting to clean up old runs)
- Cached some lookups that are repeated during file processing that could spam logs with Resolution information when debugging is enabled.
  - This should speed up the TokenReplacer ~30% when doing multiple files at a time.
- Now caches the last ten encode indexes when using comparison image generation via FrameForge in the users temp directory (default in appdata if not defined)
  - No longer generates indexes beside encode file with using FrameForge
- Re-designed UI for tracker settings
  - Much cleaner split panel view
  - You can still set the priority of the tracker upload order by dragging them (priority is greatest from top to bottom)
  - Wizard flow will also use this as well
- Re-designed UI for client settings, works the same as the new tracker settings UI (minus the re-order)
- Media search now uses guessit only instead of older deprecated search code
  - Cleanly detect the title from series based off of the input with weights vs just a generic folder or top level file read

### Fixed

- TokenTable widget labels had the wrong weight of bold.
- UploadCX payload was assigned to the wrong payload _(wouldn't have actually bothered the end result)_.
- Potential error reading audio track layouts with a core.
- Properly catch/handle errors when loading the program when a plugin wizard page threw an error.
- Fixed config round-trip bug for qBittorrent super_seeding
- Properly check for hostname before initialization for Transmission
- Check instance of object before stripping it for save directory/label in Transmission
- Properly check for hostname before initialization for Deluge
- Check instance of object before stripping it for save directory/label in Deluge
- Image subtitle size above 2160p would result in no image subtitle size
- Issue with FFMPEG drawtext filter on basic comparison images.
- Incorrectly showing image generation complete on failed image generation
- Could incorrectly parse IMAX from titles such as 'climax'
- Prevent tracker credentials from reaching logs, retry dialogs, and process error output.
- Series episode renames now render filename and MediaInfo tokens from each episode instead of reusing the first file in the pack.
- Plugin flat filters now apply consistently to runtime filenames, series folder names, tracker titles, and qBittorrent save-path templates as well as Settings previews.
- Empty or failed generated rename names are rejected before a rename plan is created.
- Rendered filenames are sanitized for Windows path rules, and cross-folder rename previews now show their full paths.
- Metadata transformer payloads are fully validated and copied before commit, preventing invalid or uncopyable results from partially replacing canonical TMDB metadata.

### Removed

- `{movie_full_title}` has been removed (`{title_exact}` token replaces it).
- Movie settings page no longer has controls for clean title token and dynamic range control (this is now handled in Global Management).
- Advanced Input page _(existing functionality will still exist in the **Input** page)_.
- General settings source/encode extension filter control has been removed.
- Unused fonts that was included in the bundled runtime
- Removed direct IMDb scraping and the **cinemagoer/imdbinfo** dependencies. TMDB now supplies fallback metadata when no external transformer is configured.
- Removed the legacy `PluginPayload`, plugin registry, and metadata-provider contracts. Local plugins now require a manifest and the typed `PluginDefinition` API.

## [0.8.14] - 2026-2-21

### Added

- Add super seeding mode option for qBittorrent client (@yammes08).

### Fixed

- MoreThanTV release group parser for tags could sometimes include extra information.
- Prevent mi_video_dynamic_range token from appending PQ to HDR formats (@yammes08).

## [0.8.13] - 2025-10-26

### Changed

- ReelFliX domain change.

## [0.8.12] - 2025-10-16

### Added

- Massively improve resolution detection (@yammes08).

### Fixed

- Fixed DDP naming (@yammes08).

## [0.8.11] - 2025-10-11

### Added

- Localization override for rename/encode wizard (yammes).
- BHD edition support (yammes).
- Streaming optimized toggle for BHD uploads (yammes).

### Fixed

- Audio channel spacing/characters for BHD (yammes).

## [0.8.10] - 2025-09-01

### Changed

- Now downloads the torrent after upload for **UNIT3D** trackers. This is now [required on v9.1.6](https://github.com/HDInnovations/UNIT3D/pull/4910).

## [0.8.9] - 2025-08-19

### Added

- **FFPROBE** detection. While NFoForge doesn't really _need_ this to function, this will be nice for users to utilize in a plugin and detection can be handled by NfoForge.
- Added informational hover labels to each dependency.
- Now supports conditional prompt tokens.
- In template sandbox mode a new button menu has been added and will be visible when a source is loaded. This allows the user to clear the input or clear the input and tokens without leaving this screen. This way they can test multiple inputs/configurations more easily.
- Rename window auto detects remux now.
- TokenReplacer detects rather or the token **{mi_video_codec}** should be H.264, x264, or AVC (and HEVC equivalents now) intelligently.
- Added some more plugin functionality _(documentation for plugins doesn't exist right now, this will come in the future)_.
  - Added `ask_thread_safe_prompt`, `ask_thread_safe_multi_prompt` and `ask_thread_safe_custom_prompt`.
    - These are helper functions that can be called from any where in the program, other threads, or multi processes and safely talk to the GUI (ideal for plugins).
  - Built new plugin base `PluginPromptDialog` for `ask_thread_safe_custom_prompt`.

### Changed

- ImageViewer check button background now changes to green when required selected images are met.
- ImageViewer buttons cursor are now pointing hand cursor for the mouse.

### Fixed

- ImageViewer error when moving images starting at index 0.
- An issue bug for flat strings when using **opt**, this would have gave duplicate optional values.
- An issue in rename window for jinja added globals.
- Rename window remux checkbox was disabled on UHD BluRay quality selection.
- BeyondHD dupe checks for directories has been fixed.

### Removed

- Jinja changes.
  - Block, variable, and comment control.
  - Line statement prefix and line comment prefix.
  - All of the above added un-needed complexity that > 99% of users would never customize and this allows me to use add custom logic/tokens/unit tests easier.

## [0.8.8] - 2025-08-15

### Added

- MediaSearch missing inputs that are required now flashes yellow if missing.
- Advanced input wizard page now flashes yellow for missing input(s).
- Parse series from TVDB to get metadata as needed (full series support is not in the program yet).
- Config selector on splash screen if there are 2 or more user configs available for easy selection.
- Added a new checkbox to **Enabled Prompt Tokens on Preview in Sandbox**. This will allow the user to control rather or not they will be prompted while testing their templates by prompt tokens.
- UI scaling.
  - Added UI scaling spinbox in **Settings -> General**.
  - Can now modify scaling on the fly program wide with hotkeys.
    - **CTRL and +** zooms in.
    - **CTRL and -** zooms out.
    - **CTRL and 0** resets zoom to defaults.
    - Config is automatically updated after a couple seconds of using the hot keys.

### Changed

- Template sandbox mode changes.
  - Improved syntax error line detection in templates.
  - Directory button is now visible in the input.

### Fixed

- User could save their previewed template in sandbox mode, overwriting their template. Now automatically unchecks the template on save.
- Break up tooltip that was too long.
- A bug when the user saved any changes in Config that would break **user plugin functions**.
- ShareIsland default torrent source was **wrong**. You should modify this yourself and set the torrent source to **ShareIsland**. _Alternatively, you can reset the entire config if you desire._
- Dupes we're not be accurately detected for numerous trackers since **v0.8.0**.
- Alignment of widgets on sandbox input window.

### Removed

- Un-needed print statement in code base.

## [0.8.7] - 2025-08-14

### Added

- Ability to sync images in **Basic Comparison** screenshot mode.
  - Sync tab to image viewer.
- TMDB language settings.
  - Smart Language Selection: Added comprehensive TMDB language support with 69 languages including regional variants (en-US/en-GB, es-ES/es-MX, zh-CN/zh-TW, etc.).
  - Automatically uses original titles when user's language matches the movie's original language (e.g., Italian users get authentic Italian titles for Italian films).
- New FileToken **{mi_video_format}**, returns the video format e.g. HEVC, AVC, MPEG Video.

### Changed

- Massively improved the auto crop detection logic.
- Image generation for **Basic** and **Basic Comparison** modes have been re-worked.
  - For basic and basic comparison image generation we're looking at about a **80x** speed up for image generation.
  - Brings VC-1 image generation up to speed with other codecs.
- Now automatically de-selects preview on template tab if we're swapping tabs in settings.
- Optimized API calls to TMDB.
- No longer overrides TMDB title with IMDb.
- Improved speed of metadata initial search speed by around 70%.
- IMDb ID isn't parsed until the user selects a title now (massively reduces requests for each title).
- MediaSearchPayload now includes essentially **all** tmdb data from the api for the user to utilize in their templates if needed.

### Fixed

- Edge case where sync images could be out of sync in the ImageViewer Sync tab.
- Auto crop could fail in certain circumstances.
- Bug when working with VC-1 files and generating images due to auto crop and basic comparison mode.
- Media search bug when stripping text is fixed.
- Bug for template validation when it comes to Unit3D trackers.

## [0.8.6] - 2025-08-12

### Added

- Support for new trackers.
  - ShareIsland
  - OnlyEncodes
  - UploadCX
- Opt-in mod queue for ReelFliX and Aither.
- Flat string filters for filenames/titles.
- Added a new FileToken **{mi_audio_language_all_full}**.

### Changed

- MoreThanTV and PassThePopcorn TOTP input changes:
  - Label has been been changed to be more descriptive.
  - Label and input now has a tooltip.
  - If **TOTP Secret** is not provided the user will now be prompt during processing for their timed one time password.
- Process progress bar will now be displayed as busy if progress is at 0 when sent. Once above 0 progress is handled as before.

### Fixed

- Default override title token for LST, darkpeers, and Aither.
- Remove message that would output a repeated string for each tracker in the process log output.
- Only show update message if there was updates by the user during the overview prompt during processing.

## [0.8.4] - 2025-08-09

### Added

- Added support for prompt tokens.
- Docs for prompt tokens.
- Overview Prompt
  - Added checkbox in settings -> general to toggle overview prompt during processing.
  - Now prompts the user with the full generated NFOs and tracker titles so they can view them and make final edits if needed.
  - Added docs for overview prompt.

### Changed

- Media search window in sandbox mode is opened the same size and position as the main parent window.

### Fixed

- Theme swapper now de-registers widgets as they are destroyed automatically.

### Removed

- Overview page has been removed and related docs.

## [0.8.3] - 2025-08-04

### Added

- The start to proper documentation [here](https://jesterr0.github.io/NfoForge/).
- On process page a new button to view current working directory after processing will appear.
- Added min/max required screenshots/sets.
  - Settings window now has two spinbox's to set min/max screenshot requirements.
  - ImageViewer has been upgraded to allow max screens.
- Added attributions for TMDB and TVDB in the docs/about page.
- Added clickable links to Documentation (online and offline).
- Process process dupe changes:
  - Now logs duplicate check errors.
  - If dupe check worker completely fails, a prompt comes up asking the user if they'd like to continue with uploading. If the user selects yes, NfoForge will continue to upload on next wizard click, if the user selects no they can attempt to check for dupes again.
  - If dupe check fails for a specific tracker (or multiple), each are now displayed and logged to console. NfoForge allows the user to continue uploading at this point, displaying the error on the output window.

### Changed

- Added qtawesome to Thanks and Credits in about page.
- H-lines are a bit wider in about page.
- Movie Rename page release group entry is now part of the override tokens.
  - You can now modify this in both the token override section of the window as well as the release group entry _(these fields will stay in sync when edited)_.
  - For auto detection of input release group you should keep the release group entry blank.
  - You need to use the token **{release_group}** for this functionality to work _({:opt=-:release_group})_.
  - Updated tooltips for release group widgets.

### Fixed

- System bell ringing when using sandbox mode.
- UI bug where the process page progress bar could still exist when clicking start over after processing jobs.
- Creating a new template during during the flow of the wizard the process page would not load the new templates without restarting the program _(This did not affect uploading, just writing the generated NFO to disk)_.
- Overview page now shows all generated NFOs (regression in v0.8.0).
- Override panel isn't reset in rename window properly.
- **movie_clean_title** defaults have changed, preventing output from `St. Elmo's` from becoming `St. Elmo s`.
- Movie Rename page having an error on reset in certain circumstances due to signals still being fired off.
- There was no way to modify release group on filename.
- Override tokens in the Movie Rename page now respects **:opt=x:** properly.
- A bug when selecting your torrent client that would pop up (and still work).
- A bug on linux causing issue with starting the application.

### Removed

- Required selected screenshots (replaced see Added).
- Requirement for TVDB Api Key (still gets metadata from TVDB).

## [0.8.2] - 2025-07-28

### Changed

- Process window is now supports 2 decimal precision.
- TorrentLeech title naming scheme is now enforced, added defaults to the override.

### Fixed

- Media search window was not showing in the last release (not getting IMDb/TMDB metadata).
- **movie_clean_title** wasn't working properly to remove all tokens. If you have made modifications to his, you should reset it to the new defaults and re-add your modifications.

## [0.8.1] - 2025-07-27

### Added

- Added Working Directory input (general settings).
- Added button to open current working directory in file explorer across Win, Linux, and Mac.
- Added option to prevent parsing of input file attributes (REMUX, HYBRID, PROPER, and REPACK) in the movie settings tab.
- Added example file input and mediainfo window in the movie settings tab to show the raw data of how the examples are being generated.
- New tokens (**hybrid**, **localization**, and **remux**).
- Rename window has been completely reworked.
  - Now uses tokens instead of hierarchy, this is superior to the older method and allows greater user customization where they want this input.
  - Added some new default **Repack Reasons** in the drop down menu.
  - Updated default **Repack/Proper** reason placeholder.
  - Added a new section to over ride the token string, toggled via a checkbox.
  - Added a new button that opens a pop up window to show the user all the potential **FileTokens** they can use in their override string, where they can click to copy/search.
  - Added a **REMUX** checkbox (if the token exists in the string it'll fill the remux token).
  - Added a **HYBRID** checkbox (if the token exists in the string it'll fill the hybrid token).
  - Options portion has been put in a scroll area to allow more widgets.
  - All combo boxes (drop down menus) mouse wheel has been disabled as to not accidentally change while scrolling the new scroll window.
  - **Output can no longer be edited directly, you must use the override token area above and edit each value as needed**.
  - When the **Value** is edited in the **override** section, if the **same** token in a corresponding **title token** exists it will also be updated.
  - Added a new **quality** selection box, this box will **override** the **source** token if utilized. It's automatically detected and set on initialization of the rename page.
  - New validation to ensure the user isn't blatantly using an invalid quality to resolution.
- Added support for **user tokens**.
- Added new **Settings** tab **User Tokens**.
  - Can now add **custom** user tokens for both **FileTokens** and **NfoTokens**.
  - Tokens must be **prefixed** with **usr\_**, all **lowercase**, and **underscores**.
  - **Duplicate** tokens are ignored, only the **last duplicate** token will be accepted.
  - Includes a button to to expand the editor for longer/multi-line tokens.
- **TokenReplacer** engine has been improved.
- Added a new special NfoToken **release_notes**.
  - This token works similar to the other NfoTokens.
  - Added a new wizard page called **Release Notes**, this page allows you to add, delete, edit, manage as many **notes** as you want and label them what ever.
  - Each time you utilize the work flow, you can set the type of release notes you want sent to fill the token **release_notes**.
  - Updated default template for new nfo templates to include a if block for **release_notes**.
  - Added a new variable to the **SharedData** called **release_notes**, that can be overridden in a plugin.
- **Directory** support has been officially added and tested.
  - You can now open a directory in **Basic** mode, this will be good for structures that have a top level folder and file(s) inside.
  - During **rename** on the **process** page the **top-level folder** that was opened will be renamed at the same time as the file.
  - The largest file with the **supported selected suffix (.mkv/.mp4)** will automatically be detected as your **media file**.
  - You can open a file/directory via drag and drop or by using the dedicated buttons.
  - If the file is a directory you'll see a new **file tree** appear, showing the files that will be utilized.
  - Program now displays current size of working directory on status bar 3.5 seconds after launch.
  - Added a delete button to clean up working directory in the settings tab.
- Added support for torrent generation with **mkbrr**.
  - Added support in the **Dependencies** settings tab modify the path to mkbrr if needed.
  - Torrent generation will now **default** to **mkbrr** if it's available, but will fall back to torf as needed or on failure.
  - As of now **mkbrr** will not be bundled with NfoForge on Windows. However, if desired it'll look for **mkbrr** on the system path or in NfoForge's `runtime/apps/mkbrr/*` if you decide you want to bundle it.
  - Added toggle to prioritize torrent generation with **mkbrr** if exists/enabled.
- Added support for **DarkPeers**.
- Added prompt if user opens URLs or image files to be utilized asking if they are comparison images.
- Added new **screenshot comparison tokens** _(they are available as long as the user used comparison images via generation or input)_.
  - Added new token **screen_shots_comparison**.
    - The user is still responsible for the comparison tags in their templates, this only outputs the raw image URLs in the correct format.
  - Added new token **screen_shots_even_obj**.
    - Returns an iterable of even screenshot objects that have **x.url** and **x.medium_url** _(both are not guaranteed so check them with an if statement)_, the user can display it/iterate it in what ever way they desire via the template engine.
  - Added new token **screen_shots_odd_obj**.
    - Returns an iterable of odd screenshot objects that have **x.url** and **x.medium_url** _(both are not guaranteed so check them with an if statement)_, the user can display it/iterate it in what ever way they desire via the template engine.
  - Added new token **screen_shots_even_str**.
    - Returns an iterable of even strings (source).
  - Added new token **screen_shots_odd_str**.
    - Returns an iterable of odd strings (encode).
- **pre_upload_plugin** now has access to the callable **progress_cb** in the process window. It expects a **float**, if this will allow the user to utilize the progress bar in their program.

### Changed

- Upgraded PySide6 to 6.8.3 (tried to go for latest version but there was some minor graphical issues with images).
- Upgraded from requests to niquests.
- Built in plugin descriptions are more descriptive (thanks yammes).
- Slightly organized general settings tab.
- Basic/Advanced inputs now sets working directory sub folder name based on inputs for rest of programs control flow.
- Basic input now always accepts a folder or a file without needing toggled in settings.
- Improved error handling of token replacer backend.
- **Template Settings** token child window will now automatically be closed when closing settings or navigating to a new settings tab.
- **Major** token **mi_video_dynamic_range** changes (thanks yammes):
  - Built a new widget in the **Movie Settings** tab that allows the user fine grained control over how it works.
  - Set which resolutions this token will be active in (720p, 1080p, 2160p).
  - You can set which HDR types will be returned.
  - You can adjust custom strings that will be used when they are returned for each HDR type.
- TokenTable in edit mode is not organized a bit better with h-lines.
- Massively improved edition detection from filename in rename window.
- **Basic Input** page will now flash yellow to alert the user when the user attempts to press **Next** with invalid/missing inputs.
- **Overview Page** file tree widget now auto expands upload loading files.
- **Process Page** log area has been re-worked with rich text. Utilizing emojis and html/css to make things look a bit nicer overall.
  - Detected **duplicates** now have clickable links right from the **log window**, that will open your default browser to navigate to if desired.
  - Emojis for status column.
  - Better organization/separation for different steps in the window.
- Improved settings tabs layout.
- All image host uploaders now log retries.
- **Overview** page initialization is now handled in a threaded worker, to keep the UI smooth while it's handling longer loading NFOs/plugins.
- Improved icons across the whole program (less dependencies to package in the runtime folder).
- Process window log window is scrollable during processing now.

### Fixed

- Don't send TVDB ID to Unit3d trackers if media type is not series.
- Error when image generation is disabled.
- Built in editions in rename window could be duplicated with specific formatting.
- Wrong svg icon on advanced input for the buttons.
- Fixed about tab copy to clip board buttons not working.
- Token **mi_audio_bitrate** would return no results.
- Rare issue that could happen if the token when was closed after copying data from it.
- Extra white space on some of the settings tab at the bottom of the window.
- TokenReplacer engine not replacing tokens when there was an unknown or invalid token in the user input.
- Depending on the vertical height of the parent window sometimes the **Process Page log** would not scroll all the way down when the progress bar was shown.
- Expired cookies on **TorrentLeech**, **PassThePopCorn**, **MoreThanTv** was not automatically being deleted and recreated as needed. Resulting in failed authentication.
- PassThePopCorn could upload with an invalid image format in some cases.
- Sandbox preview now properly uses dummy screenshots.

### Removed

- Remove Directory Input toggle in general settings.

## [0.7.4] - 2025-05-30

### Fixed

- Bug when parsing movie titles that are an audio codec (Opus 2025).

## [0.7.3] - 2025-05-11

### Added

- **LST** tracker support **thanks LostRager**!

### Changed

- In media search window each icon now will fall back to a text based search if the ID is missing.
- Updated aiohttp to 3.11.18.

### Fixed

- **Aither** uploading not working since adding TVDB support.

## [0.7.2] - 2025-4-07

### Fixed

- Console popping up in Windows during image generation.

## [0.7.1] - 2025-4-03

### Added

- Log final args for advanced image generation in DEBUG mode.
- Added the ability to control the Source subtitles for advanced frame generation.
- Added the ability to select the subtitle outline color for both comparison image generation modes.

### Changed

- Massively improved the automatic crop detection for comparison image modes.
- **Windows** updated included **FrameForge** to **1.4.0**.
- Minimum FrameForge version is now 1.4.0 for advanced image generation.
- MoreThanTv release title rules will now be enforced during upload regardless if the user specifies a different format.

### Fixed

- Issue where in some resolutions/crops NfoForge would fail to determine the correct automatic crop.
- Issue when passing manual crops to Advanced image generation could result in picture being out of frame.
- Issue with Automatic Crop would not work for basic comparison mode.
- Disabled crop would still crop for Comparison Mode.
- Crop correction in comparison mode was not working correctly.
- Potential None type error in MoreThanTv module.

## [0.7.0] - 2025-3-25

### Added

- Built a new widget that can scroll for very long error messages to replace the default unhandled error box.
- Logger will now log output to console if debug executable is executed.

### Changed

- Improve logging in the plugin loader.
- Use new error window widget to display unhandled errors.
- Now uses UV instead of Poetry.
- Logger starts in debug mode and is configured on first message via the users settings.

### Fixed

- Movie clean title table would not properly save/update user settings or defaults after being modified once.
- Subprocess windows executing in a new window on Windows.
- 'None' being added to each unhandled error exception output.
- Major bug when attempting to use **requirements.txt** on a system that didn't have Python installed.

### Removed

- NfoForge **no longer** looks for and installs requirement text files for packages. This is a breaking change but is required to properly ensure this works across multiple configurations.

## [0.6.4] - 2025-3-23

### Added

- Added new token **{mi_audio_channel_s_i}**, this token will provide raw channel output (6).
- Added new token **{mi_audio_sample_rate}**, this token will provide audio track #1's sampling rate (48 kHz).
- Added new token **{mi_audio_bitrate}**, this will provide audio track #1's bitrate (640000).
- Added new token **{mi_audio_bitrate_formatted}**, this will provide audio track #1's bitrate (640 kb/s).
- Added new token **{mi_audio_format_info}**, this will provide audio track #1's format info if available (Enhanced AC-3).
- Added new token **{mi_audio_commercial_name}**, this will provide audio track #1's commercial name if available (Dolby Digital Plus).
- Added new token **{mi_audio_compression}**, this will provide audio track #1's compression mode if available (Lossy).
- Added new token **{mi_audio_channel_s_layout}**, this will provide audio track #1's channel layout if available (L R C LFE Ls Rs Lb Rb).
- Added new token **{mi_video_width}**, this will provide video track #1's width (1940).
- Added new token **{mi_video_height}**, this will provide video track #1's height (1080).
- Added new token **{mi_video_language_full}**, this will provide video track full language if available (English).
- Added support for custom **jinja2 functions** and **filters**. You can take a look at the included example plugin on how to use them.

### Changed

- Modify the description of **{mi_audio_channel_s}**.

### Fixed

- Normalize super script (Title⁹ -> Title 9).
- Catch unexpected errors during template preview and reset the button preview button.

## [0.6.3] - 2025-3-18

### Added

- Support for numerous other **Edition** types.
- Now normalizes all editions to properly formatted edition types (Director's -> Directors Cut).

### Changed

- Renamed **Generate Screenshots** to **Enable Image Handling** in the screenshot settings.
- Now asks the user for manual MAL ID input if unable to detect and defaults to 0.
- Now asks the user for manual TVDB ID input if unable to detect and defaults to 0.
- **Edition** is no longer pulled from the **Source** if using a multi input profile.
- Improved **Edition** detection in the backend.

### Fixed

- Prevent error when unable to detect MAL ID when media type is Animation.
- Prevent error when unable to detect TVDB ID.
- MAL/TVDB links we're broken when clicking their icons.

## [0.6.2] - 2025-03-03

### Added

- Added required title override map (`\s` -> `.`) for **MTV**.

### Changed

- Updated pymediainfo to v7.0.1.
- **Generated** in **Optimize Generated Images** is now bold.
- **Convert downloaded and opened images to optimized PNG format** has been renamed to **Optimize Opened Images** with bold.
- **MoreThanTV** tracker over ride should now be **Enabled** by default (if this doesn't update your current config you should enable this yourself).
- Generated images from now on are automatically compressed.
- Adjusted the position of checkbox Optimize Generated Images` in the UI.

### Fixed

- Issue when optimizing images opened via **local files** or **URLs** _(not generated)_ where multiprocessing would hang during image optimization when the program was bundled into an executable.
- A bug that was always **optimizing** users images even if they had configured the program differently.

## [0.6.1] - 2025-02-21

### Fixed

- Bug that could happen if you created a **new** template for a tracker during the **Wizard** in the **Nfo Templates** page. The backend would fail to detect the **new** template.
- Fixed that was stripping unique ID out of mediainfo cleansed strings.
- An issue where reset button didn't work on tracker override character map.

### Removed

- Un-needed string conversions in unit3d backend.
- Tracker override config options.

## [0.6.0] - 2025-02-19

### Added

- You can organize your image URL formatting in "Tracker" settings PER tracker.
- Image generation Log widget now tells the user what "Mode" they are generating images in.
- Image page now supports opening .jpg/.jpeg.
- Image page can now accept raw urls in any format, html, bbcode, raw urls etc. It'll attempt to parse them and convert them automatically to a format the backend needs for processing.
- Can now download images from existing URLs and re-host as needed to image hosts of the users selection.
- Screenshots subtitle color can now be selected via the color chooser widget to the right of the label.
- Add basic ui validation to avoid saving image host data if there is missing data detected.
- You can now select which image host you'd like to upload to for which tracker on the process page.
- Added a right click context menu to the Tracker/Status tree widget, to set all image hosts at once.
- Added the ability to select dropped URLs for each tracker.
- ImageBox now retries with a delay if there is networking issues.
- Added support to set **{ screen_shots }** columns, column space, and row space PER tracker.
- Can now set desired order you'd like your tracker(s) to process in.
- Can now choose desired image host per tracker on the process page. (Can use right click to set ALL trackers to a specific image host)
- Now uploads to multiple image hosts asynchronous.
- Numerous optimizations and improvements.
- Can now open log file directory or current log file from the general settings page via two new icon buttons.
- Added the ability to set your subtitle color via an interactive subtitle picker.
- Add a Reset icon button to movie_clean_token table widget.
- Now passes a new arg to plugin `token_replacer_plugin` of **formatted_screens**.
- Now passes a new arg to plugin `token_replacer_plugin` of **format_images_to_str**.
- Now passes a new arg to plugin `token_replacer_plugin` of **tracker_images**.
- Added a checkbox in the **Screenshot** settings tab called **Convert download and opened images to optimized PNG format**. This checkbox is on by default, if enabled any provided URLs (going to an image host) or any loaded images will automatically be optimized/converted to PNG.
- **Optimize Images CPU Percent** spinbox, the user can select how many **threads** they'd like to allocate to optimizing images (default is 25%).
- Add support for plugins with the prefix of `plugin-`.
- **PTPIMG** support added.
- Added support to remember last used image host per tracker.
- Added support for tracker **HUNO**.
- Add new tokens `{tvdb_id}` and `{mal_id}`.
- Support to easily control the title token, colon replace, and a string replace (via regex) map system PER tracker.
- Added a new token `{frame_size}` for IMAX/Open Matte.
- Add token `{mi_audio_language_1_full}`.
- Add token `{movie_exact_title}`.

### Changed

- **Breaking config changes**, ensure you check all of your saved settings.
- Tracker settings (and all QTreeWidgets) no longer auto scrolls.
- During image generation the "Log" box now automatically scrolls to newest text.
- Image page has been completely re-worked.
- Tracker settings (and all QTreeWidgets) when expanded now scrolls much faster with the mouse wheel.
- Built a new image host interface to easily configure the settings of each host.
- Increased scrolling speed of the torrent client widget on expanded items.
- Set read only mode on screenshots subtitle color input box.
- Template sandbox mode/preview and Overview wizard page now shows Dummy screenshot data, since this is actually filled in the final process step.
- Removed the ability to highlight items in the tracker list box on the overview page.
- Trackers are now displayed in the order the user sets as the priority in the overview page.
- Can no longer manually type the hex color code for subtitle color, you must use the new subtitle picker now.
- Prevent errors when launching the program with _.TOML from the command line for --config _.TOML.
- **movie_clean_token** has some new default rules to handle comma/dash.
- Aither/reelFliX image width can only go as low as 300.
- **Compress Images** checkbox in **Screenshot settings** has been renamed to **Optimize Generated Images**.
- Images wizard page now displays a descriptive subtitle.
- Now automatically creates linked versions of images even if there is no medium/thumbnail urls.
- Locked columns/column space for PTP, they should stay at 1 since PTP doesn't support anything else.
- Checks PTPIMG is configured when enabling PassThePopcorn tracker, prompts the user to add PTPIMG API key.
- All image hosts now will attempt to retry uploads 3 times per image before failing.
- **Movies** settings tab has been completely reworked.
- **Movies** now supports separate filename and title tokens.
- **Movies** now supports separate colon replacement options for filename and title tokens.
- **Movies** examples are now built from real data (mediainfo, imdb/tmdb/tvdb).
- **TorrentLeech** uploader now supports including a title.
- **{releasers_name}** is now available as a **FileToken** now.
- **{edition}** token no longer includes IMAX and Open Matte (this is handled via the new token **{frame_size}**).
- Rename page now stores `frame_size_override` in the shared dynamic data payload.
- Releasers name if left blank defaults to Anonymous.
- Compiled NfoForge (Windows) FrameForge is now updated to v1.3.5.
- Updated dependencies requests, lxml, torf, psutil, aiohttp, semver, qbittorrent-api, regex, stdlib-list, jinja2, beautifulsoup4, rapidfuzz, ruff, and cython.

### Fixed

- Image page open image button icon was improperly sized.
- Issue where modifying the tracker order on the Process page would throw an error.
- Fixed incorrect frame shape/style on the client widget.
- Prevent error when launching program with `--config *.TOML` (capitalized ext).
- ImageBox returning improperly ordered images.
- ImageBox not returning all images after uploading.
- Capitalization of warning prompt in Template settings.
- **movie_clean_token** rules was not updating for the programs new defaults upon loading.
- **movie_clean_token** UI widget had a bug when selecting/deleting the top most item would result in a prompt to ask the user if they'd like to reset to default over and over again.
- Modifying tracker settings in the Tracker widget page will now update the Tracker widget in the Tracker settings tab.
- Bug when utilizing Plugin mode utilizing the built in Basic profile, could result in incorrect image generation being done.
- Wasn't updating tracker status to complete when we skipped upload but still processed the tracker in the backend.
- **Aither** tracker settings widget was displaying the wrong label for image width.
- Prevent colon replace combo boxes from scrolling with the mouse scroll wheel.
- Fixed a bug when trying to access data from the replace table widget that was empty.
- Tracker settings tab that prevented the widgets from expanding fully.

### Removed

- Image host selection is no longer in the General settings page.
- Image uploading is not done in the Image wizard page anymore.
- **Parse with MediaInfo** in **Movies** settings (this will always be done).

# Info

All notable changes to this project will be documented in this file starting with **0.6.0**.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
