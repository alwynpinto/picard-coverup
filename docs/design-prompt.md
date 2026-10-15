# CoverUp: MusicBrainz Picard Plugin. Design and Build Prompt

> Paste this whole document into your coding agent as the task brief. Sections 1-3 say what to build. Sections 4-7 are the design to follow. Sections 8-10 cover extras, delivery and acceptance.

---

## 1. Role and objective

You are a senior Python engineer who knows MusicBrainz Picard internals, PyQt6, async HTTP, image processing and audio-tag formats. Design and implement **CoverUp**, a Picard plugin that finds, ranks, previews and applies album artwork. It searches multiple sources, picks the best match with a transparent scoring and consensus model, and saves the result as embedded tags, as files in a user-defined folder, or both.

**Design goals, in priority order:**
1. **Correctness.** Prefer the exact release's artwork. Never silently apply wrong art.
2. **Safety.** Never lose or overwrite the user's existing art or files without a backup or confirmation.
3. **Control.** The user chooses which art types to apply (front, back, disc, artist and so on) and where it goes.
4. **Transparency.** Every candidate shows its source, size, score and the reason for that score.
5. **Good citizenship.** Respect API terms and rate limits, cache aggressively, and never scrape sites that forbid it.

## 2. Platform and constraints

- Target **Picard 3.x and its Plugin V3 API** (plugins are distributed through the Picard Plugins Registry and managed with `picard-cli plugins`). **First read the current Plugin V3 documentation and the Picard source** to confirm the manifest format, entry point (`enable(api)`), the `PluginApi` surface, and the available registration functions. Expect these to exist but verify names and signatures:
  - cover art provider registration (`register_cover_art_provider`)
  - context-menu actions for albums, clusters, tracks and files
  - an options page
  - file post-save / post-load hooks
  - script variable registration (`register_script_variable`)
  - the web service wrapper, which should be preferred over raw HTTP so that Picard's proxy and rate-limit settings apply
- Do **not** assume Picard 2.x APIs. Do not use the legacy `PLUGIN_NAME` style.
- Python and Qt: use whatever Picard 3 ships (PyQt6). Third-party dependencies must be **pure Python and already bundled with Picard, or vendored**. Plugins cannot rely on `pip install` in frozen builds. Therefore:
  - No OpenCV, no numpy requirement, no ImageMagick requirement.
  - Use `QImage` / `QImageReader` for decoding and scaling.
  - Implement perceptual hashing (dHash, plus pHash if practical) in pure Python over a downscaled `QImage`. Optionally use Pillow when it is importable, and degrade gracefully when it is not.
- Never block the UI thread. All network and image work goes through Picard's async web service or worker threads. Results come back to the UI via signals.
- Cross-platform: Windows, macOS and Linux. Handle path length limits, illegal filename characters and case-insensitive filesystems.
- Licence: GPL-2.0-or-later, compatible with Picard and registry rules.

## 3. Functional requirements (from the product owner)

### 3.1 Sources
Provide a pluggable provider system with these initial providers:

| Provider | Covers | Auth | Notes |
|---|---|---|---|
| **MusicBrainz / Cover Art Archive** | Release and release-group art with typed images (front, back, medium, booklet, etc.) | none | Highest trust for exact-release matches. Also follow MusicBrainz URL relationships ("cover art" links and allowed-URL whitelist). |
| **Discogs** | Release images (primary and secondary) | user token (OAuth or personal token) | Resolve the exact Discogs release ID from the MB release's URL relationship; otherwise search by barcode, catalogue number, then artist + title + year + format + country. Honour Discogs rate limits and image-licensing terms. |
| **Fanart.tv** | Album covers, **disc art (with disc number)**, artist thumbs, backgrounds, logos, banners | project API key (+ optional personal key) | Keyed by MusicBrainz release-group ID or artist ID. Requires attribution. Release-group level, not release level. |
| **TheAudioDB** | Album thumbs, CD art, artist images | API key | Release-group level. |
| **iTunes / Apple Music Search API** | Front cover (can request very high resolution via URL rewriting) | none | Good fallback, front only. |
| **Deezer API** | Front cover (XL) | none | Front only. |
| **Last.fm** | Front cover | API key | Fallback. |
| **Spotify** (optional) | Front cover | client credentials | Optional, behind a toggle. |
| **Wikimedia Commons / Wikipedia** (optional) | Public-domain / freely licensed covers | none | Useful for classical and old releases. |
| **Web image search** | Front, back, anything | **user-supplied API key only** | See the legal note below. |
| **Local sources** | Existing `cover.*`/`folder.*` files, existing embedded art, files dropped in by the user | none | Used as a candidate and as the *comparison reference* for "is the new art better?". |

**Legal and technical note on "Google Images":** do **not** scrape Google results because it violates their terms and breaks constantly. Implement web image search as a provider abstraction (`WebImageSearchProvider`) that works only with a user-supplied API key. Examples are Google Programmable Search / Custom Search JSON API (**verify its current availability, since Google has been restricting it for new users**), Brave Search Image API, and SerpApi. Ship it **disabled by default**, label it clearly as using the user's own key, and document how to get one. Make adding a new provider a single-file task.

**Amazon:** Picard already has an Amazon provider plugin. CoverUp should not re-implement it, but may optionally call it as a candidate source.

### 3.2 Matching and selection logic
CoverUp must decide what "the right cover" is, and explain why.

Use a **tiered, evidence-based approach** (details in §5):

1. **Tier A, exact release anchor.** The cover belongs to the exact MB release (CAA release images) or the exact linked Discogs release (via URL relationship, barcode or catalogue number).
2. **Tier B, release-group anchor.** CAA release-group image, Fanart.tv or TheAudioDB (release-group keyed).
3. **Tier C, visual consensus.** For everything else, **cluster candidates by perceptual similarity and prefer the cluster with the most independent sources agreeing**. If no exact-release art exists, the cover "that looks similar across the highest number of results" wins.

Rule: when Tier A/B candidates and a large Tier C consensus cluster **disagree**, do not auto-apply. Flag the conflict and ask the user (or in unattended mode, apply the Tier A candidate and mark the item "needs review").

### 3.3 Artwork types
The plugin must fetch and let the user select among:
- **Front**
- **Back**
- **Disc / Medium** (CD, vinyl label, etc.), **matched to the correct disc number** using file tags (`discnumber`, `totaldiscs`, MusicBrainz medium position)
- **Booklet / inlay / tray / spine / other** pages
- **Artist** images (thumb, background, logo, banner)

The user chooses **any combination**: only front, front + back, front + back + discs, everything, etc. This is a persistent default *and* a per-run override in the review dialog.

### 3.4 Output / apply modes
Independent toggles. The user may enable either or both:
1. **Embed as tags.** Write images into the audio files via Picard's metadata image system so they are saved with the files. Respect per-format limits (see §6.4).
2. **Save to folder as files.** Save to disk beside the album.

**Folder options (for saved files):**
- **Same folder as the tracks.** Files are written next to the audio, so each type needs its own filename (e.g. `cover.jpg`, `back.jpg`, `disc1.jpg`).
- **Sub-folder with a user-defined name**, default **`covers`**. Presets in a dropdown: `covers` (default), `art`, `artwork`, `booklet`, plus **Custom…**. Validate the name (no path separators or illegal characters).
- Optional **per-type routing**, e.g. front → album folder as `cover.jpg`, everything else → `artwork/`. This is the most useful real-world layout, so offer it as a preset.
- File naming through **user-editable templates** with Picard script variables, with defaults:
  - front: `cover` (+ ext)
  - back: `back`
  - disc: `disc{discnumber}` (e.g. `disc1`)
  - booklet: `booklet-{n}`
  - artist: `artist` (saved in the **artist folder**, the parent of the album folder, when it can be determined, otherwise skipped with a notice)
- Format options: keep the original format (no needless re-encoding), or convert to JPEG/PNG, plus a JPEG quality setting. Optional max dimension for files and a separate, lower max dimension for embedded images.
- **Collision policy:** skip / overwrite / overwrite only if better / keep both (suffix). The default must be **overwrite only if better, with a backup**.

### 3.5 Resolution limits (search and apply)

Resolution is controlled at **two separate points**, because "what we are willing to consider" and "what we write" are different decisions. Settings are **per art type** (front, back, disc, booklet, artist) with global defaults, and shown in Options → Resolution.

**A. Search / acceptance limits (which candidates are eligible)**
- **Minimum width and height** (default front: 500 px; back/disc/booklet: 300 px). Candidates below the minimum are hidden by default but kept in a collapsed "Below minimum" group so the user can still choose one deliberately.
- **Maximum width and height** (default: none, with an optional ceiling such as 6000 px) to skip absurd scans.
- Also: **min/max file size**, **aspect-ratio tolerance** (front default 0.95-1.05, wider allowed for booklet/back/spine scans), and **"prefer closest to target size"** (e.g. target 1200 px) versus **"prefer largest"**.
- Providers that support size parameters (CAA 250/500/1200 thumbnails, iTunes URL rewriting, Discogs primary vs. secondary) must be asked for the right size up front instead of downloading everything and filtering afterwards. Record the *actual* decoded dimensions after download and re-check, since providers misreport sizes.
- A candidate that fails the limits keeps its reason (e.g. "Too small: 300x300 < 500x500") in the score breakdown and the log.

**B. Apply limits (what gets written)**
- Separate **max dimensions for embedded images** (default 1000-1500 px) and **for saved files** (default: original size, no limit), per art type.
- **Never upscale by default.** Offer an explicit "upscale to minimum" option, flagged as low-quality in the UI and tags. Downscale with high-quality resampling and keep the aspect ratio. Option to **pad/crop to square** for front covers only when the user asks.
- Optional **min resolution to apply** (a stricter bar than the search minimum): below it, the plugin does not apply and routes the album to the "low resolution" fallback (§3.6) or the review queue.
- Reuse the same limits in "overwrite only if better", so a larger existing file is never replaced by a smaller one.

### 3.6 Creative fallback and AI-generated art

CoverUp can produce replacement or alternative artwork when real art is missing, too small, or simply not wanted. This is **off by default** and opt-in, and generated art is always clearly marked as generated (see the guardrails below).

**Three independent controls**

1. **Fallback trigger (when does creative art kick in?).** A setting with these options:
   - *Never* (default).
   - *No cover found.*
   - *Best cover is below the minimum resolution* (uses the §3.5 apply minimum).
   - *Low match confidence* (only conflicting or Tier C art found).
   - Any combination of the above.
2. **Creative method (what is produced when triggered).** User-selected order, e.g. "try A, then B, then C":
   - **A. Fan art from a source** (fanart.tv and similar), chosen by the usual scoring. This is real, human-made art and the preferred first fallback.
   - **B. AI recreation / re-imagining** of the album cover: a new image *inspired by* the release, built from the artist, album title, year, genre/style tags and, optionally, the low-resolution cover used as a reference (image-to-image). Output is clearly a reinterpretation, not a copy.
   - **C. Template composition without AI** (procedural gradient, texture or typographic layouts), as an offline fallback with no external calls.
3. **"Always use generated art" mode (regardless of whether a real cover exists).** A separate switch: the user can choose to use generated art **even when a good real cover was found**, using one of the fixed templates below. It is configurable globally, per profile, per album, and per art type (e.g. generate only the **front**, keep real back/disc art).

**Fixed style templates (user chooses; all editable)**
Ship a library of named templates, each a prompt recipe plus composition rules and negative prompts, stored as editable files (`templates/*.toml` or similar) so users can add their own:
- *Art* (painterly / abstract), *Fantasy*, *Nature*, *Planetary / Space*, *Cyberpunk / Neon*, *Minimal typographic*, *Vintage / Vinyl-era*, *Photographic / Cinematic*, *Geometric / Bauhaus*, *Dark / Gothic*, *Retro pop*, plus **Custom** (user-written prompt with placeholders such as `{artist}`, `{album}`, `{year}`, `{genre}`, `{mood}`, `{palette}`).
- Each template defines: prompt text, negative prompt, aspect ratio (1:1 for front, circular crop for disc art), preferred resolution, optional palette hints, and whether title/logo overlay is on.
- A **"match the era"** option that adds era cues from the release year (e.g. 1970s gatefold, 1980s airbrush, 1990s digital), and a **"match the genre"** option driven by the genre tags.
- Previews: the template picker shows a small sample so the user knows what to expect.

**Logo and title handling (important design decision)**
- **Do not ask the AI model to draw text or the band logo.** Image models spell and render logos poorly. Instead, generate the **background art only**, then **composite the artist logo and album title in the plugin** with Qt (`QPainter`/`QImage`), so text is always sharp and correctly spelled.
- **Band logo source:** prefer a real logo from fanart.tv (HD music logo / clear logo) or TheAudioDB, with **era matching**: when several logo variants exist, prefer the one nearest the release year if the source provides dates, otherwise let the user pick one in the review dialog and **remember it per artist**. If no logo is available, fall back to **styled typographic text** of the artist name (font choice, colour and placement from the template).
- Composition options: logo position (top, centre, bottom), scale, safe margins, contrast/shadow so it stays readable, album title and optional year line, and a **"no overlay"** choice.
- Overlay must keep the logo's aspect ratio, never crop it, and handle transparent PNG logos.

**AI generation provider abstraction**
- A `GenerationProvider` interface (`providers/ai/`) with: `generate(prompt, negative, size, seed, reference_image=None) -> image`, capability flags (img2img, seed support, max size, cost estimate), and the same async/rate-limit/cache/log infrastructure as other providers.
- Initial backends, all **user-configured with their own endpoint and key** (nothing bundled, nothing hosted by us): (1) **local** Stable-Diffusion-compatible servers (e.g. AUTOMATIC1111 / ComfyUI style HTTP APIs), the privacy-friendly default; (2) any **OpenAI-compatible image-generation endpoint**; (3) a generic "custom HTTP endpoint" adapter. Verify each backend's current API during Phase 0.
- **Variations:** generate N candidates (default 4), show them in a grid in the review dialog, user picks one. Store the **seed, model, prompt, template and settings** with the chosen image so it can be regenerated or tweaked ("more like this", "different seed", "edit prompt").
- Cost/limits controls: max generations per run, max per album, a confirmation before large batches, and a visible estimated cost when the backend reports it.
- **Image-to-image from the existing low-resolution cover** is an *option*: "Recreate (reinterpret, free to change)" versus "Restore/upscale (stay faithful)". Faithful upscaling, if offered, goes through a user-supplied upscaler command/endpoint and is labelled as an upscale.

**Guardrails (these are requirements, not suggestions)**
1. **Always labelled.** Every generated image gets provenance: `coverart_comment` (e.g. "Generated by CoverUp, AI, template: fantasy"), a sidecar `coverup.json` (seed, model, template, prompt, timestamp, source art used), and the script variable `%_coverup_generated%`. In the UI it carries a visible **"AI-generated"** badge. It is **never** described as the official release art.
2. **Never submitted anywhere.** No auto-upload to the Cover Art Archive, Discogs or any service, and the "submit-back helper" in §8 must exclude generated art.
3. **Real art always outranks generated art** in normal scoring (a separate tier "G", the lowest). Generated art wins only when the user chose *Always use generated art*, or when the fallback trigger fired.
4. **Upgrade path.** Audit mode and the batch queue can flag albums that have generated art when real art later becomes available, with a one-click "replace with real art".
5. **Privacy consent.** Using a remote generation service sends the artist, album title, year, genre text (and a reference image if enabled) to a third party. Show a one-time explicit consent dialog per backend, with a "local only" option, and never send reference images to a remote service unless the user enabled it.
6. **Rights notice.** In the options page and docs, state that generated art is for **personal library use**, that recreating an existing cover from a reference is the user's responsibility, and that the plugin does not distribute artwork. The band logo is used only for display in the user's own library.
7. **No silent replacement.** Generated art never overwrites an existing real cover without confirmation and a backup (same safety rules as §6.3).
8. **Offline fallback.** If the AI backend is unreachable, fall back to template composition without AI (method C), or leave the album untouched. Never block the batch.

## 4. Architecture

Prefer small, testable modules. Suggested layout:

```
coverup/
  MANIFEST.toml            # Plugin V3 manifest (verify exact schema)
  __init__.py              # enable(api): registers actions, options page, hooks
  model.py                 # dataclasses: Query, Candidate, ArtType, Cluster, Decision
  providers/
    base.py                # CoverProvider ABC + capability flags + rate-limit/backoff mixin
    caa.py  discogs.py  fanart.py  audiodb.py  itunes.py  deezer.py
    lastfm.py  spotify.py  commons.py  websearch.py  local.py
  matching/
    identity.py            # resolves MBIDs, Discogs ID, barcode, catno from the release
    phash.py               # pure-Python dHash/pHash + Hamming distance
    cluster.py             # similarity clustering
    scoring.py             # candidate scoring + explanation strings
    disc.py                # disc-number matching heuristics
  pipeline.py              # orchestration: discover -> fetch thumbs -> score -> select -> apply
  apply/
    embed.py               # write to Picard metadata images
    files.py               # folder resolution, naming, safe write, backup, undo journal
    imageops.py            # resize / convert / trim / validate via QImage
  creative/
    trigger.py             # evaluates fallback triggers (none found / below min res / low confidence / always)
    templates/             # editable style templates (art, fantasy, nature, planetary, ... + custom)
    template_engine.py     # fills prompt placeholders (artist, album, year, genre, era, palette)
    compositor.py          # QPainter overlay of band logo + title/artist text; disc circular crop
    logos.py               # logo lookup (fanart.tv / AudioDB), era matching, per-artist memory
    procedural.py          # offline non-AI backgrounds (gradients, textures, typographic layouts)
    provenance.py          # comment/sidecar/script-variable labelling of generated art
  providers/ai/
    base.py                # GenerationProvider ABC (generate, capabilities, cost estimate)
    local_sd.py  openai_compat.py  custom_http.py
  cache.py                 # on-disk HTTP + image cache (ETag aware), decisions DB
  ui/
    options_page.py        # settings
    review_dialog.py       # thumbnail grid review/selection UI
    widgets.py             # candidate card, compare slider, disc assignment
  diagnostics/
    logging_setup.py       # file handler, rotation modes, redaction filter, run/album correlation IDs
    bundle.py              # "Export diagnostics bundle" (redacted zip)
  ratelimit.py  util.py
tests/                     # pytest, with recorded provider fixtures (no live network in CI)
```

**Core data model**
- `Query`: artist, album, year, barcode, catalogue number, label, country, format, medium count, per-disc info, `release_mbid`, `rg_mbid`, `artist_mbid`, `discogs_release_id`.
- `Candidate`: `provider`, `provider_id`, `url`, `thumb_url`, `art_type` (front/back/disc/booklet/artist-*/other), `disc_number` (optional), `width`, `height`, `bytes`, `format`, `anchor_tier` (A/B/C), `phash`, `score`, `score_breakdown`, `license/attribution`, `source_confidence`.
- `Decision`: chosen candidates per art type, who chose (auto/user), timestamp, rationale. It is persisted keyed by release MBID so the user is not asked twice.

**Pipeline (each stage is async and cancellable)**
1. **Identify**: build the `Query` from Picard's album/track metadata. If the MB release has a Discogs URL relationship, use that Discogs ID. Otherwise search Discogs by barcode, then catno, then fuzzy artist/title.
2. **Discover**: run enabled providers concurrently with per-provider concurrency and rate limits. Collect candidate metadata and thumbnails only.
3. **Fingerprint**: download small thumbnails (or the provider's thumb URL) and compute perceptual hashes. Fetch full-size images **lazily**, only for finalists or when applying.
4. **Score and cluster**: see §5. Apply the §3.5 search limits here and record the reason for every rejection.
4b. **Creative fallback (§3.6)**: if the fallback trigger fires (no art, best art below the apply minimum, low confidence) or "Always use generated art" is on, run the creative methods in the user's order: fan art, then AI recreation, then non-AI template. Generated candidates enter the pipeline as tier **G** with provenance attached.
5. **Select**: auto-pick or hand over to the review dialog depending on mode and confidence.
6. **Apply**: embed and/or write files transactionally, with a journal for undo.
7. **Report**: per-album summary, with status exposed as script variables / columns.

## 5. Matching and scoring design

### 5.1 Identity anchoring
- **Tier A** candidates come from: CAA release images, the Discogs release whose ID or barcode/catno matches, and local art already tied to this release.
- Discogs fuzzy matches must pass a **release-match confidence** check before being treated as Tier A. Compare track count, medium count, year, label and catno, and show the confidence. Fall back to Tier C when it is low.

### 5.2 Per-candidate score (0-100, fully explained)
Weighted sum, weights configurable under "Advanced":
- **Identity anchor** (largest weight): A > B > C.
- **Visual consensus**: size of the candidate's similarity cluster, counting *independent sources*, not duplicates from one provider.
- **Resolution fit**: closeness to the user's preferred size (e.g. ≥1000 px), penalise tiny images, mild penalty above the max useful size.
- **Aspect ratio**: strongly prefer ~1:1 for front, and penalise wide scans that include the spine or a crop.
- **Source reliability prior**: configurable per provider.
- **File quality**: format, estimated JPEG quality or compression artefacts, byte size sanity.
- **Placeholder / junk detection**: penalise known "no image" placeholders, 1x1 pixels, heavy watermarks, and near-blank images (low variance).
- **Type confidence**: how sure the provider is that this is truly a back cover, disc, etc.

Always show the breakdown in the UI tooltip.

### 5.3 Visual consensus
- Compute dHash (and pHash if feasible) on a normalised 32x32 / 64x64 grayscale. Treat Hamming distance under a configurable threshold as "same artwork".
- Handle common variations: different crops or borders (trim near-uniform margins before hashing), different compression, and slightly different colour grading. Optionally hash at a few crops.
- Use single-linkage or simple union-find clustering. For each cluster record member providers, best resolution, and whether it contains a Tier A/B anchor.
- **Choosing a cluster:** (1) a cluster containing a Tier A anchor, (2) else Tier B, (3) else the cluster with the **most distinct providers**, with the largest highest-resolution member as the tie-break. Within the winning cluster, pick the best-scoring member (usually the highest resolution from the most reliable source).
- Edge cases to handle explicitly:
  - **Remasters and reissues** with different art than the tagged release. This is the main false-positive risk, so surface the conflict instead of guessing.
  - **Deluxe editions, regional variants, explicit/clean covers.**
  - **Various Artists compilations.**
  - **Singles and EPs** with generic or ambiguous titles.

### 5.4 Disc-art matching
Goal: "Disc 2 art goes with disc 2 files."
- Per album, build a **disc map** from tags and MB data: medium position, format (CD, vinyl, SACD, DVD), title and total discs. Files with no `discnumber` are treated as disc 1 of 1.
- Disc candidates are assigned to a disc number by, in order:
  1. Explicit provider data (Fanart.tv `disc` field).
  2. CAA comment text (e.g. "Disc 2", "CD2", "Side B"). Parse the common patterns.
  3. Provider ordering heuristics (flagged low confidence).
  4. **Manual assignment** in the review dialog with drag-and-drop onto disc slots.
- If a single disc image is found for a multi-disc album, do not duplicate it onto every disc by default. Ask or flag. Offer "use for all discs" as an explicit option.
- Embedding rule: for each *track*, embed only the disc art that matches the track's disc. Do not embed every disc's art into every file.

## 6. Apply layer: safety, formats, files

### 6.1 Timing with Picard's rename/move
Picard renames and moves files on save, so the final album folder is only known **after save**. Therefore:
- Stage chosen images in the cache and a pending-apply queue.
- Embedding: add images to Picard's per-file metadata so Picard writes them with its normal save path.
- Files: write them in a **post-save hook**, once the destination folder is known. Offer **"Apply now"** for albums already in place (e.g. when tagging a library in place).
- Handle albums whose tracks are split across several folders: ask or use the folder with the most tracks.

### 6.2 Coexisting with Picard's native cover handling
Picard can already save `cover.jpg` and embed art. Provide a clear setting: **"CoverUp takes over cover handling"** (disables Picard's own save-to-file for this run) versus **"Work alongside"**. Detect when native "save images as files" would write the same filename and avoid double-writes.

### 6.3 File safety
- Write to a temp file, validate (decodable, expected size), then atomic-rename.
- **Backup** any replaced file to a `.coverup-backup/` (configurable) with a journal, and provide **Undo last apply** per album and per session.
- Never overwrite a larger or higher-resolution existing image unless "overwrite only if better" says so, or the user confirms.
- Dry-run / preview mode shows exactly which files and tags will change.
- Respect read-only files and report failures per item without aborting the batch.

### 6.4 Embedding specifics
- Use Picard's image/metadata classes and set `coverart_types` / `coverart_comment` correctly so Picard writes proper picture types.
- **Per-format capability matrix** and warnings:
  - ID3v2 (MP3): APIC with picture types. Mind tag size limits.
  - FLAC / Vorbis: PICTURE blocks with types. Large images bloat the file header.
  - MP4/M4A: `covr` has no picture types, so typically front only. Warn when back/disc selected.
  - ASF/WMA, WavPack, APE, Opus/Ogg: handle or warn per Picard's support.
- Defaults: **embed front only**, with a max dimension (e.g. ≤1000-1500 px) and a max byte size. Booklets and disc scans belong in files. Warn before embedding anything large.
- Provide "remove existing embedded art of the selected types before embedding" and "do not replace if existing is larger" options. Reuse Picard's existing semantics where possible so behaviour is familiar.

### 6.5 Image processing
Use `QImage`. Support resize (high-quality, never upscale unless asked), format conversion (WebP/AVIF/BMP/TIFF in, JPEG/PNG out), EXIF strip, CMYK/colour-profile sanity, optional **auto-trim of borders** for scans, and a minimum-quality check. Optionally call `oxipng`/`jpegoptim` if found on `PATH`, but never require them.

### 6.6 Logging and diagnostics (troubleshooting requirement)

CoverUp must write its own log file so that any problem can be diagnosed after the fact without asking the user to reproduce it. I assumed "2NB" in the brief meant **2 MB**. Treat 2 MB as the default fixed size.

**Location and naming**
- Default: a `coverup/logs/` folder inside Picard's per-user config/data directory (resolve it through Picard's API, not a hard-coded path). Main file `coverup.log`.
- The user can change the folder in Options. Validate it is writable and fall back to the default with a warning if not.
- Also forward WARNING and above to Picard's own log (`picard.log`) so problems appear in **Help → View Error/Debug Log**, but keep the detailed trace only in the CoverUp file.

**Size and retention modes (user-selectable in Options → Logging)**
1. **Fixed size (default).** Rotating files, **2 MB per file** (configurable, e.g. 1-50 MB) and **N backups** (default 3, so about 8 MB maximum on disk). Oldest backup is deleted when the limit is reached (`coverup.log.1`, `.2`, `.3`). Use the standard-library rotating handler or an equivalent that is safe on Windows (no rename-while-open failures).
2. **Variable size, capped by total.** One logical log that grows up to a user-set **total cap** (e.g. 25 MB), pruning the oldest whole files or oldest lines first.
3. **Variable size, by age.** Keep log files for **N days** (default 14), with a hard safety ceiling (e.g. 100 MB) so it can never fill a disk.
4. **Per-session files.** A new timestamped file each Picard session (`coverup-YYYYMMDD-HHMMSS.log`), keeping the last N sessions.
5. **Off.** Only WARNING and above go to Picard's log. (Not the default.)

**Levels**
- ERROR, WARNING, INFO (default), DEBUG, TRACE. TRACE is for raw provider payload summaries, scoring math and pHash distances.
- Changing the level takes effect immediately, without restarting Picard.
- Add a **"Verbose until restart"** toggle so a user can capture a problem without leaving debug logging on permanently.

**What to log (every entry has a timestamp with timezone, level, module, and a short run ID + album ID so one album's story can be followed across threads)**
- Plugin version, Picard version, Python/Qt versions, OS, and enabled providers (without keys) at startup.
- Per album: the built `Query` (identity anchors found: MBIDs, Discogs ID, barcode, catno), and the Discogs match confidence with the reasons.
- Per provider call: provider, endpoint (query string redacted of secrets), duration, HTTP status, retries/backoff, rate-limit waits, cache hit/miss, number of candidates returned.
- Per candidate: URL (or a stable ID), type, dimensions, bytes, tier, perceptual hash, cluster membership, and the **score breakdown**.
- Decisions: what was chosen per art type, whether auto or by the user, the one-line rationale, and conflicts that blocked auto-apply.
- Apply stage: resolved destination folder, final filenames, embed vs file, format conversion/resize, collision policy outcome, backup paths, and undo-journal entries.
- Every exception with a full traceback, and every skipped or degraded step (missing key, disabled provider, unsupported tag format) with the reason.
- Resolution decisions: each candidate rejected or accepted by the §3.5 limits and why.
- Creative fallback: which trigger fired, the method order tried, template name, backend, seed, model, the **final prompt text** (without secrets), generation time and cost estimate, logo chosen, and the provenance written. Never log reference-image bytes.
- Timing summary per album (discover / fingerprint / score / apply) to help spot slow providers.

**What must never be logged**
- API keys, tokens, OAuth secrets and `Authorization` headers. Apply a **central redaction filter** (regexes plus exact-value masking of every configured secret) to *all* handlers, and add a unit test that fails if a known fake key appears in any log output.
- Full tag contents or file paths beyond what is needed. Offer a **"Anonymise paths and names"** option for logs the user wants to share (replace the home directory and artist/album text with stable hashes while keeping IDs).

**Reliability and performance**
- Logging must never crash the plugin or block the UI. Use a queue-based handler (`QueueHandler` / `QueueListener` or equivalent) so disk I/O happens off the UI and worker threads.
- Flush on ERROR, and on exit. Survive a full disk or read-only folder by disabling file logging with a single warning rather than raising.
- Rate-limit repeated identical messages (e.g. collapse "same warning ×200") so one failing provider cannot flood the file.

**User-facing tools**
- Options → Logging page: mode, size, backups/days/cap, level, folder, anonymise toggle, and buttons: **Open log folder**, **Open current log**, **Clear logs**, **Copy recent log to clipboard**.
- **"Export diagnostics bundle…"**: a zip containing the recent log files, a **redacted** settings dump (keys replaced by `***set***`/`***unset***`), version/environment info, the provider health/last-error table, and optionally the `Decision` records for selected albums. This is what a user attaches to a bug report.
- A small **in-app log viewer** (read-only, filter by level/album/provider, search) is a nice-to-have.
- A **"Provider health" panel** in Options showing each provider's last success time, last error, and rate-limit status, with a **Test connection** button that logs the full result.

## 7. UI/UX design

1. **Entry points**
   - Context menu on albums, clusters, tracks and files: **"CoverUp: Find artwork…"**, **"CoverUp: Auto-apply with saved profile"**, **"CoverUp: Undo last apply"**.
   - Optional **automatic mode** during load: runs after a release is matched and only applies when confidence is high. Otherwise it queues the album for review.
2. **Review dialog** (core screen)
   - Left: album identity (art on current files, MB release, matched Discogs release with a confidence badge, counts).
   - Main: **tabbed or sectioned grid** by art type (Front | Back | Discs | Booklet | Artist), each candidate shown as a thumbnail card with provider badge, dimensions, size in KB, tier badge (A/B/C), score, and a "cluster ×N" agreement badge. The auto-selected pick is highlighted.
   - Click to select. Per-type "None" is a valid choice. A master **"Apply types"** checklist (Front / Back / Disc / Booklet / Artist) controls what gets applied.
   - **Creative tab** (shown when enabled or triggered): template picker with samples, "match era / match genre" toggles, backend selector, a **variations grid** (N generated candidates with "regenerate", "new seed", "edit prompt"), a logo picker (era variants) with position/scale/title overlay controls and a live composite preview, and a persistent **AI-generated** badge. Also a per-album switch: *Use real art / Use generated art / Ask*.
   - **Resolution indicators**: each card shows the pixel size with a colour hint (below minimum / OK / above maximum), and a "Show below-minimum candidates" toggle.
   - **Compare view**: before/after slider between existing art and a candidate, with pixel dimensions.
   - **Discs section**: shows detected discs, so users can assign images to disc slots.
   - Destination panel: Embed ☐ / Save to folder ☐, folder preset dropdown (covers / art / artwork / booklet / custom / same folder), and a live **preview of the resulting file paths**.
   - Footer: **Apply**, **Apply to all similar albums in this batch**, **Skip**, and **Remember my choice**.
3. **Batch mode**: a queue with a progress view, then a **review list** with each album's status (✔ auto-applied, ⚠ needs review, ✖ none found, ⏭ skipped). Keyboard navigation: next/prev album, accept, skip.
4. **Options page** (Picard Options → Plugins → CoverUp) with sections: Sources (enable, order, keys, test-connection buttons), Matching (thresholds, weights, auto-apply confidence), **Resolution (§3.5: search min/max and apply limits per art type)**, **Creative / AI (§3.6: trigger, method order, templates, backends, consent, logo and overlay settings, generation limits)**, Types, Output (embed/files, folder preset, naming templates, format and size limits), Safety (backup, overwrite policy, undo), Cache, **Logging (see §6.6)**, and Advanced.
5. **Profiles**: named presets (e.g. "Minimal: embed front only", "Archivist: everything to /artwork", "Media server: cover.jpg + artist.jpg"), selectable per run.
6. Accessibility and polish: keyboard-operable, sensible high-DPI thumbnails, translatable strings, no modal dead-ends during network failures.

## 8. Additional features to include (from review of other tools)

I reviewed Picard's built-in providers and plugins (CAA, CAA release group, whitelisted URLs, local files, fanart.tv, TheAudioDB, Amazon), beets `fetchart`/`embedart`, SACAD, Album Art Downloader-style tools, and media-server artwork conventions. These are the features worth adopting, ordered by value:

**Must-have (ship in v1)**
- **Provider ordering and enable/disable with "first good result" vs "gather all" modes.** Picard stops at the first provider that returns art, whereas CoverUp gathers all of them for consensus. Offer both, and make "gather all" the default.
- **Size and quality filters:** minimum/maximum width and height, max file size, aspect-ratio enforcement (beets `fetchart`: `minwidth`, `maxwidth`, `enforce_ratio`).
- **"Don't replace existing art if the new one is smaller / not better"** (Picard and beets `embedart` equivalents), extended with a similarity threshold so an effectively identical image is not re-written.
- **Scoring that combines source reliability, size, format and similarity to a reference** (SACAD's key idea). Here, the reference is the Tier A anchor or the existing art.
- **Caching and rate limiting:** on-disk HTTP cache with ETag/Last-Modified, per-provider token buckets, exponential backoff, a descriptive User-Agent with contact info, and respect for `Retry-After`.
- **Dry run and undo journal.**
- **Manual add:** paste a URL, drag-and-drop an image file, or paste from the clipboard into any art-type slot.
- **Remember decisions** per release MBID, with a "forget / re-search" action.

**Should-have (v1.x)**
- **Placeholder / "no image" detector** and low-variance image rejection.
- **Auto-trim and deskew** for flatbed scans of back covers, discs and booklets.
- **Booklet handling:** group multi-page booklet scans, name them `booklet-01…`, and optionally build a PDF.
- **Media-server naming presets** matching Kodi/Jellyfin/Plex/Navidrome/Roon conventions: `cover.jpg` / `folder.jpg` / `front.jpg` for the album, `artist.jpg` in the artist folder, `disc.png`/`cdart.png`, `logo.png`, `banner.jpg`, `fanart.jpg`. Verify the exact lookup order of the target server (for example Navidrome's cover art priority setting) and document it.
- **Library audit mode:** scan selected albums and report missing/low-resolution/mismatched art without changing anything. Export the report as CSV.
- **Expose script variables** (e.g. `%_coverup_status%`, `%_coverup_source%`, `%_coverup_confidence%`) so users can build custom columns and file-naming rules, and sort by "needs review".
- **Source provenance tagging:** optionally record the art's source URL or provider in the image comment, and in a sidecar `coverup.json` so decisions are reproducible.
- **Conflict explanations:** a one-line plain-language reason for every auto-decision ("Chose CAA release image; Discogs and iTunes agree, 3 sources").

**Nice-to-have (later)**
- **Upscaling hint only** (flag low-res; never auto-upscale), and optional integration with a user-provided external upscaler command.
- **Format modernisation:** optional WebP/AVIF output for files (not for embedding, since player support is poor).
- **Multi-resolution outputs:** e.g. `cover.jpg` full size plus `cover-500.jpg` thumbnail for portable devices.
- **Colour-dominant extraction** exposed as a script variable, for players or dashboards.
- **Submit-back helper:** when CoverUp finds good art that the CAA lacks, offer to open the MusicBrainz "Add cover art" page with the URL prefilled. It must never upload automatically, and it must respect licensing.
- **Scheduled/unattended re-check** for albums previously marked "none found".

## 9. Delivery plan

**Phase 0, research (no code):** confirm the Plugin V3 API surface, manifest schema, available hooks, web-service usage, and the image/metadata classes. Produce a short "API contract" note listing the exact functions you will call. Resolve every "verify" item in this document and list the answers. Check each provider's current API terms, auth and rate limits.

**Phase 1, vertical slice (logging from day one, with the fixed-size 2 MB rotating log, redaction filter and levels; the other retention modes and the diagnostics bundle follow in Phase 3):** CAA + Discogs identity resolution, Tier A/B/C scoring (without consensus), review dialog with front only, embed + save-to-folder with `covers` default, safe write + backup.

**Phase 2:** resolution limits (§3.5, search and apply), perceptual-hash consensus, remaining providers, back/disc/booklet/artist types, disc-number matching, per-type routing, naming templates, profiles.

**Phase 3:** creative fallback and AI templates (§3.6: trigger logic, non-AI template compositor and logo overlay first, then fan-art fallback, then the AI backends, variations grid, provenance and consent), all log retention modes (variable by total/age, per-session), diagnostics bundle, provider health panel, batch/queue mode, audit mode, undo UI, media-server presets, script variables, caching hardening, placeholder detection, auto-trim.

**Phase 4:** packaging for the Picard Plugins Registry, documentation, screenshots, localisation scaffolding.

For each phase deliver: working code, unit tests, and a short changelog.

## 10. Quality bar and acceptance criteria

**Testing**
- Unit tests for scoring, clustering (with synthetic images: identical, recompressed, cropped, different art), disc-number parsing, filename template rendering, path sanitising, and collision policy.
- **Recorded-fixture tests** for each provider (no live network in CI). Include a small live "smoke test" script that is run manually with real keys.
- Tag-format tests: embed and read back on MP3, FLAC, M4A, OGG with expected picture types.
- Failure-injection tests: timeouts, 429/5xx, malformed JSON, truncated images, read-only files, full disk.
- Logging tests: rotation at the size limit in each mode, retention pruning, secret redaction (fake keys never appear), path anonymisation, repeat-message collapsing, and that an unwritable log folder degrades gracefully.

**Acceptance criteria (all must hold)**
1. For a release with exact CAA art, CoverUp selects it over visually different web results.
2. For a release with no exact-release art, the winning cover is the largest multi-source visual-agreement cluster, and the UI says so.
3. When tiers conflict, the album is flagged and **nothing is auto-applied**.
4. The user can apply any subset of {front, back, disc, booklet, artist}, and only that subset is written.
5. Disc art for disc N is embedded and filed only against disc N tracks.
6. Output to `covers` (default), `art`, `artwork`, `booklet`, a custom name, or the same folder works, including after Picard renames/moves files.
7. No existing file is lost: every replacement is backed up and undoable.
8. The UI never freezes, long jobs can be cancelled, and API limits are never exceeded.
9. Missing keys or disabled providers degrade gracefully with a clear message and no crashes.
10. Passes on Windows, macOS and Linux, including paths with Unicode and spaces.
11. A log file is always produced (unless the user turns it off), never exceeds its configured size/retention limits in any mode (default 2 MB per file, 3 backups), contains no secrets (verified by test), and a single album's full decision path can be reconstructed from the log alone using its run/album ID.
12. "Export diagnostics bundle" produces a redacted zip that is sufficient to reproduce a typical bug report (versions, settings, provider health, recent logs).
13. Search min/max resolution and apply (embed/file) limits are enforced independently per art type; nothing below the apply minimum is written, nothing is upscaled unless explicitly enabled, and every rejection is explained.
14. With the fallback trigger on, an album with no art (or art below the apply minimum) gets creative art by the chosen method order; with it off, the album is left untouched.
15. "Always use generated art" produces art from the chosen fixed template **even when a real cover exists**, can be limited to front only, and never touches real back/disc art unless asked.
16. The artist logo and album title are composited by the plugin (not rendered by the AI model), are correctly spelled and sharp, and use an era-matched logo when one is available, with a typographic fallback when not.
17. Every generated image is labelled (tag comment, sidecar, script variable, UI badge), is never uploaded anywhere, never outranks real art outside the two opt-in cases, and is reproducible from its stored seed/prompt/template.
18. The AI backend being offline, rate-limited or unconfigured degrades to the non-AI template or no-op without failing the batch.

**Non-goals (for now):** audio fingerprinting, tagging metadata other than art-related fields, uploading anything to CAA automatically (and never AI-generated art), presenting generated art as official release artwork, bundling or hosting any AI model, scraping sites whose terms forbid it, and cloud services operated by the plugin author.

## 11. Open questions to resolve in Phase 0 (answer them, don't guess)
1. Exact Plugin V3 manifest fields, entry point and registry submission process.
2. Which Picard hooks expose "final path after save", and how do other plugins write sidecar files safely?
3. How does Picard 3 represent image types and comments on `CoverArtImage`, and which formats honour them?
4. Current status, quotas and ToS of Google Custom Search JSON API, Discogs image access, Fanart.tv personal vs project keys, and TheAudioDB free-tier limits.
5. Whether a bundled Pillow is available in Picard 3 frozen builds. If not, the pure-`QImage` path is mandatory.
6. How to avoid double-writing against Picard's native "save images as files" setting.
7. Current API shape, auth, size limits and terms of the target AI backends (local Stable-Diffusion-compatible servers, OpenAI-compatible image endpoints), and whether they support seeds and image-to-image.
8. What logo metadata fanart.tv / TheAudioDB actually expose (variants, dates, likes) so era matching is feasible, and their attribution/usage terms for logos.
9. Whether Qt text/logo compositing can be done safely in a worker thread in Picard 3 (`QImage`/`QPainter` off the GUI thread), and which fonts are safely available cross-platform.

**Output format for your response:** begin with the Phase 0 findings and any deviations from this brief (with reasons), then the architecture as built, then the code module by module with tests. Flag every assumption you could not verify.
