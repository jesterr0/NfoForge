# Plugin System

NfoForge plugins are trusted Python code loaded into the application process. Install
only plugins whose source and author you trust. Plugins are loaded once at startup;
changing one requires restarting NfoForge.

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
numbers, dots, underscores, and hyphens. The module may be a normal Python package or a
compiled package with `__init__.pyd`; compiled plugins must target the same Python
version and platform as NfoForge.

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

## Installed packages

A Python distribution may expose the same `PluginDefinition` through the
`nfoforge.plugins` entry-point group. The entry-point name is its stable ID:

```toml
[project.entry-points."nfoforge.plugins"]
"example.my-plugin" = "plugin_my_plugin:plugin"
```

Local repositories remain the recommended installation method for packaged NfoForge
builds.

## Capabilities and failures

Wizard pages, token replacers, pre-upload processors, and metadata transformers are
single-select capabilities. Jinja filters/functions and flat token filters from every
valid plugin are combined while external plugins are enabled.

Loading failures are collected and shown together; one broken plugin does not stop
startup. Duplicate IDs and template/filter names are rejected instead of silently
overwriting another plugin. A configured but unavailable plugin falls back to built-in
behavior without erasing the saved selection.

Use **Settings -> Plugins** to enable or disable external plugin execution, choose the
plugin used for each single-select capability, and inspect loaded, failed, or
configured-but-unavailable plugins. Disabling plugin execution keeps the selections
intact and does not hide discovery diagnostics.

Metadata transformers and other network work run outside the Qt UI thread. Wizard pages
are the exception and must interact with Qt only from the UI thread. Plugins should
raise descriptive exceptions and honor the timeout in their typed request when one is
supplied.
