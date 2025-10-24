# Changelog

## [Unreleased] - 2025-m?-d?

### Added

- Real-time token example updates in Movie Management settings when Global Management settings change (title clean rules and video dynamic range).
- Added new settings tab **Global Management**. This tab will hold global rename settings for both Series/Movies.
- New custom widget - ComparisonFileMatcher. This will be used to select a matching **source** file for movies/series. # TODO: remove this if we're not going to use it?
- Tokens:
  - **FileTokens**:
    - `{imdb_aka}` - IMDb AKA filename.
    - `{imdb_aka_fallback_title}` - IMDb AKA filename with a fallback to {title}.
    - `{imdb_aka_fallback_title_clean}` - IMDb AKA filename with a fallback to {title_clean}.
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
    - `{episode_title_exact}`- Title parsed from media databases with no modifications.
  - **NfoTokens**:
    - `{total_seasons}`- Total seasons in series.
    - `{total_episodes}`- Total episodes in season/series.
    - `{episode_mediainfo}` - Synopsis of all episodes mediainfo.
    - `{episode_metadata}` - Synopsis of all episodes metadata.
    - `{episode_metadata_mediainfo}` - Synopsis of all episodes metadata + mediainfo.
- Built **Series Mapper** _(for series)_:
  - New widget that will allow the user to match their episode(s) with aired, dvd, or absolute data parsed from **TVDB**. This data will allow NfoForge to accurately rename/manage files throughout the rest of the work flow.
  - New wizard page for the user to access this during the workflow.
- Support for plugin **filters** and **functions** for flat strings _(no documentation yet on this https://github.com/jesterr0/NfoForge/issues/97)_.
- Built a dialog crop widget that wraps the existing crop widget.

### Changed

- TODO add in changes to input pages etc...
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
- Removed **cinemagoer** dependency and replaced it with **imdbinfo**.
- Update niquests.
- All calls to mediainfo includes legacy stream data now _(to detect DTS core)_.
- General Settings Tab:
  - **Profile** selection drop down has been replaced by a checkbox **Enable External Plugins**.
  - Checkbox's are no longer stacked vertically and are inline with the text.
- Main window status label now updates with the current wizard plugin when selected.
- Crop Widget:
  - Improved script detection logic for AviSynth/VapourSynth scripts for manual crops.
  - Re-organized the widget to make things look nicer.
  - Added a description label.
  - Adjusted widget margins.
  - You can now pop out the text editor widget for the text input.
  - Text window is now read only.
- Plugin Changes:
  - `pre_upload` plugin is no longer passed kwargs `media_file, mi_obj, source_path`. These can be gathered from the config object easily.
- Improved the visuals of tracker format override widget.

### Fixed

- TokenTable widget labels had the wrong weight of bold.

### Removed

- `{movie_full_title}` has been removed (`{title_exact}` token replaces it).
- Movie settings page no longer has controls for clean title token and dynamic range control (this is now handled in Global Management).
- Advanced Input page _(existing functionality will still exist in the **Input** page)_.
- General settings source/encode extension filter control has been removed.

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
- Image page can now accept raw urls in any format, html, bbcode, raw urls etc. It'll attempt to parse them
  and convert them automatically to a format the backend needs for processing.
- Can now download images from existing URLs and re-host as needed to image hosts of the users selection.
- Screenshots subtitle color can now be selected via the color chooser widget to the right of the label.
- Add basic ui validation to avoid saving image host data if there is missing data detected.
- You can now select which image host you'd like to upload to for which tracker on the process page.
- Added a right click context menu to the Tracker/Status tree widget, to set all image hosts at once.
- Added the ability to select dropped URLs for each tracker.
- ImageBox now retries with a delay if there is networking issues.
- Added support to set **{ screen_shots }** columns, column space, and row space PER tracker.
- Can now set desired order you'd like your tracker(s) to process in.
- Can now choose desired image host per tracker on the process page. (Can use right click to set ALL trackers
  to a specific image host)
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
- Template sandbox mode/preview and Overview wizard page now shows Dummy screenshot data, since this is actually filled
  in the final process step.
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
- **movie_clean_token** UI widget had a bug when selecting/deleting the top most item would result in a prompt
  to ask the user if they'd like to reset to default over and over again.
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

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
