# CoverUp (MusicBrainz Picard plugin)

Find, compare and apply album artwork from many sources, as embedded tags, as files in a folder you name, or both.

**Version 0.4.0. Needs Picard 3.0 or newer.**

## What it does

Right-click an album, a cluster, a track or a file in Picard. Loose files under **Unclustered Files** work too: CoverUp groups them by their own album and album-artist tags and searches with those.

| Menu item | What happens |
|---|---|
| **CoverUp: Find artwork…** | Searches every enabled source and opens the review window: one tab per art type (Front, Back, each disc, Booklet, Artist, Create), a large preview with a comparison to your current cover, and **Your set**, the strip of everything you are about to apply. **Double-click a picture to apply just that one straight away**; the window stays open for the rest. |
| **CoverUp: Auto-apply** | For all selected albums: applies confident results, marks conflicts and misses for review (double-click a row to review it). |
| **CoverUp: Undo last apply** | Removes the files the last apply wrote and restores any files it replaced (from `.coverup-backup`). |

### Sources
Cover Art Archive (exact release and release group), Discogs (exact release via the MusicBrainz link, barcode, catalogue number or search; also the artist's page), Wikimedia Commons (artist photos and logos through the artist's MusicBrainz links, no key), Fanart.tv (covers, numbered disc art, artist images and logos), TheAudioDB, iTunes, Deezer (albums and artist photos), Last.fm, optional paid web image search (Brave API key), and images already in the album folder.

### Artist images
Options > CoverUp > **Artists** holds everything about them: whether to look for them, which kinds are pre-selected (photo, logo, background, banner), the smallest photo to accept, and whether to save them in the artist folder (the folder above the album, for example `Music/Artist/artist.jpg`). By default the photo is collected and saved; logos, backgrounds and banners are listed in the review window to pick by hand, or tick them in the settings.

| Kind | Sources, best first |
|---|---|
| Photo | Wikimedia Commons (exact: linked from the artist's MusicBrainz page; shows its licence), Discogs (artist page), Fanart.tv, TheAudioDB, Deezer (matched by name only) |
| Logo, background, banner | Fanart.tv (free key), TheAudioDB; Wikimedia Commons logos when the artist has one |

Compilations (Various Artists) never get artist images.

### Use CoverUp from Picard's own cover art lookup
CoverUp is also listed in Picard's **Options > Cover Art** next to *Cover Art Archive* and *Discogs*. Tick it, and when Picard loads an album it asks CoverUp: CoverUp searches all its sources, and hands the front (and back, if you embed it) to Picard, which embeds it under its usual rules. The covers folder, artist images, disc art and booklets are written by CoverUp when you save, exactly as with Auto-apply. Picard stops asking providers once it has the front cover it needs, so drag CoverUp **above** the others in that list to let it decide. CoverUp's own settings (sources, sizes, embed choice, folder) apply.

### Search the web yourself (free)
**Search the web** in the review window opens an image search in your browser (Google Images limited to large images, Bing, DuckDuckGo, Discogs, the release's MusicBrainz cover art page, or a **Shops and streaming** submenu with Amazon, Spotify, Tidal, Apple Music, YouTube Music, Bandcamp and Qobuz), built from the album artist, album title, year, edition words such as *remastered* or *deluxe* from the title and release comment, and, for "this pressing", the label, catalogue number and format. Open a picture full size, then copy it (right-click > Copy image) and press **Ctrl+V** in CoverUp, or drag it onto the window: it lands in the tab you are on. Pasted Google/Bing result links are turned into the real image address. CoverUp never reads search-engine pages itself.

### How the pick is made
1. **Exact release** art (tier A: Cover Art Archive release images, or the matching Discogs release) wins.
2. Otherwise **release-group** art (tier B: CAA release group, Fanart.tv, TheAudioDB).
3. Otherwise the image that the **most independent sources agree on** visually (perceptual hashing).
4. If exact-release art and a large group of other sources disagree, nothing is applied automatically; the album is flagged for review.

Each image carries a plain label: **Exact release**, **Same album** (possibly another edition), **Search match**, or **Generated**. CoverUp's choice is marked **CoverUp pick**. Select an image to see why in the preview panel.

### Art types
Front, back, disc (matched to the right disc using `discnumber` tags), booklet pages, and artist images (photo, logo, background, banner). Choose any combination per run; set the default in Options.

### Defaults (chosen for collectors)
- Collects the front, back, disc art, booklet pages and the artist photo (other artist images are one tick away).
- Embeds **only the front cover** in the tags (up to 1200 px) and saves every image as a full-size file in `covers/`, plus `cover.jpg` beside the tracks for players and media servers.
- Prefers the **largest** scan available; never applies anything smaller than 600 px; never enlarges images.
- Replaces an existing file only when the new image is larger, and keeps a backup so Undo can restore it.
- Records where each image came from in `coverup.json`, not in your tags.
- Creating covers is off until you turn it on.

If you used an earlier version, settings you never changed move to these defaults; anything you changed yourself is kept. *Restore Defaults* in the Options window shows them again.

### Output
- **Embed in tags**: front only (default), front and back, everything chosen, or nothing. Disc art is embedded only into that disc's files.
- **Save as files** in a sub-folder you name: `covers` (default), `art`, `artwork`, `booklet` or your own, or in the album folder itself. By default the front cover is also saved as `cover.jpg` in the album folder, where players look for it.
- File names: default, Kodi/Jellyfin, Plex presets, or your own templates (`disc{discnumber}`, `booklet-{n}`).
- Artist images go to the artist folder (the folder above the album; `Album/CD1` layouts are recognised).
- Files are written **after Picard saves the album** (so they follow renames and moves), or immediately if you prefer.
- If a file exists: replace only if the new one is larger (default), replace, keep, or keep both. Replaced files are backed up and can be undone.
- `coverup.json` next to the files records where each image came from.

### Resolution limits
Separate minimums per art type for **searching** (smaller results are hidden but can be shown), an optional maximum, a preferred size, and separate **apply** limits: maximum size for embedded images and for files, and a minimum below which nothing is applied (and the creative fallback can kick in). Images are never upscaled unless you turn that on.

### Creative / AI art (off by default)
- **When:** no cover found, best cover below the apply minimum, only conflicting covers found, or **always** (even when a real cover exists).
- **How, in your order:** fan art from Fanart.tv → AI → offline template.
- **Styles:** Art, Fantasy, Nature, Planetary/Space, Cyberpunk, Minimal, Vintage, Photographic, Geometric/Bauhaus, Gothic, Retro pop, or your own prompt. Templates are editable `.toml` files; put your own in the templates folder (Options > CoverUp > Creative / AI > Open my templates folder).
- **Era and genre matching** from the release year and genre tag.
- **Logo and title are drawn by CoverUp, not the AI**, so they are sharp and correctly spelled. The band logo comes from Fanart.tv/TheAudioDB (pick a logo variant once per artist; it is remembered), else the artist name is set as text.
- **AI backends you configure yourself:** a local Stable Diffusion web UI (AUTOMATIC1111 started with `--api`), any OpenAI-compatible images API, or a custom HTTP endpoint. Nothing is bundled or hosted by CoverUp.
- Generated art is always **labelled** (image comment "Generated by CoverUp…", `coverup.json`, `%_coverup_generated%`), never uploaded anywhere, and never outranks real art except in the cases you switched on. Remote AI services ask for your consent first; the current cover is only sent as a reference to a remote service if you allow that separately.

### Script variables
`%_coverup_status%` (applied / review / none), `%_coverup_source%`, `%_coverup_confidence%` (A/B/C/G), `%_coverup_generated%`.

### Logging
A log file for troubleshooting: rotating 2 MB × 3 by default, or size-capped, age-based or one-per-session. API keys are always masked. Options > CoverUp > Logging has *Open log folder* and *Export diagnostics bundle…* (a redacted zip to attach to a bug report). Flatpak Picard keeps it in `~/.var/app/org.musicbrainz.Picard/cache/MusicBrainz/Picard/coverup/logs/`.

## Setup
1. Install: Options > Plugins > Install Plugin… (or `picard-cli plugins install <this folder or repo URL>`; Flatpak: `flatpak run --command=picard-cli org.musicbrainz.Picard plugins install …`).
2. Options > Plugins > **CoverUp** > Sources: add the keys you have.
   - Discogs: personal access token (discogs.com > Settings > Developers).
   - Fanart.tv: free project API key (fanart.tv/get-an-api-key).
   - Last.fm and web image search are optional.
   - Cover Art Archive, Wikimedia Commons, TheAudioDB (public test key), iTunes and Deezer work without keys.
3. Picard's own Options > Cover Art > *Embed cover images into tags* must be on for embedding. If *Embed only a single front image* is on, only the front is embedded.

## Updating from this repository
```
cd ~/Documents/Github/picard-coverup && git pull
```
Then Options > Plugins > select CoverUp > Update (or `picard-cli plugins update CoverUp`), and restart Picard.

## Known limits
- As a Picard cover art provider, CoverUp hands over only the front and back covers (Picard embeds an image into every track, which is wrong for disc art and booklets); it writes the other images as files. It runs a full search for each album Picard loads, so it is slower than the built-in providers; leave it unticked if you prefer to run CoverUp by hand.
- Generated art is made for the front cover only; back, disc and booklet images are always real scans.
- Discogs does not label secondary images; they are offered in the Back/Discs/Booklet tabs for you to pick but never auto-selected.
- HTTP requests use Python's standard library (proxy settings from the `HTTPS_PROXY` environment variable), not Picard's network settings.
- Embedded images can be changed until you save; to drop unsaved changes, remove and reload the album. Undo covers files CoverUp wrote.
- Provider responses were tested against fixtures written from each API's documentation; please report any source that returns nothing with the diagnostics bundle.

## Development
```
python -m venv .venv && .venv/bin/pip install pytest PyQt6
.venv/bin/python -m pytest -q                       # core + Qt tests
PICARD_SRC=/path/to/picard-3.x-source .venv/bin/python -m pytest -q   # also the Picard integration and UI tests
```
`docs/design-prompt.md` is the full design; `docs/phase0-api-contract.md` lists the Picard 3 APIs used, verified against the Picard 3.0 source.

## Licence
GPL-2.0-or-later, same as Picard.
