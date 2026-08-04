# Plugin System

NfoForge plugins are trusted Python code loaded into the application process. Install
only plugins whose source and author you trust. Enabled plugins are loaded once at
startup; changing a plugin or the enabled setting requires restarting NfoForge.

## Local plugins

Place each plugin repository directly inside NfoForge's `plugins` directory and add
`nfoforge-plugin.toml` at the repository root:

```toml
schema_version = 1
id = "example.my-plugin"
module = "plugin_my_plugin"
object = "plugin" # optional; this is the default
```

Directories without this manifest are not considered plugin candidates.

The ID is the permanent configuration identity and must be lowercase. It may contain
numbers, dots, underscores, and hyphens. `module` must be one top-level Python module or
package name inside that plugin's repository. It may resolve to a normal Python package
or a compiled package with `__init__.pyd`; compiled plugins must target the same Python
version and platform as NfoForge.

NfoForge loads that module directly from the repository without adding the repository to
Python's global import path. Code inside a plugin package should use relative imports
for its own modules, such as `from .client import MetadataClient`.

The module exports one typed definition:

```python
from src.plugins.api import PluginDefinition

plugin = PluginDefinition(
    display_name="My Plugin",
    version="1.0.0",
    token_replacer=replace_tokens,
)
```

Plugin code should import its public contracts from `src.plugins.api`. Assigning a
function with the wrong signature to `PluginDefinition` is reported by BasedPyright
without requiring NfoForge to inspect annotations at runtime.

The current runtime contract is plugin API version 2. Version 2 replaces the live
`ProcessingContext` previously exposed to metadata transformers with the isolated
`MetadataTransformContext` snapshot documented under Metadata Transformers.

## Installed packages

A Python distribution may expose the same `PluginDefinition` through the
`nfoforge.plugins` entry-point group. The entry-point name is its stable ID:

```toml
[project.entry-points."nfoforge.plugins"]
"example.my-plugin" = "plugin_my_plugin:plugin"
```

Local repositories remain the recommended installation method for packaged NfoForge
builds.

### ID collision precedence

Local plugin directories are loaded before installed entry points. If a local plugin
and an entry point share the same ID, the local plugin registers first and wins;
the entry point's registration then fails with a duplicate-ID error and is reported
as a load failure rather than applied silently. This is deliberate: local plugins are
the recommended installation method, so an installed package can never silently
shadow one.

## Capabilities and failures

Wizard pages, token replacers, pre-upload processors, and metadata transformers are
single-select capabilities. Jinja filters/functions and flat token filters from every
valid plugin are combined while external plugins are enabled.

Jinja filters apply to NFO templates using Jinja syntax. Flat token filters apply to the
`{token|filter}` syntax used by filename templates, tracker-title templates, and
qBittorrent save-path templates; the same filters are used by their Settings previews.

Loading failures are collected and shown together; one broken plugin does not stop
startup. Duplicate IDs and template/filter names are rejected instead of silently
overwriting another plugin. A configured but unavailable plugin falls back to built-in
behavior without erasing the saved selection.

Use **Settings -> Plugins** to enable or disable external plugin execution, choose the
plugin used for each single-select capability, and inspect loaded, failed, or
configured-but-unavailable plugins. When plugins are disabled, no local plugin or
`nfoforge.plugins` entry point is imported during startup. Saved selections remain
intact, and the status table reports that discovery was skipped.

Metadata transformers and other network work run outside the Qt UI thread. Wizard pages
are the exception and must interact with Qt only from the UI thread. Plugins should
raise descriptive exceptions and honor the timeout in their typed request when one is
supplied.
