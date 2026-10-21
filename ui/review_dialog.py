# -*- coding: utf-8 -*-
# CoverUp: MusicBrainz Picard plugin. GPL-2.0-or-later.
"""The review dialog: compare, choose and apply artwork for one album.

Layout (top to bottom):
  header      current cover, album, artist/year/discs, search status
  body        tabs (one per slot: Front, Back, Disc 1…n, Booklet, Artist, Create) | large preview
  set strip   the package being assembled: one tile per slot, each with an include box
  footer      where it goes (embed / save to), a plain summary, and "Apply N images"
"""

from __future__ import annotations

import logging
import threading
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices, QIcon, QImage, QKeySequence, QPainter, QPalette, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import glue, imaging
from ..apply.files import FOLDER_PRESETS, validate_folder_name
from ..creative.generate import ConsentRequired, CreativeOptions, generate, resolve_template
from ..creative.template_engine import CUSTOM, load_templates
from ..model import ArtType, Candidate, Tier
from ..pipeline import AlbumResult, PlanItem
from ..searchlinks import links, search_terms, store_links, unwrap_image_url
from ..settings import ARTIST_TYPES, EMBED_CHOICES
from .crop_dialog import CropDialog
from .widgets import SOURCE_NAMES, CandidateGrid, Preview, image_of, run_in_background

log = logging.getLogger("coverup.ui")

ALBUM_FOLDER = "__album__"
OTHER_FOLDER = "__other__"
NO_FILES = "__none__"
TILE = 64


@dataclass
class Slot:
    key: str
    title: str
    group: str  # front | back | disc | booklet | artist (matches the "apply types" setting)
    art_type: ArtType
    disc: int | None = None
    multi: bool = False
    grid: CandidateGrid | None = None
    stack: QStackedWidget | None = None
    empty: QLabel | None = None
    tile: QToolButton | None = None
    include: QCheckBox | None = None
    chosen: list[Candidate] = field(default_factory=list)


EMPTY_TEXT = {
    "front": "No front cover was found. Add one from a file or a web address, or make one in the Create tab.",
    "back": "No back cover was found. Add a scan from a file or a web address.",
    "disc": "No art was found for this disc. Add a scan from a file or a web address.",
    "booklet": "No booklet pages were found. Add scans from files or web addresses.",
    "artist": "No artist images were found. Photos come from Wikimedia Commons, Deezer, Discogs, Fanart.tv and TheAudioDB; "
    "logos, backgrounds and banners from Fanart.tv (free key) and TheAudioDB. See Options > CoverUp > Artists.",
}
ARTIST_OFF_TEXT = "Artist images are switched off. Turn them on under Options > CoverUp > Artists."


def _h(text: str, scale: float = 1.0, bold: bool = False) -> QLabel:
    lab = QLabel(text)
    f = lab.font()
    if scale != 1.0:
        f.setPointSizeF(f.pointSizeF() * scale)
    f.setBold(bold)
    lab.setFont(f)
    return lab


def _muted(text: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setForegroundRole(QPalette.ColorRole.PlaceholderText)
    return lab


class ReviewDialog(QDialog):
    def __init__(self, target, parent=None, state=None):
        super().__init__(parent)
        self.state = state or glue.STATE
        self.target = target
        self.s = self.state.settings()
        self.cancel = threading.Event()
        self.pipeline = self.state.pipeline(self.cancel)
        self.query = glue.query_from(target)
        self.result: AlbumResult | None = None
        self.current = glue.existing_front(target)
        self.slots: list[Slot] = []
        self.generated: list[Candidate] = []
        self._busy_applying = False
        self.setWindowTitle(f"CoverUp: {self.query.album or 'Album'}")
        self.resize(1180, 820)
        self._build()
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._apply)
        self._start_search()

    # ===================================================================================== layout
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.addLayout(self._build_header())

        body = QHBoxLayout()
        left = QVBoxLayout()
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(self._tab_changed)
        left.addWidget(self.tabs, 1)
        tools = QHBoxLayout()
        self.show_rejected = QCheckBox("Show images below the minimum size")
        self.show_rejected.toggled.connect(lambda _on: self._refresh_all())
        tools.addWidget(self.show_rejected)
        tools.addStretch(1)
        self.search_btn = QPushButton("Search the web")
        self.search_btn.setMenu(self._build_search_menu())
        self.search_btn.setToolTip(
            "Opens an image search in your browser, built from this album's tags.\n"
            "Open the picture full size, then copy it (or drag it) into this window."
        )
        self.paste_btn = QPushButton("Paste image")
        self.paste_btn.setToolTip("Adds a copied image, image address or file to the current tab (Ctrl+V)")
        self.paste_btn.clicked.connect(self._paste)
        self.add_file_btn = QPushButton("Add from file…")
        self.add_file_btn.clicked.connect(self._add_file)
        self.add_url_btn = QPushButton("Add from web address…")
        self.add_url_btn.clicked.connect(self._add_url)
        self.clear_btn = QPushButton("Choose nothing here")
        self.clear_btn.clicked.connect(self._clear_choice)
        self.rotate_left_btn = QPushButton("Rotate left")
        self.rotate_left_btn.clicked.connect(lambda: self._rotate(-90))
        self.rotate_right_btn = QPushButton("Rotate right")
        self.rotate_right_btn.clicked.connect(lambda: self._rotate(90))
        self.crop_btn = QPushButton("Crop…")
        self.crop_btn.clicked.connect(self._crop)
        for b in (self.rotate_left_btn, self.rotate_right_btn, self.crop_btn):
            b.setToolTip("Makes an edited copy of the selected picture (the original stays in the list). Edited pictures are saved as JPEG.")
        for b in (self.search_btn, self.paste_btn, self.add_file_btn, self.add_url_btn, self.rotate_left_btn, self.rotate_right_btn, self.crop_btn, self.clear_btn):
            tools.addWidget(b)
        paste = QShortcut(QKeySequence(QKeySequence.StandardKey.Paste), self.tabs)
        paste.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        paste.activated.connect(self._paste)
        self.setAcceptDrops(True)
        left.addLayout(tools)
        body.addLayout(left, 1)
        self.preview = Preview()
        self.preview.current = self.current
        body.addWidget(self.preview)
        root.addLayout(body, 1)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(line)
        root.addLayout(self._build_set_strip())
        root.addLayout(self._build_footer())

        self.creative_page = self._build_creative()
        self._set_busy(True)

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.cover = QLabel()
        self.cover.setFixedSize(72, 72)
        self.cover.setPixmap(self._tile_pixmap(self.current, 72, "No cover"))
        row.addWidget(self.cover)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(_h(self.query.album or "Untitled album", 1.35, True))
        bits = [self.query.artist or "Unknown artist"]
        if self.query.year:
            bits.append(str(self.query.year))
        if (self.query.medium_count or 1) > 1:
            bits.append(f"{self.query.medium_count} discs")
        if self.current is not None and self.current.width:
            bits.append(f"current cover {self.current.width} × {self.current.height}")
        text.addWidget(QLabel(", ".join(bits)))
        self.status = _muted("Searching the enabled sources…")
        text.addWidget(self.status)
        row.addLayout(text, 1)
        self.stop_btn = QPushButton("Stop searching")
        self.stop_btn.clicked.connect(self.cancel.set)
        row.addWidget(self.stop_btn, 0, Qt.AlignmentFlag.AlignTop)
        return row

    def _build_set_strip(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(4)
        head = QHBoxLayout()
        head.addWidget(_h("Your set", 1.0, True))
        head.addWidget(_muted("Tick what to apply. Click a picture to change it."), 1)
        box.addLayout(head)
        self.strip = QHBoxLayout()
        self.strip.setSpacing(14)
        self.strip.addStretch(1)
        box.addLayout(self.strip)
        return box

    def _build_footer(self) -> QVBoxLayout:
        col = QVBoxLayout()
        dest = QHBoxLayout()
        form_l = QFormLayout()
        self.embed_combo = QComboBox()
        for types, label in EMBED_CHOICES:
            self.embed_combo.addItem(label, types)
        current_embed = list(self.s["embed_types"] or []) if self.s["embed"] else []
        idx = next((i for i, (t, _l) in enumerate(EMBED_CHOICES) if t == current_embed), 0)
        self.embed_combo.setCurrentIndex(idx)
        self.embed_combo.currentIndexChanged.connect(self._update_summary)
        form_l.addRow("Embed in tags:", self.embed_combo)
        dest.addLayout(form_l)
        dest.addSpacing(24)
        form_r = QFormLayout()
        files_row = QHBoxLayout()
        self.folder_combo = QComboBox()
        for name in FOLDER_PRESETS:
            self.folder_combo.addItem(f"{name}/ folder", name)
        self.folder_combo.addItem("The album folder", ALBUM_FOLDER)
        self.folder_combo.addItem("Another folder…", OTHER_FOLDER)
        self.folder_combo.addItem("Don't save files", NO_FILES)
        self.custom_folder = QLineEdit()
        self.custom_folder.setPlaceholderText("folder name")
        self.custom_folder.setMaximumWidth(160)
        if not self.s["save_files"]:
            self.folder_combo.setCurrentIndex(self.folder_combo.findData(NO_FILES))
        elif self.s["folder_mode"] == "same":
            self.folder_combo.setCurrentIndex(self.folder_combo.findData(ALBUM_FOLDER))
        elif self.s["folder_name"] in FOLDER_PRESETS:
            self.folder_combo.setCurrentIndex(self.folder_combo.findData(self.s["folder_name"]))
        else:
            self.folder_combo.setCurrentIndex(self.folder_combo.findData(OTHER_FOLDER))
            self.custom_folder.setText(self.s["folder_name"])
        self.folder_combo.currentIndexChanged.connect(self._folder_changed)
        self.custom_folder.textChanged.connect(self._update_summary)
        files_row.addWidget(self.folder_combo)
        files_row.addWidget(self.custom_folder)
        form_r.addRow("Save files to:", files_row)
        dest.addLayout(form_r)
        dest.addSpacing(24)
        self.write_now = QCheckBox("Write files now, not when I save")
        self.write_now.setChecked(self.s["write_files_when"] == "immediately")
        self.write_now.toggled.connect(self._update_summary)
        dest.addWidget(self.write_now)
        dest.addStretch(1)
        col.addLayout(dest)

        bottom = QHBoxLayout()
        self.summary = _muted("")
        bottom.addWidget(self.summary, 1)
        self.warning = QLabel("")
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color: #9a5b00;")
        embeds, only_one = glue.picard_embeds_images()
        if not embeds:
            self.warning.setText("Picard is set not to embed cover images (Options > Cover Art), so nothing will be embedded.")
        elif only_one:
            self.warning.setText("Picard embeds only one front image (Options > Cover Art), so only the front will be embedded.")
        self.warning.setVisible(bool(self.warning.text()))
        bottom.addWidget(self.warning, 1)
        close = QPushButton("Cancel")
        close.clicked.connect(self.reject)
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setDefault(True)
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._apply)
        bottom.addWidget(close)
        bottom.addWidget(self.apply_btn)
        col.addLayout(bottom)
        self._folder_changed()
        return col

    def _build_creative(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        intro = _muted(
            "Make your own front cover. The band logo (or name) and the album title are drawn by CoverUp so the "
            "lettering is always correct. Created covers are labelled as generated and never uploaded."
        )
        lay.addWidget(intro)
        self.creative_reason = QLabel("")
        self.creative_reason.setWordWrap(True)
        self.creative_reason.setVisible(False)
        lay.addWidget(self.creative_reason)
        form = QFormLayout()
        self.template_combo = QComboBox()
        self.templates = load_templates(self.state.user_templates_dir())
        for name, t in sorted(self.templates.items(), key=lambda kv: kv[1].title):
            self.template_combo.addItem(t.title, name)
        self.template_combo.addItem("Custom prompt (set in Options)", CUSTOM)
        self.template_combo.setCurrentIndex(max(0, self.template_combo.findData(self.s["creative_template"])))
        form.addRow("Style:", self.template_combo)
        self.method_combo = QComboBox()
        self.method_combo.addItem("Built-in renderer (works offline)", "template")
        if self.s["ai_backend"] != "none":
            self.method_combo.addItem(f"AI image service ({self.s['ai_backend']})", "ai")
            self.method_combo.setCurrentIndex(1)
        form.addRow("Made with:", self.method_combo)
        self.logo_combo = QComboBox()
        self.logo_combo.addItem("Artist name as lettering", None)
        form.addRow("Band logo:", self.logo_combo)
        opts = QHBoxLayout()
        self.logo_cb = QCheckBox("Show logo or name")
        self.logo_cb.setChecked(bool(self.s["creative_overlay_logo"]))
        self.title_cb = QCheckBox("Show album title")
        self.title_cb.setChecked(bool(self.s["creative_overlay_title"]))
        self.pos_combo = QComboBox()
        for v, label in (("top", "Logo at top"), ("center", "Logo in centre"), ("bottom", "Logo at bottom")):
            self.pos_combo.addItem(label, v)
        self.pos_combo.setCurrentIndex(max(0, self.pos_combo.findData(self.s["creative_logo_position"])))
        for x in (self.logo_cb, self.title_cb, self.pos_combo):
            opts.addWidget(x)
        opts.addStretch(1)
        form.addRow("Lettering:", opts)
        gen_row = QHBoxLayout()
        self.var_spin = QSpinBox()
        self.var_spin.setRange(1, 8)
        self.var_spin.setValue(int(self.s["creative_variations"]))
        self.var_spin.setSuffix(" versions")
        self.ref_cb = QCheckBox("Base it on the current cover (AI only)")
        self.ref_cb.setChecked(bool(self.s["ai_img2img"]))
        self.gen_btn = QPushButton("Create")
        self.gen_btn.clicked.connect(self._generate)
        gen_row.addWidget(self.var_spin)
        gen_row.addWidget(self.ref_cb)
        gen_row.addStretch(1)
        gen_row.addWidget(self.gen_btn)
        form.addRow("", gen_row)
        lay.addLayout(form)
        self.creative_grid = CandidateGrid()
        self.creative_grid.itemSelectionChanged.connect(lambda: self.preview.show_candidate((self.creative_grid.selected() or [None])[0]))
        lay.addWidget(self.creative_grid, 1)
        use_row = QHBoxLayout()
        use_row.addStretch(1)
        self.use_btn = QPushButton("Use as front cover")
        self.use_btn.setEnabled(False)
        self.use_btn.clicked.connect(self._use_generated)
        self.creative_grid.itemSelectionChanged.connect(lambda: self.use_btn.setEnabled(bool(self.creative_grid.selected())))
        use_row.addWidget(self.use_btn)
        lay.addLayout(use_row)
        return w

    # ===================================================================================== slots
    def _make_slots(self) -> None:
        res = self.result
        n = max(1, len(res.discs) if res else 1)
        defs = [Slot("front", "Front", "front", ArtType.FRONT), Slot("back", "Back", "back", ArtType.BACK)]
        for d in range(1, n + 1):
            defs.append(Slot(f"disc{d}", "Disc" if n == 1 else f"Disc {d}", "disc", ArtType.DISC, disc=d))
        defs += [Slot("booklet", "Booklet", "booklet", ArtType.BOOKLET, multi=True), Slot("artist", "Artist", "artist", ArtType.ARTIST_THUMB, multi=True)]
        default_groups = set(self.s["apply_types"] or [])
        for slot in defs:
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.setContentsMargins(0, 6, 0, 0)
            slot.grid = CandidateGrid(multi=slot.multi)
            slot.grid.itemSelectionChanged.connect(lambda s=slot: self._grid_changed(s))
            slot.grid.itemDoubleClicked.connect(lambda item, s=slot: self._apply_now(s, item.data(Qt.ItemDataRole.UserRole)))
            slot.grid.currentItemChanged.connect(lambda cur, _prev: self.preview.show_candidate(cur.data(Qt.ItemDataRole.UserRole) if cur else None))
            slot.empty = _muted(EMPTY_TEXT[slot.group] if slot.group != "artist" or self.s["artist_art"] else ARTIST_OFF_TEXT)
            slot.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            slot.stack = QStackedWidget()
            slot.stack.addWidget(slot.grid)
            slot.stack.addWidget(slot.empty)
            lay.addWidget(slot.stack)
            hint = "Click a picture to choose it; double-click to apply it straight away."
            if slot.multi:
                hint = "Select every image you want (click again to remove one); double-click one to apply just that image now."
            lay.addWidget(_muted(hint))
            self.tabs.addTab(page, slot.title)
            tile_col = QVBoxLayout()
            tile_col.setSpacing(2)
            slot.tile = QToolButton()
            slot.tile.setIconSize(QSize(TILE, TILE))
            slot.tile.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            slot.tile.setAutoRaise(True)
            slot.tile.clicked.connect(lambda _c=False, s=slot: self.tabs.setCurrentIndex(self.slots.index(s)))
            slot.include = QCheckBox(slot.title)
            slot.include.setChecked(slot.group in default_groups)
            slot.include.toggled.connect(self._update_summary)
            tile_col.addWidget(slot.tile, 0, Qt.AlignmentFlag.AlignHCenter)
            tile_col.addWidget(slot.include, 0, Qt.AlignmentFlag.AlignHCenter)
            self.strip.insertLayout(self.strip.count() - 1, tile_col)
            self.slots.append(slot)
        self.tabs.addTab(self.creative_page, "Create")

    def _with_local(self, pool: list[Candidate]) -> list[Candidate]:
        """Every image found in the album folder is offered for front, back and disc: file names say little."""
        have = {id(c) for c in pool}
        return pool + [c for c in (self.result.candidates if self.result else []) if c.provider == "local" and id(c) not in have]

    def _pool(self, slot: Slot) -> list[Candidate]:
        res = self.result
        if res is None:
            return []
        if slot.group == "front":
            return self._with_local(res.of_type(ArtType.FRONT) + [c for c in self.generated if c in slot.chosen])
        if slot.group == "back":
            return self._with_local(res.of_type(ArtType.BACK, include_unlabelled=True))
        if slot.group == "disc":
            n = len(res.discs)
            return self._with_local([c for c in res.of_type(ArtType.DISC) if n == 1 or c.disc_number in (slot.disc, None)] + res.of_type(ArtType.OTHER))
        if slot.group == "booklet":
            return res.of_type(ArtType.BOOKLET, include_unlabelled=True)
        return [c for c in res.candidates if c.art_type in ARTIST_TYPES]

    def _pick(self, slot: Slot) -> Candidate | None:
        res = self.result
        if res is None:
            return None
        if slot.group in ("front", "back"):
            sel = res.selections.get(ArtType.FRONT if slot.group == "front" else ArtType.BACK)
            return sel.winner if sel else None
        if slot.group == "disc":
            sel = res.discs.get(slot.disc or 1)
            return sel.winner if sel else None
        return None

    def _preselect(self) -> None:
        res = self.result
        for slot in self.slots:
            if slot.group in ("front", "back", "disc"):
                pick = self._pick(slot)
                slot.chosen = [pick] if pick is not None and pick.provider != "embedded" else []
            elif slot.group == "booklet":
                slot.chosen = list(res.booklet)
            else:
                kinds = self.s.artist_art_types()
                slot.chosen = [c for art, c in res.artist.items() if c and art in kinds]

    def _refresh_slot(self, slot: Slot) -> None:
        pool = self._pool(slot)
        slot.grid.set_candidates(pool, self.show_rejected.isChecked(), slot.chosen, self._pick(slot))
        slot.stack.setCurrentIndex(0 if slot.grid.count() else 1)
        eligible = len([c for c in pool if not c.rejected_reason])
        idx = self.slots.index(slot)
        self.tabs.setTabText(idx, f"{slot.title} ({eligible})" if eligible else slot.title)
        self._refresh_tile(slot)

    def _refresh_all(self) -> None:
        for slot in self.slots:
            self._refresh_slot(slot)
        self._update_summary()

    def _tile_pixmap(self, c: Candidate | None, size: int, empty_text: str, count: int = 0) -> QPixmap:
        pm = QPixmap(size, size)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        img = image_of(c)
        pal = self.palette()
        if img is not None:
            scaled = img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            p.drawImage(int((size - scaled.width()) / 2), int((size - scaled.height()) / 2), scaled)
            if count > 1:
                p.fillRect(size - 24, size - 18, 24, 18, QColor(0, 0, 0, 170))
                p.setPen(QColor("white"))
                p.drawText(size - 24, size - 18, 24, 18, Qt.AlignmentFlag.AlignCenter, str(count))
        else:
            p.setPen(pal.color(QPalette.ColorRole.PlaceholderText))
            p.drawRect(0, 0, size - 1, size - 1)
            p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, empty_text)
        p.end()
        return pm

    def _refresh_tile(self, slot: Slot) -> None:
        first = slot.chosen[0] if slot.chosen else None
        slot.tile.setIcon(QIcon(self._tile_pixmap(first, TILE, "none", len(slot.chosen))))
        if slot.chosen:
            if len(slot.chosen) > 1:
                what = f"{len(slot.chosen)} images"
            else:
                what = f"{first.width} × {first.height}" if first.width else "chosen"
            slot.tile.setToolTip(f"{slot.title}: {what}")
        else:
            slot.tile.setToolTip(f"{slot.title}: nothing chosen")
        slot.include.setEnabled(bool(slot.chosen))

    # ===================================================================================== search
    def _set_busy(self, busy: bool) -> None:
        self.stop_btn.setVisible(busy)
        for w in (self.add_file_btn, self.add_url_btn, self.clear_btn, self.show_rejected):
            w.setEnabled(not busy)

    def _start_search(self) -> None:
        run_in_background(lambda: self.pipeline.run(self.query), self._search_done)

    def _search_done(self, result, error) -> None:
        self._set_busy(False)
        if error is not None or result is None:
            self.status.setText(f"The search failed ({error}). Details are in the CoverUp log.")
            return
        self.result = result
        self._make_slots()
        self._preselect()
        self._fill_logos()
        self._refresh_all()
        self.status.setText(self._status_text(result))
        go, why = result.creative.get(ArtType.FRONT, (False, ""))
        if go and why:
            self.creative_reason.setText(f"Suggested because: {why[0].lower() + why[1:]}.")
            self.creative_reason.setVisible(True)
        self.tabs.setCurrentIndex(0)
        self._tab_changed(0)
        self._update_summary()

    def _status_text(self, res: AlbumResult) -> str:
        front = res.selections.get(ArtType.FRONT)
        if res.cancelled:
            head = "Search stopped early."
        elif not front or not front.winner:
            head = "No front cover found."
        elif front.conflict:
            head = "Sources disagree about the front cover: check the pick before applying."
        elif front.winner.tier == Tier.A:
            head = "Found the front cover of this exact release."
        elif front.winner.tier == Tier.B:
            head = "Found the album's front cover (it may be from another edition)."
        else:
            agree = len(front.clusters[0].providers) if front.clusters else 1
            head = f"Front cover chosen because {agree} sources show the same picture."
        failed = sorted(SOURCE_NAMES.get(k, k) for k, v in res.provider_status.items() if v.startswith("error"))
        skipped = sorted(SOURCE_NAMES.get(k, k) for k, v in res.provider_status.items() if v.startswith("skipped"))
        tail = []
        if failed:
            tail.append(f"Not reachable: {', '.join(failed)}")
        if skipped:
            tail.append(f"Skipped (add a key in Options > CoverUp > Sources): {', '.join(skipped)}")
        return head + ("  " + ". ".join(tail) + "." if tail else "")

    def _fill_logos(self) -> None:
        res = self.result
        for logo in res.logos:
            src = "Fanart.tv" if logo.provider == "fanart" else "TheAudioDB"
            self.logo_combo.addItem(f"Logo from {src}" + (f" ({logo.likes} likes)" if logo.likes else ""), logo)
        remembered = self.s.logo_choice(self.query.artist_mbid)
        for i in range(1, self.logo_combo.count()):
            if self.logo_combo.itemData(i).url == remembered:
                self.logo_combo.setCurrentIndex(i)
                return
        if res.logos:
            self.logo_combo.setCurrentIndex(1)

    # ===================================================================================== events
    def _current_slot(self) -> Slot | None:
        idx = self.tabs.currentIndex()
        return self.slots[idx] if 0 <= idx < len(self.slots) else None

    def _tab_changed(self, _idx: int) -> None:
        slot = self._current_slot()
        for b in (self.search_btn, self.paste_btn, self.add_file_btn, self.add_url_btn, self.rotate_left_btn, self.rotate_right_btn, self.crop_btn, self.clear_btn, self.show_rejected):
            b.setVisible(slot is not None)
        if slot is None:
            sel = self.creative_grid.selected()
            self.preview.show_candidate(sel[0] if sel else None)
        else:
            self.preview.show_candidate(slot.chosen[0] if slot.chosen else None)

    def _grid_changed(self, slot: Slot) -> None:
        picked = slot.grid.selected()
        before = bool(slot.chosen)
        slot.chosen = picked
        if picked and not before:
            slot.include.setChecked(True)
        self._refresh_tile(slot)
        self._update_summary()

    def _clear_choice(self) -> None:
        slot = self._current_slot()
        if slot is None:
            return
        slot.grid.clearSelection()
        slot.chosen = []
        slot.include.setChecked(False)
        self._refresh_tile(slot)
        self.preview.show_candidate(None)
        self._update_summary()

    def _folder_changed(self, *_a) -> None:
        data = self.folder_combo.currentData()
        self.custom_folder.setVisible(data == OTHER_FOLDER)
        self.write_now.setEnabled(data != NO_FILES)
        self._update_summary()

    # ===================================================================================== summary
    def chosen_items(self) -> list[PlanItem]:
        items: list[PlanItem] = []
        for slot in self.slots:
            if not slot.include.isChecked() or not slot.chosen:
                continue
            if slot.group == "booklet":
                pages = sorted(slot.chosen, key=lambda c: (c.provider, c.page))
                items += [PlanItem(ArtType.BOOKLET, c, page=i + 1) for i, c in enumerate(pages)]
            elif slot.group == "artist":
                items += [PlanItem(c.art_type, c) for c in slot.chosen]
            elif slot.group == "disc":
                items.append(PlanItem(ArtType.DISC, slot.chosen[0], disc_number=slot.disc))
            else:
                items.append(PlanItem(slot.art_type, slot.chosen[0]))
        return items

    def _destination(self) -> dict:
        data = self.folder_combo.currentData()
        out = {
            "embed_types": list(self.embed_combo.currentData() or []),
            "embed": bool(self.embed_combo.currentData()),
            "write_files_when": "immediately" if self.write_now.isChecked() else "on_save",
            "save_files": data != NO_FILES,
        }
        if data == ALBUM_FOLDER:
            out["folder_mode"] = "same"
        elif data == OTHER_FOLDER:
            out.update({"folder_mode": "subfolder", "folder_name": validate_folder_name(self.custom_folder.text().strip())})
        elif data != NO_FILES:
            out.update({"folder_mode": "subfolder", "folder_name": data})
        return out

    def _update_summary(self, *_a) -> None:
        items = self.chosen_items()
        n = len(items)
        self.apply_btn.setText(f"Apply {n} image{'s' if n != 1 else ''}" if n else "Apply")
        if self.result is None:
            return
        self.apply_btn.setEnabled(n > 0)
        if not n:
            self.summary.setText("Nothing is ticked in your set yet.")
            return
        try:
            dest = self._destination()
        except ValueError:
            self.summary.setText("Type a valid folder name (no slashes or special characters).")
            self.apply_btn.setEnabled(False)
            return
        embed_types = self.s.with_(**dest).embed_art_types()
        embedded = sorted({it.art_type.value for it in items if it.art_type in embed_types}, key=["front", "back", "disc", "booklet"].index)
        parts = []
        if embedded and dest["embed"]:
            size = int(self.s["embed_max_side"] or 0)
            noun = "image" if len(embedded) == 1 else "images"
            parts.append(f"Embeds the {' and '.join(embedded)} {noun} in the tags" + (f" (up to {size} px)" if size else "") + ".")
        if dest["save_files"]:
            where = "the album folder" if dest.get("folder_mode") == "same" else f"{dest['folder_name']}/"
            when = "now" if dest["write_files_when"] == "immediately" else "when you save the album in Picard"
            beside = dest.get("folder_mode") != "same" and self.s["front_in_album_folder"] and any(it.art_type == ArtType.FRONT for it in items)
            extra = ", plus the front cover beside the tracks," if beside else ""
            artist = " Artist images go to the artist folder." if any(it.art_type in ARTIST_TYPES for it in items) else ""
            parts.append(f"Saves {n} file{'s' if n != 1 else ''} to {where}{extra} {when}.{artist}")
        if not parts:
            parts.append("Nothing will be embedded or saved: choose where the images go.")
            self.apply_btn.setEnabled(False)
        self.summary.setText(" ".join(parts))

    # ===================================================================================== adding
    def _manual(self, data: bytes, url: str, label: str) -> Candidate | None:
        slot = self._current_slot()
        if slot is None:
            return None
        if not imaging.is_valid_image(data):
            QMessageBox.warning(self, "CoverUp", "That file is not an image CoverUp can read (JPEG, PNG, TIFF, WebP, GIF or BMP).")
            return None
        width, height = imaging.dimensions(data) or (0, 0)
        art = slot.art_type
        c = Candidate("manual", url or label, url, art, Tier.A, width=width, height=height, dims_known=True,
                      bytes=len(data), thumb_data=data, data=data, comment=label)
        fp = imaging.fingerprint(data)
        if fp:
            c.phash, c.blank = fp.phash, fp.blank
        if art == ArtType.DISC:
            c.disc_number = slot.disc
        if self.result is not None:
            self.result.candidates.append(c)
        slot.grid.add_candidate(c)
        slot.stack.setCurrentIndex(0)
        log.info("Image added by the user for %s: %s (%dx%d)", slot.key, label, c.width, c.height)
        return c

    # ---- edit: rotate and crop make a new JPEG copy in the current tab ----
    def _edit_source(self) -> Candidate | None:
        slot = self._current_slot()
        if slot is None:
            return None
        picked = slot.grid.selected() or ([self.preview.current] if self.preview.current is not None else [])
        if not picked:
            QMessageBox.information(self, "CoverUp", "Click a picture first, then rotate or crop it.")
            return None
        return picked[0]

    def _with_full_image(self, c: Candidate, then) -> None:
        """Run ``then(data)`` with the full-size bytes, downloading them first when only a thumbnail is held."""
        if c.data is not None:
            then(c.data)
            return
        self.status.setText("Downloading the full-size image…")

        def work():
            return self.pipeline.fetch_full(c)

        def done(data, error):
            if error is not None:
                self.status.setText(f"Could not download the image to edit it ({error}).")
                return
            self.status.setText("")
            then(data)

        run_in_background(work, done)

    def _add_edit(self, src: Candidate, data: bytes, how: str) -> None:
        c = self._manual(data, "", f"{src.comment or src.provider} ({how})")
        if c is not None:
            c.extra["edited_from"] = src.provider

    def _rotate(self, degrees: int) -> None:
        src = self._edit_source()
        if src is None:
            return
        how = "rotated left" if degrees < 0 else "rotated right"
        self._with_full_image(src, lambda data: self._add_edit(src, imaging.rotate(data, degrees, int(self.s["jpeg_quality"])), how))

    def _crop(self) -> None:
        src = self._edit_source()
        if src is None:
            return

        def go(data: bytes) -> None:
            dlg = CropDialog(data, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            r = dlg.rect()
            self._add_edit(src, imaging.crop(data, r.x(), r.y(), r.width(), r.height(), int(self.s["jpeg_quality"])), "cropped")

        self._with_full_image(src, go)

    def _add_file(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add images", str(Path.home()), "Images (*.jpg *.jpeg *.png *.tif *.tiff *.webp *.gif *.bmp)")
        for path in paths:
            try:
                self._manual(Path(path).read_bytes(), "", Path(path).name)
            except OSError as exc:
                QMessageBox.warning(self, "CoverUp", f"Could not read {Path(path).name}: {exc}")

    def _add_url(self) -> None:
        url, ok = QInputDialog.getText(self, "Add from web address", "Image address (https://…):")
        url = url.strip()
        if not ok or not url:
            return
        if not url.startswith(("http://", "https://")):
            QMessageBox.warning(self, "CoverUp", "The address must start with http:// or https://.")
            return
        self._download(url)

    def _download(self, url: str) -> None:
        url = unwrap_image_url(url)
        http = self.pipeline.http

        def done(data, err):
            if err:
                QMessageBox.warning(self, "CoverUp", f"Could not download the image: {err}")
            elif not imaging.is_valid_image(data):
                QMessageBox.warning(
                    self, "CoverUp",
                    "That address is a web page, not an image. In the browser, open the picture full size and "
                    "copy the image itself (right-click > Copy image), then paste it here.",
                )
            else:
                self._manual(data, url, url)

        run_in_background(lambda: http.get(url, cache=False).data, done)

    # ---- web search (in the user's browser) and bringing pictures back ------------------------
    def _build_search_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        # rebuilt each time it opens: the search fills in label, catalogue number and Discogs id
        menu.aboutToShow.connect(lambda: self._fill_search_menu(menu))
        self._fill_search_menu(menu)
        return menu

    def _fill_search_menu(self, menu: QMenu) -> None:
        menu.clear()
        for label, url in links(self.query):
            act = menu.addAction(label)
            act.setToolTip(url)
            act.triggered.connect(lambda _checked=False, u=url: self._open_search(u))
        shops = menu.addMenu("Shops and streaming")
        shops.setToolTipsVisible(True)
        for label, url in store_links(self.query):
            act = shops.addAction(label)
            act.setToolTip(url)
            act.triggered.connect(lambda _checked=False, u=url: self._open_search(u))
        menu.addSeparator()
        menu.addAction("Edit the search words…").triggered.connect(self._edit_search)

    def _open_search(self, url: str) -> None:
        log.info("Opening web search: %s", url)
        QDesktopServices.openUrl(QUrl(url))
        self.status.setText(
            "Search opened in your browser. Open a picture full size, then copy it (right-click > Copy image) "
            "and press Ctrl+V here, or drag it onto this window."
        )

    def _edit_search(self) -> None:
        text, ok = QInputDialog.getText(self, "Search the web", "Search Google Images (large) for:", text=search_terms(self.query, precise=True))
        if ok and text.strip():
            self._open_search("https://www.google.com/search?tbm=isch&tbs=isz:l&q=" + urllib.parse.quote_plus(text.strip()))

    def _paste(self) -> None:
        mime = QApplication.clipboard().mimeData()
        if not self._import_mime(mime):
            QMessageBox.information(self, "CoverUp", "The clipboard has no image, image address or image file to add.")

    def _import_mime(self, mime) -> bool:
        """Add an image from clipboard or drag-and-drop data. Returns False if there was nothing usable."""
        if mime is None:
            return False
        if mime.hasUrls():
            used = False
            for u in mime.urls():
                if u.isLocalFile():
                    try:
                        self._manual(Path(u.toLocalFile()).read_bytes(), "", Path(u.toLocalFile()).name)
                        used = True
                    except OSError:
                        continue
                elif u.scheme() in ("http", "https"):
                    self._download(u.toString())
                    used = True
            if used:
                return True
        if mime.hasImage():
            img = mime.imageData()
            if isinstance(img, QImage) and not img.isNull():
                self._manual(imaging.encode(img, "png"), "", "pasted image")
                return True
        if mime.hasText():
            text = mime.text().strip()
            if text.startswith(("http://", "https://")):
                self._download(text.split()[0])
                return True
            if text.startswith("file://") or Path(text).is_file():
                path = QUrl(text).toLocalFile() if text.startswith("file://") else text
                try:
                    self._manual(Path(path).read_bytes(), "", Path(path).name)
                    return True
                except OSError:
                    return False
        return False

    def dragEnterEvent(self, event) -> None:
        m = event.mimeData()
        if m.hasImage() or m.hasUrls() or m.hasText():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        if self._import_mime(event.mimeData()):
            event.acceptProposedAction()

    # ===================================================================================== create
    def _generate(self) -> None:
        tname = self.template_combo.currentData()
        s = self.s
        template = resolve_template(s.with_(creative_template=tname), [self.state.user_templates_dir()])
        logo = self.logo_combo.currentData()
        ref = None
        if self.ref_cb.isChecked():
            front = self.slots[0].chosen if self.slots else []
            ref_c = front[0] if front else self.current
            ref = (ref_c.data or ref_c.thumb_data) if ref_c else None
        opts = CreativeOptions(
            method=self.method_combo.currentData(), template=template, count=self.var_spin.value(),
            art_type=ArtType.FRONT, show_logo=self.logo_cb.isChecked(), show_title=self.title_cb.isChecked(),
            position=self.pos_combo.currentData(), reference=ref,
        )
        http = self.pipeline.http
        self.gen_btn.setEnabled(False)
        self.gen_btn.setText("Creating…")

        def work():
            if logo is not None:
                opts.logo_data = logo.data or http.get(logo.url).data
                logo.data = opts.logo_data
            return generate(s, http, self.query, opts)

        run_in_background(work, self._generated)
        if logo is not None and self.query.artist_mbid:
            self._save_setting("logo_choices", s.with_logo_choice(self.query.artist_mbid, logo.url))

    def _generated(self, result, error) -> None:
        self.gen_btn.setEnabled(True)
        self.gen_btn.setText("Create")
        if isinstance(error, ConsentRequired):
            ans = QMessageBox.question(
                self, "Send album details to an AI service?",
                f"Creating a cover sends the artist, album title, year and genre to {error.host}"
                + (", and the current cover as a reference" if self.s["ai_allow_remote_reference"] else "")
                + ". Allow this for that service?",
            )
            if ans == QMessageBox.StandardButton.Yes:
                hosts = list(self.s["ai_consented_hosts"] or []) + [error.host]
                self._save_setting("ai_consented_hosts", hosts)
                self.s = self.state.settings()
                self._generate()
            return
        if error is not None:
            QMessageBox.warning(self, "CoverUp", f"Creating the cover failed: {error}\nDetails are in the CoverUp log.")
            return
        for c in result or []:
            self.generated.append(c)
            self.creative_grid.add_candidate(c, select=False)
        if result:
            self.creative_grid.item(0).setSelected(True)

    def _use_generated(self) -> None:
        picked = self.creative_grid.selected()
        if not picked or not self.slots:
            return
        front = self.slots[0]
        front.chosen = [picked[0]]
        front.include.setChecked(True)
        self._refresh_slot(front)
        self.tabs.setCurrentIndex(0)
        self.preview.show_candidate(picked[0])
        self._update_summary()

    def _save_setting(self, key, value) -> None:
        try:
            self.state.api.plugin_config[key] = value
        except Exception:
            log.debug("Could not save setting %s", key)

    # ===================================================================================== apply
    def _apply(self) -> None:
        if not self.apply_btn.isEnabled() or self._busy_applying:
            return
        self._apply_items(self.chosen_items(), close=True)

    def _item_for(self, slot: Slot, c: Candidate) -> PlanItem:
        if slot.group == "disc":
            return PlanItem(ArtType.DISC, c, disc_number=slot.disc)
        if slot.group == "booklet":
            return PlanItem(ArtType.BOOKLET, c, page=c.page or 1)
        if slot.group == "artist":
            return PlanItem(c.art_type, c)
        return PlanItem(slot.art_type, c)

    def _apply_now(self, slot: Slot, c: Candidate | None) -> None:
        """Double-click on a picture: choose it and apply that one image straight away, keeping the window open."""
        if c is None or self.result is None or self._busy_applying:
            return
        for i in range(slot.grid.count()):
            item = slot.grid.item(i)
            if item.data(Qt.ItemDataRole.UserRole) is c:
                item.setSelected(True)
        slot.include.setChecked(True)
        self._apply_items([self._item_for(slot, c)], close=False)

    def _apply_items(self, items: list[PlanItem], close: bool) -> None:
        if not items:
            return
        try:
            dest = self._destination()
        except ValueError as exc:
            QMessageBox.warning(self, "CoverUp", str(exc))
            return
        s = self.s.with_(**dest)
        embed_on, files_on = bool(dest["embed"]), bool(dest["save_files"])
        if not embed_on and not files_on:
            QMessageBox.information(self, "CoverUp", "Choose where the image goes first: embed it in the tags or save it as a file.")
            return
        self._busy_applying = True
        self.apply_btn.setEnabled(False)
        self.status.setText("Downloading the full-size image…" if len(items) == 1 else "Downloading the full-size images…")
        pipeline = self.pipeline

        def work():
            return pipeline.fetch_items(items)

        def done(result, error):
            self._busy_applying = False
            if error is not None:
                self._update_summary()
                self.status.setText(f"Downloading failed ({error}). Nothing was applied.")
                return
            items, failed = result
            if failed:
                names = ", ".join(f"{it.art_type.value} ({it.candidate.provider})" for it, _e in failed)
                if not items:
                    self._update_summary()
                    self.status.setText(f"Downloading failed for {names}: {failed[0][1]}. Nothing was applied; try another source or press Apply again.")
                    return
                QMessageBox.warning(self, "CoverUp", f"Could not download: {names}.\nThe other images are being applied; choose another source for these and apply again.")
            notes = glue.apply_plan(self.target, items, s, embed_on, files_on, status="applied")
            log.info("Applied by the user: %s (embed=%s, files=%s)", ", ".join(sorted({i.art_type.value for i in items})), embed_on, files_on)
            message = glue.describe_apply(self.target, items, s, embed_on, files_on)
            if notes:
                QMessageBox.information(self, "CoverUp", "\n".join(notes))
            if close:
                self.accept()
                return
            self._update_summary()
            self.status.setText(message)
            front = next((it.candidate for it in items if it.art_type == ArtType.FRONT), None)
            if front is not None:
                self.current = front
                self.preview.current = front
                self.cover.setPixmap(self._tile_pixmap(front, 72, "No cover"))

        run_in_background(work, done)

    def reject(self) -> None:
        self.cancel.set()
        super().reject()
