# CoverUp (MusicBrainz Picard plugin)

Find, compare and apply album artwork from many sources, as embedded tags, as files in a folder you name, or both.

**Status: early development (Phase 1 skeleton).** Not yet usable from Picard's menus. What exists today is the tested core:

| Area | Module | State |
|---|---|---|
| Data model, tiers (A exact release / B release group / C unanchored / G generated) | `model.py` | done |
| Perceptual hashing, similarity clustering | `matching/phash.py`, `matching/cluster.py` | done, tested |
| Resolution limits, scoring with explanations, consensus selection, conflict detection | `matching/scoring.py` | done, tested |
| Disc-number matching | `matching/disc.py` | done, tested |
| Folder names (`covers` default, `art`, `artwork`, `booklet`, custom), file names, atomic writes, backups, undo journal | `apply/files.py` | done, tested |
| Logging: 2 MB x 3 rotating default, variable-size modes, secret redaction, run/album IDs | `diagnostics/logging_setup.py` | done, tested |
| Creative/AI fallback trigger logic | `creative/trigger.py` | logic only; no image generation yet |
| Plugin entry point (logging + settings) | `__init__.py`, `MANIFEST.toml` | skeleton |

Not built yet: provider clients (Cover Art Archive, Discogs, Fanart.tv, ...), the review dialog, the Picard actions and file post-save hook, options page, AI backends, logo/title compositor. See `docs/design-prompt.md` for the full design and `docs/phase0-api-contract.md` for the verified Picard 3.0 plugin API notes.

## Requirements
Picard 3.0+ (Python 3.10+, PyQt6). No third-party Python packages are needed (Picard does not bundle Pillow, so image work uses Qt).

## Development
```
python -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest -q          # runs without Picard installed
picard-cli plugins install .           # install this folder into Picard 3 for manual testing
```

## Licence
GPL-2.0-or-later, same as Picard.
