# Changelog

All notable changes to this project will be documented in this file starting with **0.6.0**.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [unreleased]

### Added

- 

### Changed

- Updated pymediainfo to v7.0.1.

### Fixed

- 

### Removed

- 

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
