# Changelog

All notable changes to this project will be documented in this file starting with **0.6.0**.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- You can organize your URL formatting in "Tracker" settings PER tracker.
- Image generation Log widget now tells the user what "Mode" they are generating images in.
- Image page now supports opening .jpg/.jpeg.
- Screenshots subtitle color can now be selected via the color chooser widget to the right of the label.
- Add basic ui validation to avoid saving image host data if there is missing data detected.
- You can now select which image host you'd like to upload to for which tracker on the process page.
- Added a right click context menu to the Tracker/Status tree widget, to set all image hosts at once.
- Added the ability to select dropped URLs for each tracker.
- ImageBox now retries with a delay if there is networking issues.
- Added support to set **{ screen_shots }** columns, column space, and row space PER tracker.
- Can now set desired order you'd like your tracker(s) to process in.
- Can now choose desired image host per tracker on the process page.
- Now uploads to multiple image hosts asynchronous.
- Numerous optimizations and improvements.

### Changed

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

### Fixed

- Image page open image button icon was improperly sized.
- Issue where modifying the tracker order on the Process page would throw an error.
- Fixed incorrect frame shape/style on the client widget.
- Prevent error when launching program with `--config *.TOML` (capitalized ext).
- ImageBox returning improperly ordered images.
- ImageBox not returning all images after uploading.
- Capitalization of warning prompt in Template settings.

### Removed

- Image host selection is no longer in the General settings page.
- Image uploading is not done in the Image wizard page anymore.
