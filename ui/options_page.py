# -*- coding: utf-8 -*-
# CoverUp: MusicBrainz Picard plugin. GPL-2.0-or-later.
"""Options > Plugins > CoverUp. Built from a declarative field list so every setting in settings.py
has exactly one widget, one loader and one saver."""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..settings import DEFAULTS, PROVIDER_LABELS, PROVIDERS

log = logging.getLogger("coverup.ui")

C = lambda *pairs: list(pairs)  # noqa: E731

HELP = {
    "discogs_token": "Get one at discogs.com > Settings > Developers > Generate new token.",
    "fanart_api_key": "Project API key from fanart.tv/get-an-api-key (free).",
    "fanart_client_key": "Optional personal key: newer images appear sooner.",
    "audiodb_api_key": "123 is TheAudioDB's public test key (rate limited). Use your own if you have one.",
    "lastfm_api_key": "Create one at last.fm/api/account/create.",
    "websearch_api_key": "Your own Brave Search API key or Google API key. Search pages are never scraped.",
    "websearch_google_cx": "Google Programmable Search engine ID (only for Google). Google may not issue new keys.",
}

FIELDS: dict[str, list[tuple]] = {
    "Sources": [
        ("discogs_token", "Discogs token", "password", None),
        ("fanart_api_key", "Fanart.tv API key", "password", None),
        ("fanart_client_key", "Fanart.tv personal key", "password", None),
        ("audiodb_api_key", "TheAudioDB key", "password", None),
        ("lastfm_api_key", "Last.fm API key", "password", None),
        ("websearch_engine", "Web image search engine", "choice", C(("brave", "Brave Search API"), ("google", "Google Programmable Search"))),
        ("websearch_api_key", "Web search API key", "password", None),
        ("websearch_google_cx", "Google search engine ID (cx)", "text", None),
        ("http_cache_hours", "Cache web results for (hours)", "int", (0, 720)),
        ("max_candidates_per_provider", "Max results per source", "int", (1, 50)),
    ],
    "Matching & resolution": [
        ("auto_apply_mode", "Auto-apply", "choice", C(("confident", "Only confident, non-conflicting results"), ("never", "Never (always review)"))),
        ("hamming_threshold", "Visual similarity tolerance (bits of 64)", "int", (1, 30)),
        ("conflict_min_sources", "Sources needed to flag a conflict", "int", (2, 10)),
        ("min_front", "Search minimum: front (px)", "int", (0, 5000)),
        ("min_back", "Search minimum: back (px)", "int", (0, 5000)),
        ("min_disc", "Search minimum: disc (px)", "int", (0, 5000)),
        ("min_booklet", "Search minimum: booklet (px)", "int", (0, 5000)),
        ("min_artist", "Search minimum: artist images (px)", "int", (0, 5000)),
        ("max_side", "Search maximum, any type (px, 0 = none)", "int", (0, 30000)),
        ("target_size", "Preferred size (px)", "int", (100, 10000)),
        ("prefer_largest", "Prefer the largest image instead of the preferred size", "bool", None),
        ("front_aspect_tolerance", "Square tolerance for front/disc (0.05 = ±5%)", "float", (0.0, 0.5)),
        ("max_file_mb", "Largest download (MB)", "int", (1, 200)),
        ("apply_min_side", "Apply minimum: never apply art smaller than (px)", "int", (0, 5000)),
        ("embed_max_side", "Embedded images: max size (px, 0 = original)", "int", (0, 10000)),
        ("file_max_side", "Saved files: max size (px, 0 = original)", "int", (0, 30000)),
        ("upscale_to_minimum", "Upscale small images to the minimum (lower quality; off by default)", "bool", None),
    ],
    "Output": [
        ("apply_types", "Default art types", "multi", C(("front", "Front"), ("back", "Back"), ("disc", "Discs"), ("booklet", "Booklet"), ("artist", "Artist images"))),
        ("embed", "Embed in tags", "bool", None),
        ("save_files", "Save as files", "bool", None),
        ("folder_mode", "Where files go", "choice", C(("subfolder", "A sub-folder of the album"), ("same", "The album folder itself"))),
        ("folder_name", "Sub-folder name (covers, art, artwork, booklet or your own)", "text", None),
        ("front_in_album_folder", "Also put the front cover in the album folder (players look there)", "bool", None),
        ("naming_preset", "File names", "choice", C(("default", "Default: cover, back, disc1, booklet-01, artist"), ("kodi", "Kodi/Jellyfin: folder, back, cdart1, logo, fanart"), ("plex", "Plex: cover, back, disc1, background"), ("custom", "Custom (below)"))),
        ("name_front", "Custom name: front", "text", None),
        ("name_back", "Custom name: back", "text", None),
        ("name_disc", "Custom name: disc ({discnumber})", "text", None),
        ("name_booklet", "Custom name: booklet ({n})", "text", None),
        ("name_artist_thumb", "Custom name: artist photo", "text", None),
        ("name_artist_logo", "Custom name: artist logo", "text", None),
        ("name_artist_background", "Custom name: artist background", "text", None),
        ("name_artist_banner", "Custom name: artist banner", "text", None),
        ("save_artist_art", "Save artist images in the artist folder (parent of the album folder)", "bool", None),
        ("file_format", "File format", "choice", C(("original", "Keep original"), ("jpeg", "JPEG"), ("png", "PNG"))),
        ("jpeg_quality", "JPEG quality", "int", (50, 100)),
        ("collision_policy", "If a file already exists", "choice", C(("if_better", "Replace only if the new image is larger"), ("overwrite", "Replace"), ("skip", "Keep the existing file"), ("keep_both", "Keep both (cover-2.jpg)"))),
        ("backups", "Back up replaced files (.coverup-backup) so they can be undone", "bool", None),
        ("write_files_when", "Write files", "choice", C(("on_save", "When the album is saved in Picard (follows renames/moves)"), ("immediately", "Immediately (library already organised)"))),
        ("multi_folder", "Albums split across folders (CD1/CD2)", "choice", C(("every", "Album-wide images in every folder"), ("first", "Only in the first folder"))),
        ("replace_embedded", "Remove existing embedded images of the applied types first", "bool", None),
        ("record_source_in_comment", "Record the source in the embedded image comment", "bool", None),
        ("write_sidecar", "Write coverup.json describing where each file came from", "bool", None),
    ],
    "Creative / AI": [
        ("creative_triggers", "Generate art when", "multi", C(("no_cover", "No cover is found"), ("below_min", "The best cover is below the apply minimum"), ("low_confidence", "Only conflicting/unanchored covers are found"))),
        ("creative_always", "Always use generated art for the front cover, even when a real cover exists", "bool", None),
        ("creative_method_order", "Try, in order", "order", C(("fanart,ai,template", "Fan art → AI → offline template"), ("ai,template", "AI → offline template"), ("fanart,template", "Fan art → offline template"), ("template", "Offline template only"), ("ai", "AI only"), ("fanart", "Fan art only"))),
        ("creative_template", "Style template", "template", None),
        ("creative_custom_prompt", "Custom prompt ({artist} {album} {year} {genre} {era})", "text", None),
        ("creative_match_era", "Match the era of the release year", "bool", None),
        ("creative_match_genre", "Match the genre", "bool", None),
        ("creative_variations", "Variations per generation (dialog)", "int", (1, 8)),
        ("creative_overlay_logo", "Draw the band logo (or the artist name)", "bool", None),
        ("creative_overlay_title", "Draw the album title", "bool", None),
        ("creative_logo_position", "Logo position", "choice", C(("top", "Top"), ("center", "Centre"), ("bottom", "Bottom"))),
        ("creative_max_per_run", "Max generated covers per auto-apply run", "int", (0, 1000)),
        ("ai_backend", "AI backend", "choice", C(("none", "None (offline templates only)"), ("automatic1111", "Local Stable Diffusion (AUTOMATIC1111 --api)"), ("openai", "OpenAI-compatible images API"), ("custom", "Custom HTTP endpoint"))),
        ("ai_url", "AI endpoint URL", "text", None),
        ("ai_model", "Model (optional)", "text", None),
        ("ai_api_key", "AI API key", "password", None),
        ("ai_size", "Image size (px)", "int", (256, 2048)),
        ("ai_steps", "Steps (Stable Diffusion)", "int", (1, 150)),
        ("ai_img2img", "Use the low-res cover as a reference (image-to-image)", "bool", None),
        ("ai_allow_remote_reference", "Allow sending the reference image to remote AI services", "bool", None),
    ],
    "Logging": [
        ("log_mode", "Log file", "choice", C(("fixed", "Fixed size: rotating files"), ("total", "Variable: capped total size"), ("age", "Variable: keep for N days"), ("session", "One file per Picard session"), ("off", "Off (warnings go to Picard's log)"))),
        ("log_max_mb", "File size (MB)", "int", (1, 50)),
        ("log_backups", "Backups kept (fixed size)", "int", (0, 20)),
        ("log_total_cap_mb", "Total cap (MB)", "int", (1, 1000)),
        ("log_retain_days", "Keep for (days)", "int", (1, 365)),
        ("log_sessions_keep", "Sessions kept", "int", (1, 50)),
        ("log_level", "Detail level", "choice", C(("ERROR", "Errors"), ("WARNING", "Warnings"), ("INFO", "Normal"), ("DEBUG", "Debug"), ("TRACE", "Trace (very detailed)"))),
        ("log_anonymise", "Anonymise paths and album names (for sharing)", "bool", None),
        ("log_folder", "Log folder (empty = default)", "text", None),
    ],
}


def _make_options_page_class(base):
    class CoverUpOptionsPage(base):
        NAME = "coverup"
        TITLE = "CoverUp"
        PARENT = "plugins"

        def __init__(self, parent=None):
            super().__init__(parent)
            self.widgets: dict[str, tuple[str, object]] = {}
            outer = QVBoxLayout(self)
            tabs = QTabWidget()
            outer.addWidget(tabs)
            for tab, fields in FIELDS.items():
                page = QWidget()
                form = QFormLayout(page)
                form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
                if tab == "Sources":
                    form.addRow(QLabel("<b>Sources</b> (tick to use; drag to set the order)"))
                    self.provider_list = QListWidget()
                    self.provider_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
                    self.provider_list.setMaximumHeight(220)
                    form.addRow(self.provider_list)
                if tab == "Creative / AI":
                    note = QLabel(
                        "Generated art is for your personal library. It is always labelled as generated and never uploaded. "
                        "Remote AI services receive the artist, album title, year and genre, and ask for your consent first. "
                        "Recreating an existing cover from a reference image is your responsibility."
                    )
                    note.setWordWrap(True)
                    form.addRow(note)
                for key, label, kind, opt in fields:
                    w = self._widget(kind, opt)
                    self.widgets[key] = (kind, w)
                    if key in HELP:
                        w.setToolTip(HELP[key])
                    form.addRow(label, w)
                    if key in HELP:
                        hl = QLabel(f"<small>{HELP[key]}</small>")
                        hl.setWordWrap(True)
                        form.addRow("", hl)
                if tab == "Creative / AI":
                    row = QHBoxLayout()
                    b1 = QPushButton("Open my templates folder")
                    b1.clicked.connect(self._open_templates)
                    b2 = QPushButton("Forget AI service approvals")
                    b2.clicked.connect(lambda: self._set("ai_consented_hosts", []))
                    row.addWidget(b1)
                    row.addWidget(b2)
                    form.addRow(row)
                if tab == "Logging":
                    row = QHBoxLayout()
                    for text, fn in (("Open log folder", self._open_logs), ("Export diagnostics bundle…", self._export), ("Clear download cache", self._clear_cache)):
                        b = QPushButton(text)
                        b.clicked.connect(fn)
                        row.addWidget(b)
                    form.addRow(row)
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setWidget(page)
                tabs.addTab(scroll, tab)

        # ---- widgets ----
        def _widget(self, kind, opt):
            if kind == "bool":
                return QCheckBox()
            if kind == "int":
                w = QSpinBox()
                w.setRange(*opt)
                return w
            if kind == "float":
                w = QDoubleSpinBox()
                w.setRange(*opt)
                w.setSingleStep(0.01)
                w.setDecimals(2)
                return w
            if kind in ("text", "password"):
                w = QLineEdit()
                if kind == "password":
                    w.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
                return w
            if kind in ("choice", "order"):
                w = QComboBox()
                for value, label in opt:
                    w.addItem(label, value)
                return w
            if kind == "template":
                from ..creative.template_engine import CUSTOM, load_templates
                from ..glue import STATE

                w = QComboBox()
                for name, t in sorted(load_templates(STATE.user_templates_dir()).items(), key=lambda kv: kv[1].title):
                    w.addItem(t.title, name)
                w.addItem("Custom prompt", CUSTOM)
                return w
            if kind == "multi":
                box = QWidget()
                lay = QHBoxLayout(box)
                lay.setContentsMargins(0, 0, 0, 0)
                box.checks = []
                for value, label in opt:
                    cb = QCheckBox(label)
                    cb.setProperty("value", value)
                    lay.addWidget(cb)
                    box.checks.append(cb)
                lay.addStretch(1)
                return box
            raise ValueError(kind)

        def _cfg(self):
            return self.api.plugin_config

        def _get(self, key):
            try:
                v = self._cfg()[key]
            except Exception:
                v = None
            return DEFAULTS[key] if v is None else v

        def _set(self, key, value):
            self._cfg()[key] = value

        def load(self):
            enabled = set(self._get("providers_enabled") or [])
            order = [p for p in (self._get("provider_order") or []) if p in PROVIDERS]
            order += [p for p in PROVIDERS if p not in order]
            self.provider_list.clear()
            for pid in order:
                item = QListWidgetItem(PROVIDER_LABELS[pid])
                item.setData(Qt.ItemDataRole.UserRole, pid)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
                item.setCheckState(Qt.CheckState.Checked if pid in enabled else Qt.CheckState.Unchecked)
                self.provider_list.addItem(item)
            for key, (kind, w) in self.widgets.items():
                v = self._get(key)
                if kind == "bool":
                    w.setChecked(bool(v))
                elif kind == "int":
                    w.setValue(int(v))
                elif kind == "float":
                    w.setValue(float(v))
                elif kind in ("text", "password"):
                    w.setText(str(v))
                elif kind in ("choice", "template"):
                    idx = w.findData(v)
                    w.setCurrentIndex(max(0, idx))
                elif kind == "order":
                    idx = w.findData(",".join(v) if isinstance(v, (list, tuple)) else str(v))
                    w.setCurrentIndex(max(0, idx))
                elif kind == "multi":
                    vals = set(v or [])
                    for cb in w.checks:
                        cb.setChecked(cb.property("value") in vals)

        def save(self):
            order, enabled = [], []
            for i in range(self.provider_list.count()):
                item = self.provider_list.item(i)
                pid = item.data(Qt.ItemDataRole.UserRole)
                order.append(pid)
                if item.checkState() == Qt.CheckState.Checked:
                    enabled.append(pid)
            self._set("provider_order", order)
            self._set("providers_enabled", enabled)
            for key, (kind, w) in self.widgets.items():
                if kind == "bool":
                    v = w.isChecked()
                elif kind == "int":
                    v = int(w.value())
                elif kind == "float":
                    v = float(w.value())
                elif kind in ("text", "password"):
                    v = w.text().strip()
                elif kind in ("choice", "template"):
                    v = w.currentData()
                elif kind == "order":
                    v = [x for x in str(w.currentData()).split(",") if x]
                elif kind == "multi":
                    v = [cb.property("value") for cb in w.checks if cb.isChecked()]
                else:
                    continue
                self._set(key, v)
            from ..apply.files import validate_folder_name

            try:
                validate_folder_name(self._get("folder_name"))
            except ValueError:
                self._set("folder_name", "covers")
            from .. import reconfigure_logging

            reconfigure_logging()

        # ---- buttons ----
        def _open_logs(self):
            from .. import current_log_folder

            folder = current_log_folder()
            folder.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

        def _open_templates(self):
            from ..glue import STATE

            folder = STATE.user_templates_dir()
            folder.mkdir(parents=True, exist_ok=True)
            readme = folder / "README.txt"
            if not readme.exists():
                readme.write_text(
                    "Put your own CoverUp style templates here (*.toml). Copy one of the built-in templates from the\n"
                    "plugin's creative/templates folder as a starting point. A template here with the same name as a\n"
                    "built-in one replaces it.\n",
                    encoding="utf-8",
                )
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

        def _export(self):
            from .. import __version__, current_log_folder
            from ..diagnostics.bundle import create
            from ..glue import STATE

            path, _ = QFileDialog.getSaveFileName(self, "Export diagnostics bundle", str(Path.home() / "coverup-diagnostics.zip"), "Zip (*.zip)")
            if not path:
                return
            s = STATE.settings()
            try:
                import picard

                pv = getattr(picard, "PICARD_FANCY_VERSION_STR", "?")
            except Exception:
                pv = "?"
            create(path, current_log_folder(), s.redacted(), {"coverup": __version__, "picard": pv}, s.secrets())
            QMessageBox.information(self, "CoverUp", f"Saved {path}. API keys are not included.")

        def _clear_cache(self):
            import shutil

            from ..glue import STATE

            shutil.rmtree(STATE.cache_root() / "http", ignore_errors=True)
            QMessageBox.information(self, "CoverUp", "Download cache cleared.")

    return CoverUpOptionsPage
