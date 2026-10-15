# -*- coding: utf-8 -*-
# CoverUp: MusicBrainz Picard plugin. GPL-2.0-or-later.
"""CoverUp: find, compare and apply album artwork (Picard 3 plugin).

Only this module and (later) ``picard_glue/`` touch Picard. Everything else is plain Python so it can
be unit tested without Picard installed. Picard-facing code is imported lazily inside ``enable`` so the
package stays importable in tests.

Status: Phase 1 skeleton. ``enable`` currently sets up logging and registers settings only; the
artwork actions and the review dialog come next (see docs/design-prompt.md and docs/phase0-api-contract.md).
"""

from __future__ import annotations

__version__ = "0.1.0"

_log_handle = None

# plugin_config option name -> default (see docs/phase0-api-contract.md)
_OPTION_DEFAULTS = {
    "log_mode": "fixed",  # fixed | total | age | session | off
    "log_max_mb": 2,
    "log_backups": 3,
    "log_total_cap_mb": 25,
    "log_retain_days": 14,
    "log_level": "INFO",
    "log_anonymise": False,
}


def enable(api) -> None:
    """Plugin entry point (Plugin V3 API)."""
    global _log_handle
    from pathlib import Path

    from picard.const import appdirs

    from .diagnostics.logging_setup import MB, LogSettings, setup_logging

    for key, default in _OPTION_DEFAULTS.items():
        api.plugin_config.register_option(key, default)

    cfg = api.plugin_config
    folder = Path(appdirs.cache_folder()) / "coverup" / "logs"
    settings = LogSettings(
        folder=folder,
        mode=str(cfg["log_mode"]),
        max_bytes=int(cfg["log_max_mb"]) * MB,
        backups=int(cfg["log_backups"]),
        total_cap_bytes=int(cfg["log_total_cap_mb"]) * MB,
        retain_days=int(cfg["log_retain_days"]),
        level=str(cfg["log_level"]),
        anonymise=bool(cfg["log_anonymise"]),
    )

    def to_picard(level: int, message: str) -> None:
        import logging

        (api.logger.error if level >= logging.ERROR else api.logger.warning)(message)

    _log_handle = setup_logging(settings, picard_sink=to_picard)
    import logging

    log = logging.getLogger("coverup")
    log.info("CoverUp %s starting (Picard plugin API 3.0)", __version__)
    for w in _log_handle.warnings:
        api.logger.warning(w)


def disable() -> None:
    """Close the log file when the plugin is disabled."""
    global _log_handle
    if _log_handle is not None:
        _log_handle.close()
        _log_handle = None
