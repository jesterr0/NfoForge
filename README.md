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
- Automatic detection for light/dark mode (with a manual override if desired).
- Additional format support and features coming soon!

## Supported Trackers

- BeyondHD
- MoreThanTv
- TorrentLeech
- PassThePopcorn
- ReelFliX
- Aither

_Supported trackers will be added overtime_

## Supported Operating Systems

- Windows 8.1+
- Linux (tested on Ubuntu 24.04.1 LTS)

## Supported Image Hosts

- Chevereto v3/v4
- ImageBox
- ImageBB

## Requirements

- TMDB Api [key v3](https://www.themoviedb.org/settings/api)
- TVDB Api [key](https://thetvdb.com/api-information)
- FFMPEG and/or [FrameForge](https://github.com/jessielw/FrameForge/) depending on your preferred image generation type

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

## Basic Setup Guide

- Download the current latest release, extract, and run the executable (or run it in your python environment).
- You should go through **Settings** and setup a few required things.
  - Create a template, when you select the button to create a new one you'll be presented with a very basic starting template.<br><img src="https://github.com/user-attachments/assets/083e31d5-8f3e-4b94-a3e2-5acc1672d1e5" alt="template" width="350">
  - You are **required** to have a TMDB Api Key (v3), set this below.<br><img src="https://github.com/user-attachments/assets/3839b849-eca6-4ddd-b2b7-611f0d4b5226" alt="tmdb api key" width="350">
  - You'll of course want to enable you desired tracker(s).<br><img src="https://github.com/user-attachments/assets/2410b5d6-f771-4d1d-999b-06a739296861" alt="enable trackers" width="350">
    - Ensure you expand the tracker and fill out the required details.<br><img src="https://github.com/user-attachments/assets/85c19583-a14e-47f1-8d1c-4026375774f7" alt="tracker details" width="350">
- You can simply save your settings, open a file and walk through the wizard to complete your upload.

_This is a basic setup guide, proper guides/documentation will be added in the near future._

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
