# Series Support

NfoForge supports series workflows for standard TV episodes, daily/date releases, anime/absolute-numbered releases, and episode packs.

## Current workflow

When media search identifies the input as a series, the wizard opens a **Series Match** step before rename. This step maps each selected file to TVDB episode metadata and chooses the release-format token set.

## Season packs

Opening a folder works for any of these layouts:

| Layout | What gets renamed |
| --- | --- |
| Episodes directly in the folder, one season | The folder, from the **Season Folder** token, plus each episode file. |
| Episodes directly in the folder, several seasons | The same, except `{season_number}` renders the range (`S01-S05`). |
| Episodes in `Season NN` subfolders | The opened folder takes the season range; each subfolder is renamed for its own season. |

Only video files count as episodes. Subtitles and per-episode `.nfo` files named after an episode (`ep01.en.srt`, `ep01.nfo`) are renamed to follow it, keeping any language or ordering segment. Anything else in the pack — `Extras`, artwork, samples — is left untouched and simply moves with the folder around it.

### Season folder tokens

- **Season Folder** names the opened folder. In a single-season pack that folder _is_ the season folder, so this one token covers both cases.
- **Season Subfolder** names each `Season NN` subfolder in a pack that keeps its seasons apart. Leave it blank to reuse the Season Folder token, which names each subfolder after its own season while the folder above carries the range.

Set the subfolder token to `Season {season_number|zfill(2)}` for plain `Season 01` / `Season 02` subfolders inside a scene-named pack folder.

### Multi-season packs on UNIT3D trackers

UNIT3D records one season per upload, so a pack spanning seasons is filed under its lowest season. NfoForge asks for confirmation on the Trackers page before continuing. The release name and NFO still show the full range.

Supported release-format token sets:

- **Standard**
- **Daily / Date**
- **Anime / Absolute**

DVD order can be used as a TVDB episode ordering when available, but it currently uses the **Standard** release-format token set. DVD is not a separate configurable filename/title format yet.

## Tracker support

NfoForge keeps backend guards in place and disables known unsupported series trackers in the wizard where possible.

| Tracker | Series status | Notes |
| --- | --- | --- |
| TorrentLeech | Supported | Uses TV episode HD/SD categories and TV box set category for packs. |
| BeyondHD | Supported | Uses TV category plus pack and special flags where applicable. |
| Aither, HUNO, LST, DarkPeers, ShareIsland, UploadCX, OnlyEncodes | Supported through UNIT3D upload flow | Sends TV category and TVDB metadata when available. |
| PassThePopcorn | Blocked | NfoForge does not support this series upload path yet. |
| ReelFliX | Blocked | NfoForge does not support this series upload path yet. |

If a tracker rejects a series upload, keep the generated torrent/NFO output and verify the tracker's current rules before retrying.

## Useful series tokens

Series filename/title templates can use:

- `{season_number}`
- `{episode_number}`
- `{episode_number_absolute}`
- `{episode_title}`
- `{episode_title_clean}`
- `{episode_title_exact}`
- `{air_date}`
- `{episode_air_date}`

NFO templates can also use pack-oriented summary tokens:

- `{{ episode_mediainfo }}`
- `{{ episode_metadata }}`
- `{{ episode_metadata_mediainfo }}`
- `{{ total_seasons }}`
- `{{ total_episodes }}`

`{{ total_seasons }}` and `{{ total_episodes }}` report what the _series_ has, from TMDB/TVDB — not how many the release contains.
