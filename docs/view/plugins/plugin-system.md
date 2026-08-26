# Plugin System

NfoForge plugins are trusted Python code loaded into the application process. Install only plugins whose source and author you trust. Enabled plugins are loaded once at startup; changing the enabled setting prompts you to restart NfoForge, and a restart is still required afterward for a new or changed plugin to actually be picked up.

## Local plugins

Place each plugin repository directly inside NfoForge's `plugins` directory and add `nfoforge-plugin.toml` at the repository root:

```toml
schema_version = 1
id = "example.my-plugin"
module = "plugin_my_plugin"
object = "plugin" # optional; this is the default
```

Directories without this manifest are not considered plugin candidates.

The ID is the permanent configuration identity and must be lowercase. It may contain numbers, dots, underscores, and hyphens. `module` must be one top-level Python module or package name inside that plugin's repository. It may resolve to a normal Python package or a compiled package with `__init__.pyd`; compiled plugins must target the same Python version and platform as NfoForge.

NfoForge loads that module directly from the repository without adding the repository to Python's global import path. Code inside a plugin package should use relative imports for its own modules, such as `from .client import MetadataClient`.

The module exports one typed definition:

```python
from src.plugins.api import PluginDefinition

plugin = PluginDefinition(
    display_name="My Plugin",
    version="1.0.0",
    token_replacer=replace_tokens,
)
```

Plugin code should import its public contracts from `src.plugins.api`. Assigning a function with the wrong signature to `PluginDefinition` is reported by BasedPyright without requiring NfoForge to inspect annotations at runtime.

The current runtime contract is plugin API version 2. Version 2 replaces the live `ProcessingContext` previously exposed to metadata transformers with the isolated `MetadataTransformContext` snapshot documented under Metadata Transformers.

## Installed packages

A Python distribution may expose the same `PluginDefinition` through the `nfoforge.plugins` entry-point group. The entry-point name is its stable ID:

```toml
[project.entry-points."nfoforge.plugins"]
"example.my-plugin" = "plugin_my_plugin:plugin"
```

Local repositories remain the recommended installation method for packaged NfoForge builds.

### ID collision precedence

Local plugin directories are loaded before installed entry points. If a local plugin and an entry point share the same ID, the local plugin registers first and wins; the entry point's registration then fails with a duplicate-ID error and is reported as a load failure rather than applied silently. This is deliberate: local plugins are the recommended installation method, so an installed package can never silently shadow one.

## Capabilities and failures

Wizard pages, token replacers, pre-upload processors, post-upload processors, metadata transformers, image host uploaders, and duplicate checkers are single-select capabilities. Jinja filters/functions, flat token filters, and custom edition/cut contributions from every valid plugin are combined while external plugins are enabled.

### Post-upload processors

A post-upload processor runs once per tracker, after that tracker's upload and torrent- client injection have both finished (or failed). Unlike a pre-upload processor, it makes no decision -- the tracker's work is already done -- so it receives a `PostUploadRequest` and returns nothing.

`PostUploadRequest.outcome` is one of four `PostUploadOutcome` values:

- `SUCCESS` -- the upload succeeded and injection succeeded, or injection was not needed
- `UPLOAD_FAILED` -- the upload itself failed
- `INJECTION_FAILED` -- the upload succeeded but torrent-client injection failed
- `SKIPPED` -- a pre-upload plugin returned `PreUploadDecision.SKIP` for this tracker

`PostUploadRequest.error` carries a scrubbed failure message for `UPLOAD_FAILED` and `INJECTION_FAILED`, and is `None` otherwise.

The hook does not fire when a tracker is simply disabled in Settings, and does not fire for a user-chosen mid-retry skip (declining a retry prompt after an automatic-retry budget is exhausted) -- `SKIPPED` is reserved for a pre-upload plugin's own decision.

A post-upload processor that raises is logged and otherwise ignored: the tracker's already-reported status is never changed by a broken notifier.

### Image host uploaders

An image host uploader plugin contributes a custom upload destination for screenshots, without waiting on a built-in host to be added to NfoForge. Set `image_host_uploader` on `PluginDefinition` to an instance of `BaseImageHostUploader` (`src.backend.image_host_uploading.base_image_host`) -- the same abstract base every built-in host implements:

```python
from src.backend.image_host_uploading.base_image_host import (
    BaseImageHostUploader,
    ImageUploadRequest,
)
from src.packages.custom_types import ImageUploadData

class MyHostUploader(BaseImageHostUploader):
    async def upload(
        self, request: ImageUploadRequest
    ) -> dict[int, ImageUploadData]:
        ...

plugin = PluginDefinition(
    display_name="My Image Host",
    version="1.0.0",
    image_host_uploader=MyHostUploader(),
)
```

Unlike built-in hosts, a plugin-provided host has no entry in **Settings -> Image Hosts** -- there is nothing there to enable, and no base URL or API key for NfoForge to store, since the plugin manages its own credentials and configuration. Its availability is entirely governed by the **Settings -> Plugins** selection: once configured there (and external plugins are enabled), it appears as **Plugin** in the per-tracker image host choice during the upload wizard, the same way every other host does.

### Duplicate checkers

A duplicate checker runs once per tracker, during the upload wizard's dupe-check phase -- before tracker titles, NFOs, or torrents exist, and before any upload happens. It supplements NfoForge's built-in per-tracker duplicate search (e.g. with a private cross-tracker database) rather than replacing or gating it: nothing today auto-skips a tracker because a duplicate was found, and this capability does not change that. Set `duplicate_checker` on `PluginDefinition` to a callable receiving a `DuplicateCheckRequest` (`config`, `tracker`, `media_input`, `media_search`, `timeout`) and returning a sequence of `TrackerSearchResult` -- always a sequence, never a bare string; a plugin that fails should raise, not return an error value.

Results are only merged into a tracker's dupe log when the built-in check for that tracker _succeeded_ (including "succeeded with zero hits"); if the built-in check itself failed (missing credentials, network error, an unsupported series tracker) the plugin's contribution for that tracker is not merged. A duplicate checker that raises, returns the wrong type, or runs past `timeout` is logged and treated as "nothing extra found" -- it never fails the dupe-check phase for other trackers.

### Custom edition/cut contributions

`{edition}` and `{cut}` are backed by a closed, curated table (`EDITION_INFO`/`CUT_EDITION_NAMES` in `src.backend.utils.rename_normalizations`). A plugin can extend that table rather than fork it: set `custom_editions` on `PluginDefinition` to a sequence of `CustomEditionContribution`, each pairing a `RenameNormalization` (`normalized` display value, `re_gex` case-insensitive detection patterns) with `is_cut`:

```python
from src.packages.custom_types import RenameNormalization
from src.plugins.api import CustomEditionContribution, PluginDefinition

plugin = PluginDefinition(
    display_name="My Editions",
    version="1.0.0",
    custom_editions=(
        CustomEditionContribution(
            entry=RenameNormalization("Fan Edit", (r"fan[\s\.\-_]*edit",)),
            is_cut=True,
        ),
    ),
)
```

`is_cut=True` keeps the entry in `{cut}` (so it survives on trackers whose title format switched to `{cut}`, e.g. Aither); `False` makes it Edition-only, appearing in `{edition}` but omitted from `{cut}`, the same way built-in marketing Editions (Criterion, Deluxe, Special, ...) already behave. A contribution's `normalized` name must not collide with another plugin's, or with a built-in `EDITION_INFO` entry -- both are rejected at registration, same as a duplicate Jinja filter or flat filter name.

Jinja filters apply to NFO templates using Jinja syntax. Flat token filters apply to the `{token|filter}` syntax used by filename templates, tracker-title templates, and qBittorrent save-path templates; the same filters are used by their Settings previews.

Loading failures are collected and shown together; one broken plugin does not stop startup. Duplicate IDs and template/filter names are rejected instead of silently overwriting another plugin. A configured but unavailable plugin falls back to built-in behavior without erasing the saved selection.

Use **Settings -> Plugins** to enable or disable external plugin execution, choose the plugin used for each single-select capability, and inspect loaded, failed, or configured-but-unavailable plugins. When plugins are disabled, no local plugin or `nfoforge.plugins` entry point is imported during startup. Saved selections remain intact, and the status table reports that discovery was skipped.

Metadata transformers and other network work run outside the Qt UI thread. Wizard pages are the exception and must interact with Qt only from the UI thread. Plugins should raise descriptive exceptions and honor the timeout in their typed request when one is supplied.
