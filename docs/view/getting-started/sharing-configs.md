# Sharing and Moving a Configuration

**Settings → General** has an export and an import button beside your [data folder](upgrading.md#where-your-data-lives-now). Export writes a `.zip` holding one or more profiles and the NFO templates they use; import brings one back, on this machine or another.

This is not the same as the import button next to it, which brings across a whole previous NfoForge installation. That one is for upgrading. This one produces a file you can copy to another machine, keep as a backup, or hand to someone else.

## What a bundle holds

```
nfoforge-config-2026-09-17.zip
├── nfoforge-export.toml    the manifest
├── profiles/               the profiles you picked
└── templates/              the NFO templates those profiles name
```

Templates are included because a profile names them by filename. Sent on its own, a profile arrives with every template reference pointing at nothing, so the ones it uses come with it. The export window lists them before you save, and marks any the profile names but which are no longer on disk.

Not included, deliberately:

| Not in a bundle | Why |
| --- | --- |
| Program preferences | Which profile was open and where the window was -- not settings anyone would want to receive |
| Plugin settings | A plugin's own configuration and credentials, and plugins are not in a bundle |
| Tracker cookies | Live sessions |
| Plugins and tools | See [Installing a plugin](../plugins/plugin-system.md#installing-a-plugin) |

## Credentials

**Credentials are removed unless you tick "Include credentials".** That covers tracker API keys, RSS keys, passkeys, announce URLs, usernames, passwords, two-factor seeds, session cookies, torrent client logins and your TMDB key. The export summary lists every value that was removed.

Your **releaser name** and **group tag** are not credentials and are kept. They are usually the reason a setup is worth sharing, and they are not secret.

Tick the box only to move a configuration to another machine of your own. A bundle with credentials in it holds them in plain text; treat the file exactly as you would the credentials themselves.

!!! tip "A bundle without credentials is still a complete setup" Tracker selection and order, title and filename templates, screenshot settings, image host choices, naming rules and your NFO templates all come across. Only the values that identify you are blank.

## Importing

Pick a bundle and NfoForge shows what is in it and what importing it would do, before anything is written.

**Nothing is ever overwritten.** When a profile or template name is already in use, you choose what happens:

- **Keep both** (the default) -- what is coming in lands under `name (2)`. Nothing you have is touched. A profile imported this way is repointed at the templates that arrived with it, so it renders the way it did for whoever exported it rather than picking up a template of yours that happens to share a name.
- **Skip** -- what is already here is kept and the incoming copy is discarded.
- **Replace** -- the incoming copy wins, and a dated copy of what was there is kept in an `old_configs` folder beside it.

A template that is already here **and identical** is recognised rather than copied again, so importing the same bundle twice does not fill the folder with duplicates.

### What is adjusted on the way in

**Paths that belonged to the exporting machine are cleared**: the working directory, and the locations of FFmpeg, FFprobe, FrameForge and mkbrr. They are almost never right on another machine, and a path pointing at a drive that is not there fails later, in the middle of a run. The working directory falls back to your `workspace` folder and the tools are detected again; set them yourself under **Settings → General** and **Settings → Dependencies** if you keep them somewhere particular. The import summary names everything that was cleared.

**An older configuration is brought up to date.** A bundle exported by an earlier NfoForge is migrated through each schema version on the way in, the same way opening an old profile is. A bundle from a _newer_ NfoForge is refused with a message saying so -- there is no way to convert a configuration backwards.

**A profile that would not load is refused before anything is written.** If any profile in the bundle fails validation, the whole import stops and your existing profiles are untouched. The alternative is a file that lands successfully and takes the next launch down.

### What you are told afterwards

A summary lists what landed, what was renamed or skipped, what was cleared, and anything left for you to do — including **plugins an imported profile selects that are not installed here**. Those capabilities fall back to NfoForge's own until you install the plugins; the selections themselves are kept, so they start working once the plugin arrives.

The window is shown once, so a copy is appended to `logs/migration.log` inside your data folder — the same file the upgrade writes to, and one that log tidying leaves alone.

### A single profile file

The import button also accepts a bare `.toml`. **Save As** in Settings produces exactly that, so a profile someone sent you before bundles existed still works. It carries no templates, and it carries credentials in full, because nothing removed them.
