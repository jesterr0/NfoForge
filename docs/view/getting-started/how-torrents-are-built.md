# How Torrents Are Built

Hashing the media is the most expensive step in a run, so NfoForge does it once no matter how many trackers you selected.

## One hash, one torrent per tracker

A run builds a single **base torrent** from your media, then makes one copy of it for each tracker.

The base torrent carries no tracker information at all -- no announce URL, no source tag, no comment. It is never uploaded anywhere. It sits at the top of the run's folder, alongside the per-tracker folders rather than inside any of them.

Each tracker's torrent is a copy of that base with only that tracker's own details written into it:

- its announce URL, or none at all if the tracker issues none
- its source tag
- its comment

A tracker that sets none of these gets a torrent with none of them, so nothing belongs to a torrent except the tracker it was made for.

## Piece size

Piece size is chosen from the size of the release, using a fixed scale:

| Release size     | Piece size |
| ---------------- | ---------- |
| up to 50 MiB     | 64 KiB     |
| up to 150 MiB    | 128 KiB    |
| up to 350 MiB    | 256 KiB    |
| up to 512 MiB    | 512 KiB    |
| up to 1 GiB      | 1 MiB      |
| up to 4 GiB      | 2 MiB      |
| up to 12 GiB     | 4 MiB      |
| up to 20 GiB     | 8 MiB      |
| more than 20 GiB | 16 MiB     |

The same scale applies to every release, whichever trackers you picked. The 16 MiB ceiling is at or below the limit of every tracker NfoForge supports, so one hash is valid for all of them.

!!! note

    Because the choice depends only on release size, a prepared job stays valid if you
    later run it against a different set of trackers.

There is no piece size setting to configure.

## mkbrr and torf

NfoForge hashes with [mkbrr](https://github.com/autobrr/mkbrr) when it is enabled and available, and falls back to the built-in torf library otherwise. Both are given the same piece size and produce the same torrent for the same media.

The two differ in one visible detail: the `created by` field names whichever one did the hashing.

## Excluded files

Index sidecars generated during screenshot work (`.lwi`, `.ffindex`) are left out of the torrent. They stay on disk next to your media; they are simply not part of what is uploaded or seeded.

## Saved jobs

A saved job stores the base torrent alongside its screenshots, MediaInfo and NFOs. Resuming reuses it and skips hashing entirely, as long as every file the torrent covers is unchanged in size and modified time. If anything changed, the job re-hashes.
