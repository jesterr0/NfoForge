# Series Support

NfoForge supports series workflows for standard TV episodes, daily/date releases, anime/absolute-numbered releases, and episode packs.

## Current workflow

When media search identifies the input as a series, the wizard opens a **Series Match** step before rename. This step maps each selected file to TVDB episode metadata and chooses the release-format token set.

### Choosing the episode ordering

TVDB publishes several orderings of the same season — aired, DVD, absolute — and the same season/episode pair names a different episode in each. NfoForge scores every ordering against the filenames and pre-selects the one that fits, showing the evidence on each entry in the **TVDB Order** list:

```
Aired Order — 20 eps · 20/20 matched · titles 100%
DVD Order — 19 eps · 19/20 matched · titles 47%
```

Coverage counts every episode the files claim, and the title figure compares each filename's own episode title against the episode its number lands on. Pick a different ordering whenever you disagree; your existing rows are re-read against it rather than discarded. If most of the filenames disagree with the selected ordering, a warning appears above the file list, and individual rows say which episode their title actually belongs to (`regex (title -> E02?)`).

### Mapping files to episodes

The **Episode(s)** column takes a span, not just a number:

| Typed | Means                                              |
| ----- | -------------------------------------------------- |
| `3`   | Episode 3                                          |
| `1-2` | A file covering both parts of a two-part episode   |
| `1,5` | A file covering two episodes that are not adjacent |

**Matched Episode** shows the episode each row resolved to, so a number that looks right while naming the wrong episode is visible before anything is renamed. **Title Override** replaces the episode title for that file; leave it blank to use TVDB's.

Matching weighs numbers and titles together. Where a filename carries no episode number, its title is matched against the season — and against whole multi-part stories, so `Show.Lost.and.Found.mkv` maps to `S01E01-E02` rather than to half of it. Where a filename names a part (`A.Moral.Star.2`, `Supernova.1`), it maps to that part alone; a bare trailing number counts as a part only when the rest of the title is the story's own and the number fits within it, so `Apollo 13` is left alone. Where a filename states an episode the ordering does not list, a strong title match to an unclaimed episode wins and the row reads `title`.

A season and episode NfoForge reads cleanly from a filename is kept even when the selected ordering has no such episode — the row is marked `parsed (no TVDB match)` and highlighted rather than dropped, so the pack still validates and you can correct it if it is wrong.

A file covering several episodes is named after the title its episodes share once part markers are removed, so `S01E01-E02` holding "Lost & Found (1)" and "Lost & Found (2)" renames to `Show.S01E01-02.Lost.and.Found...`. Where the episodes have genuinely different titles, none is used — one episode's title would not describe the file. Tracker release names never carry an episode title for a span, which is what those trackers' own rules require.

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
- **DVD**

Selecting DVD order on the Series Match page selects the **DVD** token set, which has its own filename and title fields in Settings → Series. It ships as a copy of the Standard pair, so nothing is named differently until you edit it; a profile saved before the DVD fields existed reads the Standard tokens for them.

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
