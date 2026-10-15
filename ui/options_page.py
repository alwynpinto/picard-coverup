# -*- coding: utf-8 -*-
# CoverUp: MusicBrainz Picard plugin. GPL-2.0-or-later.
"""Options > Plugins > CoverUp.

Built from a declarative layout (tabs > sections > fields) so every setting in settings.py has exactly
one widget, one loader and one saver. Layout rules: short labels, explanations in small grey text under
the field, checkboxes carry their own text, nothing wider than the window.
"""

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
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..settings import DEFAULTS, NAMING_PRESETS, PROVIDER_LABELS, PROVIDERS

log = logging.getLogger("coverup.ui")

C = lambda *pairs: list(pairs)  # noqa: E731

# field = (key, label, kind, options, help)
#   kinds: bool, int, float, text, password, choice, order, multi, template
#   int/float options: (min, max, suffix)
LAYOUT: dict[str, list[tuple[str, list[tuple]]]] = {
    "Sources": [
        ("Sources", []),  # provider list is inserted here
        ("API keys", [
            ("discogs_token", "Discogs token", "password", None, "discogs.com > Settings > Developers > Generate new token."),
            ("fanart_api_key", "Fanart.tv key", "password", None, "Free project key from fanart.tv/get-an-api-key."),
            ("fanart_client_key", "Fanart.tv personal key", "password", None, "Optional: newer images appear sooner."),
            ("audiodb_api_key", "TheAudioDB key", "password", None, "123 is TheAudioDB's public test key (slower)."),
            ("lastfm_api_key", "Last.fm key", "password", None, "Optional. Create one at last.fm/api/account/create."),
        ]),
        ("Web image search (your own key)", [
            ("websearch_engine", "Engine", "choice", C(("brave", "Brave Search API"), ("google", "Google Programmable Search")), None),
            ("websearch_api_key", "API key", "password", None, "Search pages are never scraped; only the official API is used."),
            ("websearch_google_cx", "Google engine ID (cx)", "text", None, "Only for Google. Google may no longer issue new keys."),
        ]),
        ("Network", [
            ("http_cache_hours", "Cache results for", "int", (0, 720, " h"), None),
            ("max_candidates_per_provider", "Results per source", "int", (1, 50, ""), None),
        ]),
    ],
    "Matching and size": [
        ("Choosing", [
            ("auto_apply_mode", "Auto-apply", "choice", C(("confident", "Confident results only"), ("never", "Never (always review)")), None),
            ("hamming_threshold", "Similarity tolerance", "int", (1, 30, " bits"), "How different two images may be and still count as the same artwork (of 64)."),
            ("conflict_min_sources", "Conflict at", "int", (2, 10, " sources"), "Other sources that must agree on a different cover to flag a conflict."),
        ]),
        ("Search limits (smaller results are hidden, not lost)", [
            ("min_front", "Front minimum", "int", (0, 5000, " px"), None),
            ("min_back", "Back minimum", "int", (0, 5000, " px"), None),
            ("min_disc", "Disc minimum", "int", (0, 5000, " px"), None),
            ("min_booklet", "Booklet minimum", "int", (0, 5000, " px"), None),
            ("min_artist", "Artist minimum", "int", (0, 5000, " px"), None),
            ("max_side", "Maximum", "int", (0, 30000, " px"), "0 = no maximum."),
            ("target_size", "Preferred size", "int", (100, 10000, " px"), None),
            ("prefer_largest", "Prefer the largest image instead", "bool", None, None),
            ("front_aspect_tolerance", "Square tolerance", "float", (0.0, 0.5, ""), "Front and disc art: 0.05 accepts ±5% from square."),
            ("max_file_mb", "Largest download", "int", (1, 200, " MB"), None),
        ]),
        ("Apply limits", [
            ("apply_min_side", "Never apply below", "int", (0, 5000, " px"), "Smaller art is not applied (and can trigger the creative fallback)."),
            ("embed_max_side", "Embedded max", "int", (0, 10000, " px"), "Larger images are scaled down before embedding. 0 = original."),
            ("file_max_side", "Saved file max", "int", (0, 30000, " px"), "0 = keep the original size."),
            ("upscale_to_minimum", "Upscale small images to the minimum (lower quality)", "bool", None, None),
        ]),
    ],
    "Output": [
        ("What to apply", [
            ("apply_types", "Default types", "multi", C(("front", "Front"), ("back", "Back"), ("disc", "Discs"), ("booklet", "Booklet"), ("artist", "Artist images")), None),
            ("embed", "Embed in tags", "bool", None, None),
            ("save_files", "Save as files", "bool", None, None),
            ("replace_embedded", "Replace existing embedded images of the same type", "bool", None, None),
            ("record_source_in_comment", "Record the source in the embedded image comment", "bool", None, None),
        ]),
        ("Where files go", [
            ("folder_mode", "Location", "choice", C(("subfolder", "Sub-folder of the album"), ("same", "The album folder")), None),
            ("folder_name", "Sub-folder name", "text", None, "covers (default), art, artwork, booklet, or your own name."),
            ("front_in_album_folder", "Also put the front cover in the album folder", "bool", None, "Players and media servers look for cover.jpg / folder.jpg there."),
            ("save_artist_art", "Save artist images in the artist folder", "bool", None, "The folder above the album (Album/CD1 layouts are recognised)."),
            ("multi_folder", "Albums in CD1/CD2 folders", "choice", C(("every", "Album art in every folder"), ("first", "Album art in the first only")), None),
            ("write_files_when", "Write files", "choice", C(("on_save", "When Picard saves"), ("immediately", "Immediately")), "“When Picard saves” follows renames and moves."),
        ]),
        ("File names", [
            ("naming_preset", "Preset", "choice", C(("default", "Default"), ("kodi", "Kodi / Jellyfin"), ("plex", "Plex"), ("custom", "Custom")), None),
            ("name_front", "Front", "text", None, None),
            ("name_back", "Back", "text", None, None),
            ("name_disc", "Disc", "text", None, None),
            ("name_booklet", "Booklet page", "text", None, "{discnumber} and {n} (page 01, 02…) are filled in."),
            ("name_artist_thumb", "Artist photo", "text", None, None),
            ("name_artist_logo", "Artist logo", "text", None, None),
            ("name_artist_background", "Artist background", "text", None, None),
            ("name_artist_banner", "Artist banner", "text", None, None),
        ]),
        ("Files", [
            ("file_format", "Format", "choice", C(("original", "Keep original"), ("jpeg", "JPEG"), ("png", "PNG")), None),
            ("jpeg_quality", "JPEG quality", "int", (50, 100, ""), None),
            ("collision_policy", "If a file exists", "choice", C(("if_better", "Replace if larger"), ("overwrite", "Replace"), ("skip", "Keep existing"), ("keep_both", "Keep both")), None),
            ("backups", "Back up replaced files so they can be undone", "bool", None, None),
            ("write_sidecar", "Write coverup.json (where each image came from)", "bool", None, None),
        ]),
    ],
    "Creative / AI": [
        ("When to generate", [
            ("creative_triggers", "Generate when", "multi", C(("no_cover", "No cover is found"), ("below_min", "Best cover is below the apply minimum"), ("low_confidence", "Only conflicting covers are found")), None),
            ("creative_always", "Always use generated art for the front cover", "bool", None, "Even when a real cover exists."),
        ]),
        ("How", [
            ("creative_method_order", "Try, in order", "order", C(("fanart,ai,template", "Fan art → AI → template"), ("ai,template", "AI → template"), ("fanart,template", "Fan art → template"), ("template", "Template only"), ("ai", "AI only"), ("fanart", "Fan art only")), None),
            ("creative_template", "Style", "template", None, None),
            ("creative_custom_prompt", "Custom prompt", "text", None, "Used with the Custom style. {artist} {album} {year} {genre} {era} are filled in."),
            ("creative_match_era", "Match the era of the release year", "bool", None, None),
            ("creative_match_genre", "Match the genre", "bool", None, None),
            ("creative_variations", "Variations", "int", (1, 8, ""), "How many images the dialog generates at once."),
            ("creative_max_per_run", "Max per auto-apply", "int", (0, 1000, ""), None),
        ]),
        ("Logo and title", [
            ("creative_overlay_logo", "Draw the band logo (or the artist name)", "bool", None, None),
            ("creative_overlay_title", "Draw the album title", "bool", None, None),
            ("creative_logo_position", "Position", "choice", C(("top", "Top"), ("center", "Centre"), ("bottom", "Bottom")), None),
        ]),
        ("AI backend", [
            ("ai_backend", "Backend", "choice", C(("none", "None (offline templates)"), ("automatic1111", "Local Stable Diffusion"), ("openai", "OpenAI-compatible API"), ("custom", "Custom HTTP endpoint")), "Local Stable Diffusion = AUTOMATIC1111 web UI started with --api."),
            ("ai_url", "Endpoint URL", "text", None, None),
            ("ai_model", "Model", "text", None, "Optional."),
            ("ai_api_key", "API key", "password", None, None),
            ("ai_size", "Image size", "int", (256, 2048, " px"), None),
            ("ai_steps", "Steps", "int", (1, 150, ""), "Stable Diffusion only."),
            ("ai_img2img", "Use the low-res cover as a reference (image-to-image)", "bool", None, None),
            ("ai_allow_remote_reference", "Allow sending that reference to remote services", "bool", None, None),
        ]),
    ],
    "Logging": [
        ("Log file", [
            ("log_mode", "Mode", "choice", C(("fixed", "Fixed size (rotating)"), ("total", "Capped total size"), ("age", "Keep for N days"), ("session", "One file per session"), ("off", "Off")), None),
            ("log_max_mb", "File size", "int", (1, 50, " MB"), None),
            ("log_backups", "Backups kept", "int", (0, 20, ""), None),
            ("log_total_cap_mb", "Total cap", "int", (1, 1000, " MB"), None),
            ("log_retain_days", "Keep for", "int", (1, 365, " days"), None),
            ("log_sessions_keep", "Sessions kept", "int", (1, 50, ""), None),
            ("log_level", "Detail", "choice", C(("ERROR", "Errors"), ("WARNING", "Warnings"), ("INFO", "Normal"), ("DEBUG", "Debug"), ("TRACE", "Trace")), None),
            ("log_anonymise", "Anonymise paths and album names (for sharing)", "bool", None, None),
            ("log_folder", "Folder", "text", None, "Leave empty for the default."),
        ]),
    ],
}

# which log fields matter in each mode
LOG_FIELDS = {
    "fixed": {"log_max_mb", "log_backups"},
    "total": {"log_max_mb", "log_total_cap_mb"},
    "age": {"log_max_mb", "log_retain_days"},
    "session": {"log_sessions_keep"},
    "off": set(),
}
NAME_KEYS = [k for k in NAMING_PRESETS["default"]]

HELP_STYLE = "color: palette(dark); font-size: 90%;"


def _help(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("coverupHelp")
    lab.setWordWrap(True)
    lab.setStyleSheet(HELP_STYLE)
    lab.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    lab.setMinimumWidth(200)
    return lab


def _make_options_page_class(base):
    class CoverUpOptionsPage(base):
        NAME = "coverup"
        TITLE = "CoverUp"
        PARENT = "plugins"
        # Picard's default page style makes every QLabel wrap, which clips form labels: opt out.
        STYLESHEET = ""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.widgets: dict[str, tuple[str, object]] = {}
            self.rows: dict[str, list[QWidget]] = {}
            outer = QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            tabs = QTabWidget()
            outer.addWidget(tabs)
            for tab, sections in LAYOUT.items():
                page = QWidget()
                col = QVBoxLayout(page)
                if tab == "Creative / AI":
                    col.addWidget(_help(
                        "Generated art is for your personal library: always labelled as generated, never uploaded. "
                        "Remote AI services receive the artist, album, year and genre, and ask for your consent first."
                    ))
                for title, fields in sections:
                    box = QGroupBox(title)
                    form = QFormLayout(box)
                    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
                    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
                    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    if tab == "Sources" and title == "Sources":
                        form.addRow(_help("Tick the sources to use. Drag to change the order."))
                        self.provider_list = QListWidget()
                        self.provider_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
                        self.provider_list.setMinimumHeight(200)
                        form.addRow(self.provider_list)
                    for key, label, kind, opt, help_text in fields:
                        self._add_field(form, key, label, kind, opt, help_text)
                    col.addWidget(box)
                if tab == "Creative / AI":
                    col.addLayout(self._buttons((("Open my templates folder", self._open_templates), ("Forget AI approvals", self._forget_ai))))
                if tab == "Logging":
                    col.addLayout(self._buttons((("Open log folder", self._open_logs), ("Export diagnostics…", self._export), ("Clear download cache", self._clear_cache))))
                col.addStretch(1)
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setFrameShape(QFrame.Shape.NoFrame)
                scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                scroll.setWidget(page)
                tabs.addTab(scroll, tab.replace("&", "&&"))
            self._custom_names = {k: str(DEFAULTS[k]) for k in NAME_KEYS}
            self.widgets["naming_preset"][1].currentIndexChanged.connect(self._preset_changed)
            self.widgets["folder_mode"][1].currentIndexChanged.connect(self._update_enabled)
            self.widgets["log_mode"][1].currentIndexChanged.connect(self._update_enabled)
            self.widgets["websearch_engine"][1].currentIndexChanged.connect(self._update_enabled)
            self.widgets["ai_backend"][1].currentIndexChanged.connect(self._update_enabled)

        # ---- building ----
        def _add_field(self, form: QFormLayout, key, label, kind, opt, help_text) -> None:
            w = self._widget(kind, opt)
            self.widgets[key] = (kind, w)
            row: list[QWidget] = [w]
            if kind == "bool":
                w.setText(label)
                form.addRow(w)
            else:
                lab = QLabel(label)
                form.addRow(lab, w)
                row.append(lab)
            if help_text:
                h = _help(help_text)
                form.addRow(h) if kind == "bool" else form.addRow("", h)
                row.append(h)
                w.setToolTip(help_text)
            self.rows[key] = row

        def _buttons(self, buttons) -> QHBoxLayout:
            row = QHBoxLayout()
            for text, fn in buttons:
                b = QPushButton(text)
                b.clicked.connect(fn)
                row.addWidget(b)
            row.addStretch(1)
            return row

        def _widget(self, kind, opt):
            if kind == "bool":
                return QCheckBox()
            if kind in ("int", "float"):
                w = QSpinBox() if kind == "int" else QDoubleSpinBox()
                lo, hi, suffix = opt
                w.setRange(lo, hi)
                if suffix:
                    w.setSuffix(suffix)
                if kind == "float":
                    w.setSingleStep(0.01)
                    w.setDecimals(2)
                w.setMaximumWidth(140)
                w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
                return w
            if kind in ("text", "password"):
                w = QLineEdit()
                if kind == "password":
                    w.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
                return w
            if kind in ("choice", "order", "template"):
                w = QComboBox()
                w.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
                if kind == "template":
                    from ..creative.template_engine import CUSTOM, load_templates
                    from ..glue import STATE

                    for name, t in sorted(load_templates(STATE.user_templates_dir()).items(), key=lambda kv: kv[1].title):
                        w.addItem(t.title, name)
                    w.addItem("Custom prompt", CUSTOM)
                else:
                    for value, label in opt:
                        w.addItem(label, value)
                return w
            if kind == "multi":
                box = QWidget()
                lay = QVBoxLayout(box)
                lay.setContentsMargins(0, 0, 0, 0)
                lay.setSpacing(2)
                box.checks = []
                for value, label in opt:
                    cb = QCheckBox(label)
                    cb.setProperty("value", value)
                    lay.addWidget(cb)
                    box.checks.append(cb)
                return box
            raise ValueError(kind)

        def _show(self, key: str, enabled: bool) -> None:
            for w in self.rows.get(key, []):
                w.setEnabled(enabled)

        def _preset_changed(self, *_):
            preset = self.widgets["naming_preset"][1].currentData()
            if getattr(self, "_last_preset", None) == "custom":
                self._custom_names = {k: self.widgets[k][1].text() for k in NAME_KEYS}
            self._last_preset = preset
            names = NAMING_PRESETS.get(preset) or self._custom_names
            for k in NAME_KEYS:
                # a preset's names are shown greyed out; Custom brings back the user's own names
                self.widgets[k][1].setText(names[k])
            self._update_enabled()

        def _update_enabled(self, *_):
            preset = self.widgets["naming_preset"][1].currentData()
            for k in NAME_KEYS:
                self._show(k, preset == "custom")
            self._show("folder_name", self.widgets["folder_mode"][1].currentData() == "subfolder")
            self._show("front_in_album_folder", self.widgets["folder_mode"][1].currentData() == "subfolder")
            mode = self.widgets["log_mode"][1].currentData()
            for k in ("log_max_mb", "log_backups", "log_total_cap_mb", "log_retain_days", "log_sessions_keep"):
                self._show(k, k in LOG_FIELDS.get(mode, set()))
            self._show("websearch_google_cx", self.widgets["websearch_engine"][1].currentData() == "google")
            ai_on = self.widgets["ai_backend"][1].currentData() != "none"
            for k in ("ai_url", "ai_model", "ai_api_key", "ai_size", "ai_steps", "ai_img2img", "ai_allow_remote_reference"):
                self._show(k, ai_on)

        # ---- config ----
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
            # remember the user's custom names so switching presets back and forth doesn't lose them
            self._custom_names = {k: str(self._get(k)) for k in NAME_KEYS}
            self._last_preset = None
            self._preset_changed()

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
            custom = self.widgets["naming_preset"][1].currentData() == "custom"
            for key, (kind, w) in self.widgets.items():
                if key in NAME_KEYS and not custom:
                    continue  # the fields only show the preset; keep the user's own names
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
        def _forget_ai(self):
            self._set("ai_consented_hosts", [])
            QMessageBox.information(self, "CoverUp", "AI services will ask for consent again.")

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
