"""Which image host each tracker's screenshots go to.

The desktop Process page offers these in a combo box per tracker and
pre-selects the tracker's last-used host. A headless run takes that same
pre-selection. Nothing here asks anyone.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from nfoforge.context.processing_context import ProcessingContext
from nfoforge.enums.image_host import ImageHost, ImageSource
from nfoforge.enums.tracker_selection import TrackerSelection
from nfoforge.packages.custom_types import (
    DISABLED_HOST,
    ImageHostRef,
    ImageUploadFromTo,
)

if TYPE_CHECKING:
    from nfoforge.config.models import AppConfig
    from nfoforge.plugins.manager import PluginManager


def plugin_image_host_available(
    settings: AppConfig, plugin_manager: PluginManager
) -> bool:
    """Whether a loaded plugin currently provides image host uploads.

    The Settings -> Plugins selection is the single source of truth, same as
    every other plugin capability.
    """
    if not settings.general.enable_plugins:
        return False
    plugin_id = settings.plugins.image_host_uploader
    if not plugin_id:
        return False
    record = plugin_manager.get(plugin_id)
    return bool(record and record.definition.image_host_uploader is not None)


def available_image_hosts(
    settings: AppConfig, plugin_manager: PluginManager
) -> set[ImageHostRef]:
    """Every image host this profile could upload to right now."""
    hosts = {
        key
        for key, value in settings.image_hosts.by_selection().items()
        if value.enabled and value.is_configured()
    }
    # a plugin-provided image host has no entry in `by_selection()`; it
    # manages its own config
    if plugin_image_host_available(settings, plugin_manager):
        hosts.add(ImageHostRef(ImageHost.PLUGIN))
    return hosts


def find_image_host(name: str, available: Iterable[ImageHostRef]) -> ImageHostRef:
    """The available host `name` refers to.

    Matched without regard to case against a host's name ("Pixhost"), its
    kind ("PIXHOST") or its stored key ("CHEVERETO_V4:abc"); "Disabled" means
    no host. Raises `ValueError` when nothing, or more than one host, matches.
    """
    wanted = name.strip().casefold()
    if wanted == str(ImageHost.DISABLED).casefold():
        return DISABLED_HOST
    hosts = list(available)
    matches = [
        host
        for host in hosts
        if wanted
        in {
            host.key().casefold(),
            str(host).casefold(),
            host.kind.name.casefold(),
            str(host.kind).casefold(),
        }
    ]
    if len(matches) == 1:
        return matches[0]
    offered = ", ".join(sorted(str(host) for host in hosts)) or "none"
    if not matches:
        raise ValueError(
            f"Image host {name!r} is not available in this config (available: "
            f"{offered})"
        )
    raise ValueError(
        f"{name!r} matches several image hosts ({', '.join(map(str, matches))}); "
        "name one by its label"
    )


def default_image_hosts(
    context: ProcessingContext,
    settings: AppConfig,
    plugin_manager: PluginManager,
    trackers: Iterable[TrackerSelection],
    preferred: str | None = None,
) -> tuple[dict[TrackerSelection, ImageUploadFromTo], list[str]]:
    """Each tracker's image host.

    A `preferred` host, named for the run, is every tracker's host; it must be
    available (`find_image_host` raises otherwise). Without one, each tracker
    gets what the Process page pre-selects: its last-used host where that is
    still available, and no host otherwise. Returns notes naming every
    tracker whose last-used host could not be used, so a run that uploads no
    screenshots says why.
    """
    shared = context.shared_data
    if shared.url_data:
        return {
            tracker: ImageUploadFromTo(ImageSource.URLS, ImageSource.URLS)
            for tracker in trackers
        }, []

    has_images = bool(shared.loaded_images)
    available = available_image_hosts(settings, plugin_manager) if has_images else set()
    # a host this run already uploaded to can be served from the stored URLs
    available |= {
        host
        for host in shared.uploaded_images_by_host
        if isinstance(host, ImageHostRef) and host != DISABLED_HOST
    }

    if preferred is not None:
        chosen = find_image_host(preferred, available) if has_images else DISABLED_HOST
        return {
            tracker: ImageUploadFromTo(ImageSource.IMAGES, chosen)
            for tracker in trackers
        }, []

    hosts: dict[TrackerSelection, ImageUploadFromTo] = {}
    notes: list[str] = []
    for tracker in trackers:
        last_used = settings.trackers.last_used_image_host.get(tracker)
        if isinstance(last_used, ImageHostRef) and last_used in available:
            destination: ImageHostRef = last_used
        else:
            destination = DISABLED_HOST
            if has_images:
                notes.append(
                    f"{tracker}: no image host is set for it"
                    if last_used is None
                    else f"{tracker}: '{last_used}' is not available in this config"
                )
        hosts[tracker] = ImageUploadFromTo(ImageSource.IMAGES, destination)
    return hosts, notes
