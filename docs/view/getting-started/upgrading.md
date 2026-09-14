# Upgrading

From **1.2.0** onward, NfoForge keeps your settings and data in a folder of your own rather than inside the application folder. Replacing a release no longer disturbs them.

If you are installing NfoForge for the first time, none of this applies and you can skip to [Initial Setup](initial-setup.md).

## Where your data lives now

| System  | Location                                   |
| ------- | ------------------------------------------ |
| Windows | `%LOCALAPPDATA%\nfoforge`                  |
| macOS   | `~/Library/Application Support/nfoforge`   |
| Linux   | `~/.local/share/nfoforge`                  |

Inside it:

| Folder                 | Holds                                            |
| ---------------------- | ------------------------------------------------ |
| `config/profiles/`     | Your configuration profiles                      |
| `config/program.toml`  | Program preferences, including the active profile |
| `config/plugins/`      | Plugin settings                                  |
| `cookies/`             | Tracker cookies                                  |
| `templates/`           | Your NFO templates                               |
| `plugins/`             | Your plugins                                     |
| `tools/`               | Bundled tools such as FrameForge                 |
| `logs/`                | Logs                                             |
| `workspace/`           | Saved jobs and run output                        |

## When the upgrade happens

On the **first launch of 1.2.0 or later**. Every earlier version kept this data inside the application folder, under `bundle/runtime`.

It runs **once per machine**. NfoForge records that your data folder is up to date and never asks again, however many times you upgrade afterward.

## How to upgrade

Do this in the order below, and in particular **do not rename or move your old folder before the upgrade has run**.

<!--prettier-ignore-start -->

1. Extract the new release to a **new, temporary folder** beside your existing one. Leave the old folder exactly where it is, under the name it already has.

2. Run NfoForge from the temporary folder. Choose **Choose a folder...** and pick your old NfoForge folder.

3. Read the summary, then use NfoForge for a while to satisfy yourself that everything came across.

4. Only now, delete the old folder and move the new one into its place -- or leave it where it is. Either is fine: nothing points inside the application folder any more.

<!--prettier-ignore-end -->

!!! warning "Why the order matters"
    Settings that name a tool record its **full path**, including the name of the folder it was in. NfoForge repoints those by comparing them against the folder you pick, so if you rename the old folder first, a recorded path no longer matches it and cannot be recognised as belonging to it.

    Such a setting is reported rather than silently left -- see **Settings naming something that is not there** below -- but you would then have to fix it by hand, and the whole point of the order above is that you do not have to.

## What you will be asked

NfoForge looks in the folder the application is running from for a previous installation, then shows one window:

- **Migrate** — bring everything across from the installation it found. The path is shown so you can check it is the right one. Disabled if nothing was found automatically.
- **Choose a folder...** — point at your previous NfoForge folder yourself. Pick the folder you extracted the old release into, the one holding the application. A folder with no NfoForge settings in it is refused rather than accepted silently.
- **Start fresh** — begin with default settings.

!!! tip "Extracted the new release somewhere new?"
    Then nothing will be found automatically, because NfoForge only looks where it is running from. Use **Choose a folder...** and pick your old folder.

## What is brought across

Your profiles, program preferences, plugin settings, tracker cookies, NFO templates, plugins and bundled tools. Two settings are also corrected as they arrive:

- A **working directory** that was NfoForge's own data folder becomes the `workspace` folder inside it, so your saved jobs are still found.
- A **dependency** stored in the old `apps` folder is repointed at its new home in `tools`.

Anything already inside your data folder from an earlier version — saved jobs, run output, the FrameForge index cache — is moved into `workspace` at the same time. That happens whether or not you import anything.

!!! info "Your old folder is never changed"
    Everything is copied, never moved, and nothing in the previous installation is deleted or modified. If the result is not what you wanted, the old folder is still exactly as it was.

## What you will be told afterward

A summary appears once, listing everything that happened. It can include:

- **Files of your own** that were sitting in the data folder and are not part of the layout. They are left where they are.
- **Run output you can delete**, with its size, in a working directory you chose. Nothing is removed for you.
- **Settings pointing into the previous installation** — usually a tool or a working directory you set yourself. These keep working until you delete that folder, and then stop. NfoForge names them rather than guessing where you would like them to go.
- **Settings naming something that is not there** — a tool recorded at a path that no longer exists, most often because the folder it was in has been renamed or moved. Set it again under **Settings -> Dependencies**. A tool you keep elsewhere on purpose is not reported, as long as it is still where the setting says.
- **The profile that was in use**, if it did not arrive. NfoForge starts on defaults under that name until you pick another profile or bring the missing one across.

The window is shown once and nothing on it is checked again, so a copy is saved in `logs/migration.log` inside your data folder. Read it whenever you like; it is not removed when old logs are tidied up, and importing again from Settings adds to it rather than replacing it.

## If something was already there

Nothing is ever overwritten or merged. If a folder or file already exists where an imported one would go, the **incoming** copy is put in `migration-conflicts` inside your data folder, keeping the same shape it would have had, and what was already there is left untouched.

This is normal when you import into a data folder you have already been using. Move anything you want out of `migration-conflicts` yourself, and delete the rest when you are happy.

!!! warning "Settings in set-aside profiles are not corrected"
    The two corrections described above are applied to the profiles in use. A profile that was set aside keeps its original paths, so check its tool locations before putting it into use.

## If you chose Start fresh

Nothing was read from your old installation and it is untouched. You can import it at any time from **Settings -> General**, using the import button beside the data folder. That runs the same import, with the same summary, and follows the same rules about not overwriting anything.

## Running from source

A source checkout uses a separate folder — `nfoforge-dev` instead of `nfoforge` in the same location — so running from source and running a release never share profiles, credentials or saved jobs.
