# Plugin System

NfoForge plugins are trusted Python code loaded into the application process. Install only plugins whose source and author you trust. Enabled plugins are loaded once at startup; changing the enabled setting prompts you to restart NfoForge, and a restart is still required afterward for a new or changed plugin to actually be picked up.

## Installing a plugin

**Settings → Plugins** names your `plugins` folder, opens it, and offers **Install** with two entries: **From folder...** and **From archive...**. Both do the same thing a manual copy does, with the manifest read first, so a plugin that could never load is refused now rather than reported as a load failure on the next launch.

Before copying anything, NfoForge checks that the folder or archive holds one `nfoforge-plugin.toml`, that the manifest is valid, and that the module it names is actually there. It then shows what it found -- the ID, the module and where it came from -- and asks. **The plugin is never imported during any of this**: a plugin is trusted code that runs inside NfoForge, and nothing runs it before you have said yes.

### Updating a plugin

Choosing a plugin whose ID is already installed is an **update**, not an error. The dialog says what it is replacing, and installing moves the copy you have into `old_plugins` inside your plugins folder, timestamped. Nothing is deleted, so an update that turns out worse than what it replaced can be put back by hand. Archived copies sit a level too deep for NfoForge to load, so they are kept without being seen.

NfoForge cannot tell you which of the two is newer. A plugin's version lives in the `PluginDefinition` its module exports, and reading it would mean running the code you are being asked to approve -- so the dialog names the path being replaced and leaves the judgement to you.

Two clashes cannot be resolved by replacing and are refused outright:

- An ID that **ships with NfoForge**. A release's own example cannot be replaced; your copy would register first and the example would be reported as broken on every launch.
- A **module name** another installed plugin declares. The loader resolves a module by name and refuses a second one from a different location, so the two cannot coexist whichever is installed second. Plugins built from the same example start out sharing the example's module name, which makes this the likelier clash of the two -- and left to startup it reads as an install that silently did nothing.

An archive is accepted whether the manifest sits at its root or inside a single wrapping folder, which is the shape a downloaded repository unpacks into. Disposable development content -- virtual environments, `.git`, bytecode, build and coverage output -- is left behind; source, tests, documentation and resources come across.

A newly installed plugin is on disk but inert. Plugins are imported once, at startup, so **NfoForge has to be restarted** before it is available, and external plugins have to be enabled.

Copying a folder in by hand still works and is described below.

## Local plugins

Place each plugin repository directly inside the `plugins` folder of [your NfoForge data folder](../getting-started/upgrading.md#where-your-data-lives-now) and add `nfoforge-plugin.toml` at the repository root:

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
from nfoforge.plugins.api import PluginDefinition

plugin = PluginDefinition(
    display_name="My Plugin",
    version="1.0.0",
    token_replacer=replace_tokens,
)
```

Plugin code should import its public contracts from `nfoforge.plugins.api`. Assigning a function with the wrong signature to `PluginDefinition` is reported by BasedPyright without requiring NfoForge to inspect annotations at runtime.

The current runtime contract is plugin API version 2. Version 2 replaces the live `ProcessingContext` previously exposed to metadata transformers with the isolated `MetadataTransformContext` snapshot documented under Metadata Transformers.

## Working from a checkout

Plugins load from your data folder, not from wherever you keep the source. Without help that makes the development loop "edit, copy into the data folder, restart", and the copy is a snapshot: the moment you forget to make it, you are testing the previous version.

`NFOFORGE_DEV_PLUGINS` points NfoForge at a different plugins folder. Set it to a folder of checkouts -- the same shape as the plugins folder it stands in for, one directory per plugin -- and everything in it loads in place:

```powershell
$env:NFOFORGE_DEV_PLUGINS = "D:\src\nfoforge-plugins"
uv run start_ui.py
```

```
D:\src\nfoforge-plugins\
    my-plugin\            <- a checkout, with nfoforge-plugin.toml at its root
    another-plugin\       <- and another, worked on at the same time
```

Name more than one folder by separating them with your platform's path separator, the same way `PATH` does: `;` on Windows, `:` elsewhere. They are read in the order written, so if two of them hold the same plugin the first one wins.

**It replaces your plugins folder rather than adding to it.** While the variable is set, the folder in your data directory is not read at all. That is deliberate: it makes a development run the same arrangement a real installation has, rather than a fourth thing that exists nowhere else, and it means a plugin can never be quietly picked up from a copy you had forgotten was installed. Everything below that point -- load order against the shipped examples, ID collisions, the status table -- behaves exactly as it does in production.

Two mistakes are reported rather than passed over, in **Settings -> Plugins**, because the path was typed on purpose and it has taken the real folder out of the run:

- naming a path that does not exist, or a folder with no plugins in it
- naming **a plugin** where a folder *of* plugins belongs -- that is, a directory with `nfoforge-plugin.toml` at its own root. NfoForge recognises this one and tells you to name the folder containing it.

While the variable is set, **Settings -> Plugins** names the folders in force, and each loaded plugin's row shows the directory it came from. The plugins folder is still named there, and **Install** still writes to it, because that is where a plugin belongs once the variable is gone.

A restart is still required. Plugins are imported once, at startup; nothing here reloads them while NfoForge is running.

Released builds ignore the variable. A plugin is trusted Python executed inside NfoForge's process, so an environment variable must not be able to decide what a release imports. It is honoured when running from source and by the debug executable shipped beside the main one, which is the same rule `NFOFORGE_DATA_DIR` follows.

## Installed packages

A Python distribution may expose the same `PluginDefinition` through the `nfoforge.plugins` entry-point group. The entry-point name is its stable ID:

```toml
[project.entry-points."nfoforge.plugins"]
"example.my-plugin" = "plugin_my_plugin:plugin"
```

Local repositories remain the recommended installation method for packaged NfoForge builds.

### ID collision precedence

Local plugin directories are loaded before installed entry points. If a local plugin and an entry point share the same ID, the local plugin registers first and wins; the entry point's registration then fails with a duplicate-ID error and is reported as a load failure rather than applied silently. This is deliberate: local plugins are the recommended installation method, so an installed package can never silently shadow one.

The full order is your plugins folder, then the examples shipped with the release, then installed entry points. `NFOFORGE_DEV_PLUGINS` substitutes for the first of those rather than adding a fourth, so none of this changes while it is set -- only where the first group is read from.

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

An image host uploader plugin contributes a custom upload destination for screenshots, without waiting on a built-in host to be added to NfoForge. Set `image_host_uploader` on `PluginDefinition` to an instance of `BaseImageHostUploader` (`nfoforge.backend.image_host_uploading.base_image_host`) -- the same abstract base every built-in host implements:

```python
from nfoforge.backend.image_host_uploading.base_image_host import (
    BaseImageHostUploader,
    ImageUploadRequest,
)
from nfoforge.packages.custom_types import ImageUploadData

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

`{edition}` and `{cut}` are backed by a closed, curated table (`EDITION_INFO`/`CUT_EDITION_NAMES` in `nfoforge.backend.utils.rename_normalizations`). A plugin can extend that table rather than fork it: set `custom_editions` on `PluginDefinition` to a sequence of `CustomEditionContribution`, each pairing a `RenameNormalization` (`normalized` display value, `re_gex` case-insensitive detection patterns) with `is_cut`:

```python
from nfoforge.packages.custom_types import RenameNormalization
from nfoforge.plugins.api import CustomEditionContribution, PluginDefinition

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
