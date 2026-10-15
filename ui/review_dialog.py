# -*- coding: utf-8 -*-
# CoverUp: MusicBrainz Picard plugin. GPL-2.0-or-later.
"""The review dialog: search, compare, choose and apply artwork for one album (design section 7)."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import glue, imaging
from ..apply.files import FOLDER_PRESETS, validate_folder_name
from ..creative.generate import ConsentRequired, CreativeOptions, generate, resolve_template
from ..creative.template_engine import CUSTOM, load_templates
from ..imageinfo import probe
from ..model import ArtType, Candidate, Tier
from ..pipeline import AlbumResult, PlanItem
from ..settings import ARTIST_TYPES
from .widgets import CandidateGrid, run_in_background

log = logging.getLogger("coverup.ui")

SAME_FOLDER = "(same folder as the tracks)"
CUSTOM_FOLDER = "Custom…"


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
        self.disc_choice: dict[int, Candidate | None] = {}
        self.generated: list[Candidate] = []
        self.setWindowTitle(f"CoverUp: {self.query.label_text}")
        self.resize(1050, 780)
        self._build()
        self._start_search()

    # ------------------------------------------------------------------------------------------ UI
    def _build(self) -> None:
        root = QVBoxLayout(self)
        head = QHBoxLayout()
        self.title = QLabel(f"<b>{self.query.label_text}</b>")
        head.addWidget(self.title, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumWidth(160)
        head.addWidget(self.progress)
        self.stop_btn = QPushButton("Stop search")
        self.stop_btn.clicked.connect(self.cancel.set)
        head.addWidget(self.stop_btn)
        root.addLayout(head)
        self.status = QLabel("Searching sources…")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.warning = QLabel("")
        self.warning.setStyleSheet("color:#b26a00")
        self.warning.setWordWrap(True)
        root.addWidget(self.warning)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.grids: dict[str, CandidateGrid] = {}
        for key, title, multi in (("front", "Front", False), ("back", "Back", False), ("booklet", "Booklet", True), ("artist", "Artist", True)):
            w = QWidget()
            lay = QVBoxLayout(w)
            info = QLabel(self._tab_help(key))
            info.setWordWrap(True)
            lay.addWidget(info)
            grid = CandidateGrid(multi=multi)
            lay.addWidget(grid, 1)
            self.grids[key] = grid
            self.tabs.addTab(w, title)
            if key == "back":
                self.tabs.addTab(self._build_discs(), "Discs")
        self.tabs.addTab(self._build_creative(), "Creative / AI")

        opts = QHBoxLayout()
        self.show_rejected = QCheckBox("Show below-minimum / rejected")
        self.show_rejected.toggled.connect(self._refresh_grids)
        opts.addWidget(self.show_rejected)
        add_file = QPushButton("Add image file…")
        add_file.clicked.connect(self._add_file)
        opts.addWidget(add_file)
        add_url = QPushButton("Add from URL…")
        add_url.clicked.connect(self._add_url)
        opts.addWidget(add_url)
        opts.addStretch(1)
        root.addLayout(opts)

        box = QGroupBox("Apply")
        g = QGridLayout(box)
        self.type_checks: dict[str, QCheckBox] = {}
        default_types = set(self.s["apply_types"])
        for i, (key, label) in enumerate((("front", "Front"), ("back", "Back"), ("disc", "Discs"), ("booklet", "Booklet"), ("artist", "Artist images"))):
            cb = QCheckBox(label)
            cb.setChecked(key in default_types)
            self.type_checks[key] = cb
            g.addWidget(cb, 0, i)
        self.embed_cb = QCheckBox("Embed in tags")
        self.embed_cb.setChecked(bool(self.s["embed"]))
        self.files_cb = QCheckBox("Save as files")
        self.files_cb.setChecked(bool(self.s["save_files"]))
        g.addWidget(self.embed_cb, 1, 0)
        g.addWidget(self.files_cb, 1, 1)
        g.addWidget(QLabel("Folder:"), 1, 2)
        self.folder_combo = QComboBox()
        self.folder_combo.addItems([SAME_FOLDER, *FOLDER_PRESETS, CUSTOM_FOLDER])
        self.custom_folder = QLineEdit()
        self.custom_folder.setPlaceholderText("folder name")
        if self.s["folder_mode"] == "same":
            self.folder_combo.setCurrentText(SAME_FOLDER)
        elif self.s["folder_name"] in FOLDER_PRESETS:
            self.folder_combo.setCurrentText(self.s["folder_name"])
        else:
            self.folder_combo.setCurrentText(CUSTOM_FOLDER)
            self.custom_folder.setText(self.s["folder_name"])
        self.folder_combo.currentTextChanged.connect(lambda t: self.custom_folder.setEnabled(t == CUSTOM_FOLDER))
        self.custom_folder.setEnabled(self.folder_combo.currentText() == CUSTOM_FOLDER)
        g.addWidget(self.folder_combo, 1, 3)
        g.addWidget(self.custom_folder, 1, 4)
        when = "after you save in Picard" if self.s["write_files_when"] == "on_save" else "immediately"
        g.addWidget(QLabel(f"Files are written {when}; replaced files are backed up and can be undone."), 2, 0, 1, 5)
        root.addWidget(box)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setDefault(True)
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._apply)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        btns.addWidget(self.apply_btn)
        btns.addWidget(close)
        root.addLayout(btns)

        embeds, only_one = glue.picard_embeds_images()
        warn = []
        if not embeds:
            warn.append("Picard's “Embed cover images into tags” option is off, so nothing will be embedded.")
        elif only_one:
            warn.append("Picard's “Embed only a single front image” option is on: back/disc/booklet images will not be embedded.")
        self.warning.setText(" ".join(warn))
        self.warning.setVisible(bool(warn))

    @staticmethod
    def _tab_help(key: str) -> str:
        return {
            "front": "The highlighted image is CoverUp's pick. Hover for the score breakdown. Colours: green = exact release, blue = release group, brown = other sources.",
            "back": "Back covers. Unlabelled Discogs images are listed too: pick one if it is the back cover.",
            "booklet": "Select every page to keep (multi-select). Pages are named booklet-01, booklet-02, …",
            "artist": "Artist images are saved as files in the artist folder (the folder above the album). They are never embedded.",
        }[key]

    def _build_discs(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel("Disc:"))
        self.disc_combo = QComboBox()
        self.disc_combo.currentIndexChanged.connect(self._disc_changed)
        row.addWidget(self.disc_combo)
        self.disc_info = QLabel("")
        row.addWidget(self.disc_info, 1)
        none_btn = QPushButton("No art for this disc")
        none_btn.clicked.connect(lambda: self._set_disc_choice(None))
        row.addWidget(none_btn)
        lay.addLayout(row)
        self.disc_grid = CandidateGrid()
        self.disc_grid.itemSelectionChanged.connect(self._disc_selected)
        lay.addWidget(self.disc_grid, 1)
        return w

    def _build_creative(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        note = QLabel(
            "Generate replacement or alternative art. Generated images are always labelled as generated "
            "(tag comment, coverup.json, script variable) and are never uploaded anywhere. The band logo and "
            "title are drawn by CoverUp, not by the AI, so they stay sharp and correctly spelled."
        )
        note.setWordWrap(True)
        lay.addWidget(note)
        self.creative_reason = QLabel("")
        self.creative_reason.setStyleSheet("color:#8e24aa")
        lay.addWidget(self.creative_reason)
        g = QGridLayout()
        g.addWidget(QLabel("Style template:"), 0, 0)
        self.template_combo = QComboBox()
        self.templates = load_templates(self.state.user_templates_dir())
        for name, t in sorted(self.templates.items(), key=lambda kv: kv[1].title):
            self.template_combo.addItem(t.title, name)
        self.template_combo.addItem("Custom prompt (Options)", CUSTOM)
        idx = self.template_combo.findData(self.s["creative_template"])
        self.template_combo.setCurrentIndex(max(0, idx))
        g.addWidget(self.template_combo, 0, 1)
        g.addWidget(QLabel("Method:"), 0, 2)
        self.method_combo = QComboBox()
        self.method_combo.addItem("Offline template (no AI)", "template")
        if self.s["ai_backend"] != "none":
            self.method_combo.addItem(f"AI: {self.s['ai_backend']}", "ai")
            self.method_combo.setCurrentIndex(1)
        g.addWidget(self.method_combo, 0, 3)
        g.addWidget(QLabel("Variations:"), 0, 4)
        self.var_spin = QSpinBox()
        self.var_spin.setRange(1, 8)
        self.var_spin.setValue(int(self.s["creative_variations"]))
        self.var_spin.setMaximumWidth(70)
        g.addWidget(self.var_spin, 0, 5)
        g.addWidget(QLabel("Logo:"), 1, 0)
        self.logo_combo = QComboBox()
        self.logo_combo.addItem("Artist name as text", None)
        g.addWidget(self.logo_combo, 1, 1)
        self.logo_cb = QCheckBox("Logo/artist")
        self.logo_cb.setChecked(bool(self.s["creative_overlay_logo"]))
        self.title_cb = QCheckBox("Album title")
        self.title_cb.setChecked(bool(self.s["creative_overlay_title"]))
        g.addWidget(self.logo_cb, 1, 2)
        g.addWidget(self.title_cb, 1, 3)
        self.pos_combo = QComboBox()
        self.pos_combo.addItems(["top", "center", "bottom"])
        self.pos_combo.setCurrentText(self.s["creative_logo_position"])
        pos_row = QHBoxLayout()
        pos_row.addWidget(QLabel("Position:"))
        pos_row.addWidget(self.pos_combo)
        pos_row.addStretch(1)
        g.addLayout(pos_row, 1, 4, 1, 2)
        self.ref_cb = QCheckBox("Use the current/low-res cover as a reference (AI image-to-image)")
        self.ref_cb.setChecked(bool(self.s["ai_img2img"]))
        g.addWidget(self.ref_cb, 2, 0, 1, 4)
        self.gen_btn = QPushButton("Generate")
        self.gen_btn.clicked.connect(self._generate)
        g.addWidget(self.gen_btn, 2, 5)
        lay.addLayout(g)
        self.creative_grid = CandidateGrid()
        lay.addWidget(self.creative_grid, 1)
        self.use_generated = QCheckBox("Use the selected generated image as the front cover (instead of the Front tab choice)")
        lay.addWidget(self.use_generated)
        return w

    # ------------------------------------------------------------------------------------ search
    def _start_search(self) -> None:
        existing = glue.existing_front(self.target)
        if existing is not None:
            for grid in self.grids.values():
                grid.existing = existing
        run_in_background(lambda: self.pipeline.run(self.query), self._search_done)

    def _search_done(self, result, error) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.stop_btn.setEnabled(False)
        if error is not None or result is None:
            self.status.setText(f"Search failed: {error}. See the CoverUp log for details.")
            return
        self.result = result
        problems = [f"{k}: {v}" for k, v in sorted(result.provider_status.items()) if not v.endswith("found")]
        text = result.summary
        if result.cancelled:
            text = "Search stopped. " + text
        if problems:
            text += "<br><small>" + "; ".join(problems) + "</small>"
        self.status.setText(text)
        self._fill()
        self.apply_btn.setEnabled(True)

    def _fill(self) -> None:
        res = self.result
        if res is None:
            return
        self.disc_choice = {d: sel.winner for d, sel in res.discs.items()}
        self.disc_combo.blockSignals(True)
        self.disc_combo.clear()
        for d in sorted(res.discs):
            self.disc_combo.addItem(f"Disc {d}", d)
        self.disc_combo.blockSignals(False)
        for logo in res.logos:
            self.logo_combo.addItem(f"{logo.provider} logo ({logo.comment or logo.provider_id})", logo)
        remembered = self.s.logo_choice(self.query.artist_mbid)
        if remembered:
            for i in range(self.logo_combo.count()):
                c = self.logo_combo.itemData(i)
                if c is not None and c.url == remembered:
                    self.logo_combo.setCurrentIndex(i)
        elif res.logos:
            self.logo_combo.setCurrentIndex(1)
        reasons = [f"{a.value}: {why}" for a, (go, why) in res.creative.items() if go]
        if reasons:
            self.creative_reason.setText("Fallback triggered: " + "; ".join(reasons))
            self.tabs.setTabText(self.tabs.count() - 1, "Creative / AI ★")
            if res.creative.get(ArtType.FRONT, (False, ""))[0]:
                self.use_generated.setChecked(True)
        self._refresh_grids(preselect=True)
        self._disc_changed()

    def _refresh_grids(self, *_args, preselect: bool = False) -> None:
        res = self.result
        if res is None:
            return
        show = self.show_rejected.isChecked()
        front = res.selections.get(ArtType.FRONT)
        back = res.selections.get(ArtType.BACK)
        self.grids["front"].set_candidates(res.of_type(ArtType.FRONT), show, [front.winner] if preselect and front and front.winner else None)
        self.grids["back"].set_candidates(res.of_type(ArtType.BACK, include_unlabelled=True), show, [back.winner] if preselect and back and back.winner else None)
        self.grids["booklet"].set_candidates(res.of_type(ArtType.BOOKLET, include_unlabelled=True), show, list(res.booklet) if preselect else None)
        artist_all = [c for c in res.candidates if c.art_type in ARTIST_TYPES]
        self.grids["artist"].set_candidates(artist_all, show, [c for c in res.artist.values() if c] if preselect else None)
        self._disc_changed()

    # ------------------------------------------------------------------------------------- discs
    def _current_disc(self) -> int:
        d = self.disc_combo.currentData()
        return int(d) if d else 1

    def _disc_changed(self, *_a) -> None:
        res = self.result
        if res is None:
            return
        d = self._current_disc()
        n = len(res.discs)
        pool = [c for c in res.of_type(ArtType.DISC) if c.disc_number in (d, None) or n == 1]
        pool += res.of_type(ArtType.OTHER)
        chosen = self.disc_choice.get(d)
        self.disc_grid.blockSignals(True)
        self.disc_grid.set_candidates(pool, self.show_rejected.isChecked(), [chosen] if chosen else [])
        self.disc_grid.blockSignals(False)
        sel = res.discs.get(d)
        self.disc_info.setText(sel.rationale if sel else "")

    def _disc_selected(self) -> None:
        picked = self.disc_grid.selected()
        self.disc_choice[self._current_disc()] = picked[0] if picked else None

    def _set_disc_choice(self, c: Candidate | None) -> None:
        self.disc_choice[self._current_disc()] = c
        self.disc_grid.clearSelection()

    # ------------------------------------------------------------------------------ manual adding
    def _current_type(self) -> tuple[ArtType, CandidateGrid]:
        idx = self.tabs.currentIndex()
        title = self.tabs.tabText(idx)
        if title.startswith("Back"):
            return ArtType.BACK, self.grids["back"]
        if title.startswith("Discs"):
            return ArtType.DISC, self.disc_grid
        if title.startswith("Booklet"):
            return ArtType.BOOKLET, self.grids["booklet"]
        if title.startswith("Artist"):
            return ArtType.ARTIST_THUMB, self.grids["artist"]
        if title.startswith("Front"):
            return ArtType.FRONT, self.grids["front"]
        return ArtType.FRONT, self.grids["front"]

    def _manual(self, data: bytes, url: str, label: str) -> None:
        if not imaging.is_valid_image(data):
            QMessageBox.warning(self, "CoverUp", "That is not an image CoverUp can read.")
            return
        art, grid = self._current_type()
        info = probe(data[:65536]) or (0, 0, "")
        c = Candidate("manual", url or label, url, art, Tier.A, width=info[0], height=info[1], dims_known=True,
                      bytes=len(data), thumb_data=data, data=data, attribution="added by you", comment=label)
        fp = imaging.fingerprint(data)
        if fp:
            c.phash, c.blank = fp.phash, fp.blank
        if art == ArtType.DISC:
            c.disc_number = self._current_disc()
            self.disc_choice[c.disc_number] = c
        if self.result is not None:
            self.result.candidates.append(c)
        grid.add_candidate(c)
        log.info("Manual image added for %s: %s (%dx%d)", art.value, label, c.width, c.height)

    def _add_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Add image", str(Path.home()), "Images (*.jpg *.jpeg *.png *.webp *.gif *.bmp)")
        if path:
            try:
                self._manual(Path(path).read_bytes(), "", Path(path).name)
            except OSError as exc:
                QMessageBox.warning(self, "CoverUp", f"Could not read the file: {exc}")

    def _add_url(self) -> None:
        url, ok = QInputDialog.getText(self, "Add from URL", "Image URL:")
        if not ok or not url.strip().startswith(("http://", "https://")):
            return
        url = url.strip()
        http = self.pipeline.http
        run_in_background(lambda: http.get(url, cache=False).data, lambda data, err: (
            QMessageBox.warning(self, "CoverUp", f"Download failed: {err}") if err else self._manual(data, url, url)
        ))

    # ---------------------------------------------------------------------------------- creative
    def _generate(self) -> None:
        tname = self.template_combo.currentData()
        s = self.s
        template = resolve_template(s.with_(creative_template=tname), [self.state.user_templates_dir()])
        logo = self.logo_combo.currentData()
        ref = None
        if self.ref_cb.isChecked():
            front = self.grids["front"].selected()
            ref_c = front[0] if front else (self.grids["front"].existing)
            ref = ref_c.data or ref_c.thumb_data if ref_c else None
        opts = CreativeOptions(
            method=self.method_combo.currentData(), template=template, count=self.var_spin.value(),
            art_type=ArtType.FRONT, show_logo=self.logo_cb.isChecked(), show_title=self.title_cb.isChecked(),
            position=self.pos_combo.currentText(), reference=ref,
        )
        http = self.pipeline.http
        self.gen_btn.setEnabled(False)
        self.gen_btn.setText("Generating…")

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
        self.gen_btn.setText("Generate")
        if isinstance(error, ConsentRequired):
            ans = QMessageBox.question(
                self, "Send album details to an AI service?",
                f"Generating art will send the artist, album title, year and genre to {error.host}"
                + (" (and the current cover, if you enabled image-to-image references for remote services)" if self.s["ai_allow_remote_reference"] else "")
                + ". Allow this for that service?",
            )
            if ans == QMessageBox.StandardButton.Yes:
                hosts = list(self.s["ai_consented_hosts"] or []) + [error.host]
                self._save_setting("ai_consented_hosts", hosts)
                self.s = self.state.settings()
                self._generate()
            return
        if error is not None:
            QMessageBox.warning(self, "CoverUp", f"Generation failed: {error}\nSee the CoverUp log for details.")
            return
        for c in result or []:
            self.generated.append(c)
            self.creative_grid.add_candidate(c, select=False)
        if result:
            self.creative_grid.item(0).setSelected(True)
            self.use_generated.setChecked(True)

    def _save_setting(self, key, value) -> None:
        try:
            self.state.api.plugin_config[key] = value
        except Exception:
            log.debug("Could not save setting %s", key)

    # ------------------------------------------------------------------------------------- apply
    def _folder_settings(self):
        choice = self.folder_combo.currentText()
        if choice == SAME_FOLDER:
            return {"folder_mode": "same"}
        name = self.custom_folder.text().strip() if choice == CUSTOM_FOLDER else choice
        validate_folder_name(name)
        return {"folder_mode": "subfolder", "folder_name": name}

    def chosen_items(self) -> list[PlanItem]:
        items: list[PlanItem] = []
        t = {k: cb.isChecked() for k, cb in self.type_checks.items()}
        if t["front"]:
            gen = self.creative_grid.selected() if self.use_generated.isChecked() else []
            pick = gen or self.grids["front"].selected()
            if pick and pick[0].provider not in ("embedded",):
                items.append(PlanItem(ArtType.FRONT, pick[0]))
        if t["back"]:
            pick = self.grids["back"].selected()
            if pick:
                items.append(PlanItem(ArtType.BACK, pick[0]))
        if t["disc"]:
            for d, c in sorted(self.disc_choice.items()):
                if c is not None:
                    items.append(PlanItem(ArtType.DISC, c, disc_number=d))
        if t["booklet"]:
            pages = sorted(self.grids["booklet"].selected(), key=lambda c: (c.provider, c.page))
            items += [PlanItem(ArtType.BOOKLET, c, page=i + 1) for i, c in enumerate(pages)]
        if t["artist"]:
            for c in self.grids["artist"].selected():
                items.append(PlanItem(c.art_type, c))
        return items

    def _apply(self) -> None:
        try:
            overrides = self._folder_settings()
        except ValueError as exc:
            QMessageBox.warning(self, "CoverUp", str(exc))
            return
        items = self.chosen_items()
        if not items:
            QMessageBox.information(self, "CoverUp", "Nothing selected to apply.")
            return
        embed_on, files_on = self.embed_cb.isChecked(), self.files_cb.isChecked()
        if not (embed_on or files_on):
            QMessageBox.information(self, "CoverUp", "Choose “Embed in tags”, “Save as files”, or both.")
            return
        s = self.s.with_(**overrides)
        self.apply_btn.setEnabled(False)
        self.status.setText("Downloading full-size images…")
        pipeline = self.pipeline

        def work():
            for it in items:
                if it.candidate.data is None:
                    pipeline.fetch_full(it.candidate)
            return items

        def done(result, error):
            if error is not None:
                self.apply_btn.setEnabled(True)
                self.status.setText(f"Download failed: {error}")
                return
            notes = glue.apply_plan(self.target, items, s, embed_on, files_on, status="applied")
            summary = ", ".join(sorted({it.art_type.value for it in items}))
            log.info("Applied by user: %s (embed=%s, files=%s)", summary, embed_on, files_on)
            msg = f"Applied: {summary}."
            if embed_on:
                msg += " Save the album in Picard to write the tags."
            if files_on and s["write_files_when"] == "on_save":
                msg += " Image files are written when you save."
            if notes:
                msg += "\n" + "\n".join(notes)
            QMessageBox.information(self, "CoverUp", msg)
            self.accept()

        run_in_background(work, done)

    def reject(self) -> None:
        self.cancel.set()
        super().reject()
