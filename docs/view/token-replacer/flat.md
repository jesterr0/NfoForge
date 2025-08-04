# Flat Strings

<!-- prettier-ignore -->
!!! tip "Flat Strings"
    Flat strings are defined by a **single line** of text.  
    *e.g. `Big.Buck.Bunny.2008.BluRay.1080p.MP2.2.0.x264`.*

NfoForge will automatically use the formatter in **flat** mode for paths (files and folders).

### Format

[FileTokens](introduction.md) are only available in **flat** mode when used directly in NfoForge. You'll notice that flat tokens have a single set of brackets, e.g., `{movie_title}`.

### Usage

A token string is simply a combination of tokens and text.

<!-- prettier-ignore -->
!!! question "What is a string?"
    A string is a sequence of characters. This includes letters, numbers, and symbols.

**Example of a token string:**

```text
{movie_clean_title} {release_year} {edition} {re_release} {source} {resolution} {mi_audio_codec} {mi_audio_channel_s} {mi_video_dynamic_range_type_inc_sdr_over_1080} {mi_video_codec}
```

**When filled:**

```text
Movie Name 2025 Directors Cut REPACK UHD BluRay 2160p TrueHD Atmos 7.1 DV HDR HEVC
```

The output will vary based on the file that is opened. If you are familiar with Radarr/Sonarr, this works very similarly.

### Optional Text

You can use tokens with an optional syntax to only add text **if** the token is filled by the formatter. This is done with the syntax `:opt=*:`, where you replace the asterisk with whatever text you want.

**Example of a token string with opt syntax:**

```text
{movie_clean_title} {:opt=(:release_year:opt=):} {edition} {re_release} {source} {resolution} {mi_audio_codec} {mi_audio_channel_s} {mi_video_dynamic_range_type_inc_sdr_over_1080} {mi_video_codec}
```

Note the token `{:opt=(:release_year:opt=):}`. We're using `:opt=(:` and `:opt=):` to wrap the year with parentheses. This allows for many use cases and enables a high degree of customization.

**When filled with opt syntax:**

```text
Movie Name (2025) Directors Cut REPACK UHD BluRay 2160p TrueHD Atmos 7.1 DV HDR HEVC
```

You can see this in action in real time inside **NfoForge** under **Settings → Movie**.

![Token Example](../../images/tokens/token-example.png){ width=100%, style="max-width: 500px;" }

### Additional Information

There are three built-in rename token strings:

<!--prettier-ignore-start -->

- **Filename** token string
    - The filename (or folder, if applicable) is shared across all trackers.
    - There can only be one of these tokens.
- **Title** token string (global)
    - A single global token shared across all trackers that don't have an override.
- Per-tracker **Title** token string override
    - Overrides the global title token for each tracker.

<!--prettier-ignore-end -->
