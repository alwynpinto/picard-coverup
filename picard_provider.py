# -*- coding: utf-8 -*-
# CoverUp: MusicBrainz Picard plugin. GPL-2.0-or-later.
"""CoverUp as one of Picard's own cover art providers.

It appears in Options > Cover Art next to "Cover Art Archive" and "Discogs". When Picard loads an album and
this provider is ticked, CoverUp runs its normal search (Cover Art Archive, Discogs, Wikimedia, Fanart.tv and the
rest), picks what it is confident about and hands the front and back covers to Picard, which embeds them
under its usual rules. The image files (covers folder, naming, artist images, disc art, booklets) are written
by CoverUp when the album is saved, exactly as with Auto-apply.

Picard stops asking providers once it has the front cover it needs, so move CoverUp above the others in
that list to let it take precedence. Pure Picard wiring: the search and the choice are the same code that the
review window and Auto-apply use.
"""

from __future__ import annotations

import logging

from . import glue, imaging
from .model import ArtType
from .ui.widgets import run_in_background

log = logging.getLogger("coverup.provider")

# Picard embeds images into every track of the album, so only album-wide images are handed over;
# disc art and booklets are written as files by CoverUp.
HANDED_TO_PICARD = (ArtType.FRONT, ArtType.BACK)


def make_provider_class(Base):
    """Build the provider class on Picard's CoverArtProvider (imported by the caller inside ``enable``)."""
    queue_state = getattr(Base, "QueueState", Base)  # Picard 3 keeps FINISHED and WAIT on QueueState

    class CoverArtProviderCoverUp(Base):
        NAME = "CoverUp"
        TITLE = "CoverUp (best match from all sources)"

        def enabled(self):
            # not the base class check: CoverUp also supplies back covers, disc art and artist images
            # that an earlier provider's front cover says nothing about
            return True

        def queue_images(self):
            try:
                state = glue.STATE
                s = state.settings()
                md = self.metadata
                q = glue.query_from_metadata(md, release=self.release)
                if not (q.artist or q.album or q.release_mbid):
                    return queue_state.FINISHED
                pipeline = state.pipeline()
                log.info("Picard asked CoverUp for artwork: %s", q.label_text)

                def work():
                    res = pipeline.run(q)
                    plan, notes = pipeline.auto_plan(res)
                    for item in plan:
                        if item.candidate.data is None:
                            pipeline.fetch_full(item.candidate)
                    return res, plan, notes

                run_in_background(work, lambda result, error: self._done(s, result, error))
            except Exception:
                log.exception("CoverUp could not start for %s", getattr(self.album, "id", "?"))
                return queue_state.FINISHED
            return queue_state.WAIT

        def _done(self, s, result, error):
            """Back on Picard's main thread. Whatever happens, hand control back exactly once."""
            try:
                if error is not None:
                    log.warning("CoverUp found nothing for Picard: %s", error)
                    return
                res, plan, notes = result
                if not plan:
                    log.info("Nothing confident enough to hand to Picard (%s)", "; ".join(notes) or "no results")
                    front_sel = res.selections.get(ArtType.FRONT)
                    self._status("review" if front_sel and front_sel.winner else "none", None)
                    return
                if s["save_files"]:
                    glue.schedule_files(self.album, plan, s)
                if s["embed"]:
                    wanted = s.embed_art_types()
                    for item in plan:
                        if item.art_type in HANDED_TO_PICARD and item.art_type in wanted:
                            self._queue(item, s)
                front = next((it.candidate for it in plan if it.art_type == ArtType.FRONT), None)
                self._status("applied", front)
            except Exception:
                log.exception("CoverUp could not hand its images to Picard")
            finally:
                try:
                    self.next_in_queue()
                except Exception:
                    log.exception("CoverUp could not continue Picard's cover art queue")

        def _queue(self, item, s):
            c = item.candidate
            if c.data is None:
                return
            data, w, h, _fmt = imaging.prepare(c.data, int(s["embed_max_side"] or 0), "original", int(s["jpeg_quality"]))
            comment = c.comment if c.generated else (f"CoverUp: {c.provider}" if s["record_source_in_comment"] else "")
            self.queue_put(glue._make_image(data, item.art_type, comment, c.url))
            log.info("Handed the %s from %s (%dx%d) to Picard", item.art_type.value, c.provider, w, h)

        def _status(self, status, front):
            try:
                for key, value in glue.status_values(status, front).items():
                    if value:
                        self.metadata[key] = value
            except Exception:
                log.debug("Could not set the CoverUp status variables", exc_info=True)

    return CoverArtProviderCoverUp
