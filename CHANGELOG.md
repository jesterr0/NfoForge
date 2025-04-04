# Changelog

All notable changes to this project will be documented in this file starting with **0.6.0**.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
