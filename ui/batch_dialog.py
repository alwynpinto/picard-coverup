# -*- coding: utf-8 -*-
# CoverUp: MusicBrainz Picard plugin. GPL-2.0-or-later.
"""Auto-apply for many albums: apply confident results, queue the rest for review."""

from __future__ import annotations

import logging
import threading

from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .. import glue
from ..creative.auto import auto_creative
from ..model import ArtType
from ..pipeline import PlanItem
from .widgets import run_in_background

log = logging.getLogger("coverup.ui")

ICONS = {"applied": "✔ applied", "review": "⚠ needs review", "none": "✖ none found", "skipped": "⏭ skipped", "error": "✖ error", "running": "… searching", "queued": "queued"}


class BatchDialog(QDialog):
    def __init__(self, targets: list, parent=None, state=None):
        super().__init__(parent)
        self.state = state or glue.STATE
        self.targets = targets
        self.cancel = threading.Event()
        self.s = self.state.settings()
        self.generated_count = 0
        self.setWindowTitle(f"CoverUp: auto-apply ({len(targets)} albums)")
        self.resize(900, 520)
        lay = QVBoxLayout(self)
        self.info = QLabel(
            "Confident results are applied automatically; albums where sources disagree or nothing good was found "
            "are marked for review. Double-click a row to open it in the review dialog."
        )
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.table = QTableWidget(len(targets), 3)
        self.table.setHorizontalHeaderLabels(["Album", "Status", "Details"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self._review)
        for row, t in enumerate(targets):
            q = glue.query_from(t)
            self.table.setItem(row, 0, QTableWidgetItem(q.label_text))
            self.table.setItem(row, 1, QTableWidgetItem(ICONS["queued"]))
            self.table.setItem(row, 2, QTableWidgetItem(""))
        lay.addWidget(self.table, 1)
        btns = QHBoxLayout()
        self.summary = QLabel("")
        btns.addWidget(self.summary, 1)
        self.stop = QPushButton("Stop")
        self.stop.clicked.connect(self.cancel.set)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        btns.addWidget(self.stop)
        btns.addWidget(close)
        lay.addLayout(btns)
        self.counts = {"applied": 0, "review": 0, "none": 0, "error": 0, "skipped": 0}
        self._next(0)

    def _set(self, row: int, status: str, details: str) -> None:
        self.table.item(row, 1).setText(ICONS.get(status, status))
        self.table.item(row, 2).setText(details)
        self.table.item(row, 2).setToolTip(details)

    def _next(self, row: int) -> None:
        if row >= len(self.targets) or self.cancel.is_set():
            self.stop.setEnabled(False)
            self.summary.setText(", ".join(f"{k}: {v}" for k, v in self.counts.items() if v) + " - done. Save in Picard to write tags and files.")
            log.info("Batch finished: %s", self.counts)
            return
        self._set(row, "running", "")
        target = self.targets[row]
        q = glue.query_from(target)
        pipeline = self.state.pipeline(self.cancel)
        s = self.s
        tmpl_dirs = [self.state.user_templates_dir()]
        allow_creative = self.generated_count < int(s["creative_max_per_run"])

        def work():
            res = pipeline.run(q)
            plan, notes = pipeline.auto_plan(res)
            creative_note = ""
            if allow_creative and not any(p.art_type == ArtType.FRONT for p in plan):
                cand, creative_note = auto_creative(pipeline, res, s, tmpl_dirs)
                if cand is not None:
                    plan.insert(0, PlanItem(ArtType.FRONT, cand))
            elif allow_creative and s["creative_always"]:
                cand, creative_note = auto_creative(pipeline, res, s, tmpl_dirs)
                if cand is not None:
                    plan = [p for p in plan if p.art_type != ArtType.FRONT]
                    plan.insert(0, PlanItem(ArtType.FRONT, cand))
            plan, failed = pipeline.fetch_items(plan)
            notes = [*notes, *(f"Could not download the {it.art_type.value} from {it.candidate.provider}: {e}" for it, e in failed)]
            return res, plan, notes, creative_note

        def done(result, error):
            if error is not None:
                self.counts["error"] += 1
                self._set(row, "error", str(error))
                log.error("Batch item failed: %s", error)
            else:
                res, plan, notes, creative_note = result
                if any(p.candidate.generated for p in plan):
                    self.generated_count += 1
                front_sel = res.selections.get(ArtType.FRONT)
                if plan:
                    glue.apply_plan(target, plan, s, bool(s["embed"]), bool(s["save_files"]), status="applied")
                    status = "applied"
                elif front_sel and front_sel.conflict:
                    status = "review"
                    glue.set_status_variables(target, "review", None)
                elif front_sel and front_sel.winner and front_sel.winner.provider == "local":
                    status = "skipped"
                else:
                    status = "none" if not (front_sel and front_sel.winner) else "review"
                    glue.set_status_variables(target, status, None)
                applied = ", ".join(sorted({p.art_type.value for p in plan}))
                details = "; ".join(filter(None, [f"applied {applied}" if applied else "", creative_note, *notes]))
                self.counts[status] += 1
                self._set(row, status, details)
            self._next(row + 1)

        run_in_background(work, done)

    def _review(self, row: int, _col: int) -> None:
        from .review_dialog import ReviewDialog

        ReviewDialog(self.targets[row], self, self.state).exec()

    def closeEvent(self, event) -> None:
        self.cancel.set()
        super().closeEvent(event)
