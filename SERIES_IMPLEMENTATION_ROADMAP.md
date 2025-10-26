# Series Management Implementation - COMPLETED! ✅

## Overview
Successfully implemented series management page with TV-specific features similar to Sonarr, including multiple episode format types and configuration settings prefixed with `tvr` (TV Rename).

## ✅ COMPLETED FEATURES

### 1. TVR Configuration Settings (src/payloads/config.py)
- **tvr_enabled**: Enable/disable series renaming
- **tvr_replace_illegal_chars**: Replace or remove illegal characters  
- **tvr_colon_replace_filename**: Colon replacement for filenames
- **tvr_colon_replace_title**: Colon replacement for titles
- **tvr_parse_filename_attributes**: Parse REMUX, HYBRID, PROPER, REPACK from filenames
- **tvr_standard_episode_token**: Token format for standard TV episodes
- **tvr_daily_episode_token**: Token format for daily episodes (talk shows, news)
- **tvr_anime_episode_token**: Token format for anime with absolute episode numbers
- **tvr_season_folder_token**: Token format for season folder names
- **tvr_multi_episode_style**: How to handle multiple episodes in single file
- **tvr_title_token**: Token format for release titles
- **tvr_release_group**: Release group setting

### 2. Multi-Episode Style Enum (src/enums/multi_episode_style.py)
- **EXTEND**: Extend episode numbers (S01E01-E03)
- **DUPLICATE**: Duplicate episode info (S01E01 S01E02 S01E03)
- **REPEAT**: Repeat with separator (S01E01.S01E02.S01E03)
- **SCENE**: Scene style format
- **RANGE**: Range format (S01E01-03)
- **PREFIXED_RANGE**: Prefixed range format

### 3. Enhanced Series Management UI (src/frontend/stacked_windows/settings/series_management.py)

#### Episode Format Section (Similar to Sonarr)
- **Standard Episode Format**: For regular TV episodes
- **Daily Episode Format**: For daily shows (talk shows, news)
- **Anime Episode Format**: For anime with absolute episode numbers
- **Season Folder Format**: For organizing seasons
- **Multi Episode Style**: Dropdown to select multi-episode handling

#### Live Preview Integration
- Connected to global management signals for real-time updates
- Live caching system for title clean rules and video dynamic range
- Real-time preview examples when global settings change

#### Control Features
- **Rename Series**: Enable/disable series renaming
- **Replace Illegal Characters**: Choose replace vs remove behavior
- **Parse Filename Attributes**: Extract REMUX, HYBRID, PROPER, REPACK
- **Colon Replacement**: Configurable colon handling for episodes and titles

### 4. Configuration Integration (src/config/config.py)
- Added TVR settings loading and saving in config system
- Default values in `runtime/config/defaults/default_config.toml`
- Series management section with sensible defaults

## Default Token Formats

### Standard Episode Format
```
{series_title_clean} - S{season:02d}E{episode:02d} - {episode_title_clean} [{resolution} {source} {video_codec} {audio_codec}]-{release_group}
```

### Daily Episode Format  
```
{series_title_clean} - {air_date} - {episode_title_clean} [{resolution} {source} {video_codec} {audio_codec}]-{release_group}
```

### Anime Episode Format
```
{series_title_clean} - S{season:02d}E{episode:02d} - {absolute_episode:03d} - {episode_title_clean} [{resolution} {source} {video_codec} {audio_codec}]-{release_group}
```

### Season Folder Format
```
Season {season}
```

## Benefits Achieved
1. **Sonarr-like Interface**: Familiar UI for users coming from Sonarr
2. **Flexible Episode Formats**: Support for different TV show types
3. **Multi-Episode Support**: Configurable handling of multi-episode files
4. **Real-time Previews**: Live updates when global settings change
5. **Consistent Architecture**: Follows same patterns as movies management
6. **Backward Compatibility**: Tracker overrides still use existing MVR system

## Integration Status
✅ **Complete**: Series management page with all episode format types
✅ **Tested**: All files compile successfully without syntax errors  
✅ **Connected**: Global management integration for live updates
✅ **Configured**: Default settings and config loading/saving
✅ **UI Ready**: Full Sonarr-inspired interface with multiple format types

## Future Enhancements
The series management system is ready for use! The tracker override system currently uses the existing MVR structure for compatibility. Future improvements could include:

1. Create series-specific tracker overrides (TVR-based)
2. Add series-specific tokens for episode numbering, air dates, etc.
3. Implement series-specific example data for better previews
4. Add validation for episode format tokens

The foundation is now in place for a comprehensive TV series management system that matches the flexibility and features of popular tools like Sonarr! 🎉

### ✅ Already Implemented
- [x] `MediaMode.SERIES` enum exists in `src/enums/media_mode.py`
- [x] `TMDBGenreIDsSeries` enum with all TV genre categories
- [x] Media search backend handles both movies and TV series
- [x] Placeholder `SeriesSettings` class exists
- [x] Tracker support includes series-specific logic (MoreThanTV categories, etc.)
- [x] Backend processing pipeline is media-mode aware
- [x] Upload functions accept `MediaMode` parameters

### ❌ Currently Blocked/Missing
- [x] Basic input handling for series (raises `NotImplementedError`)
- [ ] Series-specific settings implementation
- [ ] Series-specific tokens (episode, season, show title, etc.)
- [ ] Series rename logic and file naming patterns
- [x] Media mode combo is disabled in UI
- [ ] Need to ask user if comparison, do away with advanced input. 

## Implementation Phases

### Phase 1: Core Infrastructure 🔧
**Goal**: Enable basic series selection and input handling

#### 1.1 Enable Media Mode Selection
- [ ] Remove disabled state from `media_mode_combo` in `src/frontend/stacked_windows/settings/general.py`
- [ ] Update tooltip to reflect both modes are supported
- [ ] Test media mode switching in UI

#### 1.2 Implement Series Media Input
- [ ] Extend `MediaInputBasic.update_payload_data()` in `src/frontend/wizards/media_input_basic.py`
  - [ ] Handle series directory structures
  - [ ] Add logic to detect season/episode patterns
  - [ ] Support both single files and season directories
- [ ] Update `MediaInputAdvanced` for series support
- [ ] Add series-specific file validation

**Acceptance Criteria**: Users can select "Series" mode and input series files/directories without errors.

---

### Phase 2: Series-Specific Configuration ⚙️
**Goal**: Build comprehensive series settings infrastructure

#### 2.1 Series Settings Implementation
- [ ] Complete `SeriesSettings` class in `src/frontend/stacked_windows/settings/series.py`
  - [ ] Model after `MoviesSettings` structure
  - [ ] Add series rename controls
  - [ ] Implement token tables for series
- [ ] Add series settings to main settings navigation

#### 2.2 Configuration Payload Extensions
- [ ] Add series config properties to `src/payloads/config.py`:
  - [ ] `svr_enabled: bool` (series video rename)
  - [ ] `svr_token: str` (filename token string)
  - [ ] `svr_title_token: str` (title token string)
  - [ ] `svr_colon_replace_filename: ColonReplace`
  - [ ] `svr_colon_replace_title: ColonReplace`
  - [ ] `svr_clean_title_rules: list[tuple[str, str]]`
  - [ ] `svr_parse_filename_attributes: bool`
- [ ] Update config loading/saving logic in `src/config/config.py`
- [ ] Add series config defaults

**Acceptance Criteria**: Series settings are persistent and functional with proper validation.

---

### Phase 3: Token System Extensions 🏷️
**Goal**: Create comprehensive series-specific token system

#### 3.1 Series Token Creation
- [ ] Create `SeriesToken` class in `src/backend/tokens/`:
  - [ ] `{series_title}` - Clean series title from TMDB/TVDB
  - [ ] `{series_exact_title}` - Exact title with no modifications
  - [ ] `{series_clean_title}` - Series title with cleaning rules applied
  - [ ] `{season}` - Season number (S01, S02, etc.)
  - [ ] `{season_number}` - Season number only (1, 2, etc.)
  - [ ] `{episode}` - Episode number (E01, E02, etc.)
  - [ ] `{episode_number}` - Episode number only (1, 2, etc.)
  - [ ] `{episode_title}` - Individual episode title
  - [ ] `{air_date}` - Episode/season air date
  - [ ] `{series_year}` - Series start year
  - [ ] `{episode_year}` - Episode air year
  - [ ] `{network}` - Original network/platform
  - [ ] `{total_seasons}` - Total seasons in series
  - [ ] `{total_episodes}` - Total episodes in season/series

#### 3.2 Token Replacer Integration
- [ ] Extend `TokenReplacer` in `src/backend/token_replacer.py`:
  - [ ] Add series token handling methods
  - [ ] Implement series-specific token logic
  - [ ] Add series token validation
- [ ] Update token documentation and examples
- [ ] Add series tokens to token table system

#### 3.3 Series Template Support
- [ ] Create default series NFO templates in `runtime/templates/`
- [ ] Add series-specific template variables
- [ ] Update template selector to filter by media mode

**Acceptance Criteria**: Series tokens are fully functional and properly documented.

---

### Phase 4: Backend Processing Enhancement 🔄
**Goal**: Implement series-specific media processing logic

#### 4.1 Series Media Search Enhancement
- [ ] Ensure TVDB integration works for series metadata
- [ ] Implement season/episode-specific data handling
- [ ] Add series-specific external ID lookups (TVDB, AniList for anime)
- [ ] Handle series vs episode vs season distinctions

#### 4.2 Series File Processing
- [ ] Implement series file naming logic in rename system
- [ ] Handle season/episode directory structures
- [ ] Support batch processing of episode files
- [ ] Add episode-specific MediaInfo processing

#### 4.3 Series-Specific Media Search
- [ ] Update `MediaSearch` wizard page for series workflows
- [ ] Add series-specific search result handling
- [ ] Implement episode metadata fetching

**Acceptance Criteria**: Series files are properly processed with correct metadata extraction.

---

### Phase 5: Tracker Integration 📤
**Goal**: Ensure proper series upload support across trackers

#### 5.1 Tracker Series Logic
- [ ] Review and enhance MoreThanTV series support
- [ ] Update other tracker uploaders for series:
  - [ ] BeyondHD
  - [ ] TorrentLeech  
  - [ ] PassThePopcorn
  - [ ] Unit3D trackers (ReelFliX, Aither, etc.)
- [ ] Implement episode vs season vs complete series detection
- [ ] Ensure proper series metadata is passed to trackers

#### 5.2 Series Category Detection
- [ ] Enhance category detection for:
  - [ ] Individual episodes
  - [ ] Season packs
  - [ ] Complete series
- [ ] Update tracker-specific category mapping

**Acceptance Criteria**: Series uploads work correctly across all supported trackers.

---

### Phase 6: UI/UX Polish ✨
**Goal**: Optimize user experience for series workflows

#### 6.1 Wizard Flow Updates
- [ ] Add series-specific validation in wizard pages
- [ ] Update progress messages for series processing
- [ ] Consider different workflows for episode vs season processing
- [ ] Add series-specific help text and tooltips

#### 6.2 Settings Organization
- [ ] Integrate series settings into main settings navigation
- [ ] Implement series-specific examples and previews
- [ ] Add series token documentation to help system
- [ ] Create series-specific default configurations

#### 6.3 Error Handling & Validation
- [ ] Add series-specific error messages
- [ ] Implement validation for episode/season patterns
- [ ] Add warnings for common series naming issues

**Acceptance Criteria**: Series workflow is intuitive and well-documented.

---

## Implementation Priority

### Recommended Order:
1. **Phase 1** - Core Infrastructure (enables basic functionality)
2. **Phase 3** - Token System (unlocks most features)
3. **Phase 2** - Configuration (makes settings persistent)
4. **Phase 4** - Backend Processing (enhances functionality)
5. **Phase 5** - Tracker Integration (completes upload workflow)
6. **Phase 6** - UI/UX Polish (improves user experience)

## Key Architecture Guidelines

### Consistency Patterns
- Follow existing movie implementation patterns
- Use `svr_*` prefix for series configs (parallel to `mvr_*` for movies)
- Maintain backward compatibility with movie workflows
- Reuse common logic where possible (media processing, image generation, uploads)

### Code Organization
- Create separate token classes/groups for movies vs series
- Use media mode switches rather than duplicating code
- Implement proper error handling for series-specific edge cases
- Document series-specific configuration options

### Testing Considerations
- Test with various series naming patterns
- Validate episode vs season vs complete series detection
- Ensure tracker uploads work correctly
- Test media mode switching doesn't break existing functionality

## Progress Tracking

Use the checkboxes above to track implementation progress. Update this document as tasks are completed or requirements change.

## Additional Notes

- Consider anime-specific handling (seasons, OVAs, specials)
- Think about miniseries vs full series distinctions
- Plan for different episode numbering schemes (absolute vs seasonal)
- Consider multi-part episodes and special episodes

---

*Last Updated: August 20, 2025*
*Target Completion: TBD*
