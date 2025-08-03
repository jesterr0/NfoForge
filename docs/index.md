# NfoForge

A powerful media upload assistant featuring a step-by-step [wizard](view/getting-started/using-the-wizard.md).

## Information

NfoForge is currently under active development, and I’m excited to share it with the community now that it has reached a stable stage.

At present, **Movies** are the only supported media type. However, support for **TV shows** and **Anime** is already planned and will be added in the near future.

## Key Features

- Token system for advanced media file renaming.
- Integration with TMDB, IMDb, TVDB, and MAL for title parsing.
- Flexible Jinja-based template system for NFO file generation.
- Screenshot generation and upload, including comparisons.
- Output file organization, saving .torrent and NFO files to disk.
- Torrent cloning support for multi-tracker releases without re-generation.
- Duplicate release checker - checks trackers for duplicates pre-upload.
- Integration with Deluge, qBittorrent, Transmission, rTorrent, and watch folders, as well as fast resume support.
- Plugin support for Python (.py) and compiled (.pyd) files (.pyd compiled files require the same Python version as NfoForge).
- Support for movie files in MKV and MP4 format.
- Automatic detection for light/dark mode (with a manual override if desired) _Windows only_.
- Additional format support and features coming soon!

## Supported Trackers

- BeyondHD
- MoreThanTV
- TorrentLeech
- PassThePopcorn
- ReelFliX
- Aither
- HUNO
- LST
- DarkPeers

<!-- prettier-ignore -->
!!! info
    Supported trackers will be added over time. If you'd like a tracker added, open an [issue](https://github.com/jesterr0/NfoForge/issues/new) and it will be considered. *Pull requests are also welcome if you have the ability.*

## Supported Operating Systems

- Windows 8.1+
- Linux (tested on Ubuntu 24.04.1 LTS)
- MacOs _(untested)_

## Supported Image Hosts

- Chevereto v3/v4
- ImageBox
- ImageBB
- PTPIMG

## Requirements

- TMDB Api [key (v3)](https://www.themoviedb.org/settings/api)
- FFMPEG and/or [FrameForge **1.4.0+**](https://github.com/jessielw/FrameForge/) depending on your preferred image generation type

## Support

If you have questions, need support, or want a new feature, please open an issue on [GitHub](https://github.com/jesterr0/NfoForge).

## Attribution

![TMDB](../../images/misc/tmdb_med.png){ width=100%, style="max-width: 64px;" }  
Metadata provided by [TVDB](https://www.thetvdb.com/). Please consider adding missing information or [subscribing](https://thetvdb.com/subscribe).

![TVDB](../../images/misc/tvdb.png){ width=100%, style="max-width: 64px; background-color: #ffffff47; border-radius: 5px; padding: 3px;" }  
Metadata provided by [TMDB](https://www.themoviedb.org/).

## Donations

NfoForge is a free application. Donations of any size are greatly appreciated and will support NfoForge's active development. Thank you!

#### Bitcoin

<img src="https://github.com/user-attachments/assets/88b7643f-8567-4d6d-ade4-13d725490062" alt="bitcoin:bc1qwkhxfea0zmnuatt9fe784q87w0mwl72wd24xxc" width="140"><br />
BTC: `bc1qwkhxfea0zmnuatt9fe784q87w0mwl72wd24xxc`

#### Ethereum

<img src="https://github.com/user-attachments/assets/e34fa9d4-531f-4586-9deb-47413861279a" alt="ethereum:0x86a726C7158b852C8001Fb6762f3a263742529e6" width="140"><br />
ETH: `0x86a726C7158b852C8001Fb6762f3a263742529e6`
