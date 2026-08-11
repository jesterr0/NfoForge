# Series Support

NfoForge supports series workflows for standard TV episodes, daily/date releases,
anime/absolute-numbered releases, and episode packs.

## Current workflow

When media search identifies the input as a series, the wizard opens a **Series Match**
step before rename. This step maps each selected file to TVDB episode metadata and
chooses the release-format token set.

Supported release-format token sets:

- **Standard**
- **Daily / Date**
- **Anime / Absolute**

DVD order can be used as a TVDB episode ordering when available, but it currently uses
the **Standard** release-format token set. DVD is not a separate configurable
filename/title format yet.

## Tracker support

NfoForge keeps backend guards in place and disables known unsupported series trackers in
the wizard where possible.

| Tracker                                                          | Series status                        | Notes                                                               |
| ---------------------------------------------------------------- | ------------------------------------ | ------------------------------------------------------------------- |
| TorrentLeech                                                     | Supported                            | Uses TV episode HD/SD categories and TV box set category for packs. |
| BeyondHD                                                         | Supported                            | Uses TV category plus pack and special flags where applicable.      |
| Aither, HUNO, LST, DarkPeers, ShareIsland, UploadCX, OnlyEncodes | Supported through UNIT3D upload flow | Sends TV category and TVDB metadata when available.                 |
| PassThePopcorn                                                   | Blocked                              | NfoForge does not support this series upload path yet.              |
| ReelFliX                                                         | Blocked                              | NfoForge does not support this series upload path yet.              |

If a tracker rejects a series upload, keep the generated torrent/NFO output and verify
the tracker's current rules before retrying.

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
