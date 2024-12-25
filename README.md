# NfoForge

A powerful media upload assistant.

## Information

NfoForge is currently under active development, and I’m excited to share it with the community now that it has reached a stable stage.

At present, **Movies** are the only supported media type. However, support for **TV shows** and **Anime** is already planned and will be added in the near future.

Comprehensive documentation is on the way and will be available soon.

## Key Features

- Token system for advanced media file renaming.
- Integration with TMDB and IMDb for title parsing.
- Flexible Jinja-based template system for .NFO file generation.
- Screenshot generation and upload, including comparisons.
- Output file organization, saving .torrent and .NFO files to disk.
- Torrent cloning support for multi-tracker releases without re-generation.
- Duplicate release checker - checks trackers for duplicates pre-upload.
- Integration with Deluge, qBittorrent, Transmission, rTorrent, and watch folders, as well as fast resume support.
- Plugin support for Python (.py) and compiled (.pyd) files (.pyd compiled files require the same Python version as NfoForge).
- Support for movie files in MKV and MP4 format.
- Additional format support and features coming soon!

## Supported Trackers

- BeyondHD
- MoreThanTv
- TorrentLeech

_Supported trackers will be added overtime_

## Supported Operating Systems

- Windows 8.1+

_Support for Linux is coming soon_

## Supported Image Hosts

- Chevereto v3/v4
- ImageBox
- ImageBB

## Requirements

- TMDB Api <a href="https://www.themoviedb.org/settings/api" target="_blank">Key v3</a>
- FFMPEG or <a href="https://github.com/jessielw/FrameForge/" target="_blank">FrameForge</a> depending on your preferred image generation type

## Thanks and Credits

- aiohttp
- beautifulsoup4
- cinemagoer
- deluge-web-client
- Guessit
- iso639-lang
- jinja2
- L4G's Upload Assistant, for inspiration
- pymediainfo
- pyimgbox
- PySide6
- qbittorrent-api
- requests
- tomlkit
- torf
- transmission-rpc

## Support

[Github](https://github.com/jesterr0/NfoForge)

## Donations

NfoForge is a free application. Donations of any size are greatly appreciated and will support NfoForge's active development. Thank you!

#### Bitcoin

<img src="https://github.com/user-attachments/assets/88b7643f-8567-4d6d-ade4-13d725490062" alt="bitcoin:bc1qwkhxfea0zmnuatt9fe784q87w0mwl72wd24xxc" width="140">\
BTC: `bc1qwkhxfea0zmnuatt9fe784q87w0mwl72wd24xxc`

#### Ethereum

<img src="https://github.com/user-attachments/assets/e34fa9d4-531f-4586-9deb-47413861279a" alt="ethereum:0x86a726C7158b852C8001Fb6762f3a263742529e6" width="140">\
ETH: `0x86a726C7158b852C8001Fb6762f3a263742529e6`
