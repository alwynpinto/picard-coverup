"""Picard's left pane: loose files under "Unclustered Files", real clusters, and the CoverUp cover art provider
that Picard calls itself while it loads an album. Uses real Picard 3 objects (set PICARD_SRC)."""

import os

import pytest

from conftest import have_picard
from helpers import FakeHttp, make_image

pytestmark = [pytest.mark.skipif(not have_picard(), reason="set PICARD_SRC to a Picard 3 source tree"), pytest.mark.usefixtures("qapp")]

from test_glue_picard import REL, build_album, picard_env  # noqa: E402,F401  (fixture reuse)


def loose_files(tmp_path, n=3, album="Loose Album", artist="Loose Artist"):
    from picard.file import File

    folder = tmp_path / artist / album
    folder.mkdir(parents=True)
    files = []
    for i in range(n):
        f = File(str(folder / f"{i + 1:02d}.flac"))
        f.metadata["album"] = album
        f.metadata["albumartist"] = artist
        f.metadata["date"] = "1984"
        files.append(f)
    return files


def special_cluster(files):
    from picard.cluster import UnclusteredFiles

    cluster = UnclusteredFiles()
    for f in files:
        cluster.files.append(f)
        f.parent_item = cluster
    return cluster


def test_loose_files_become_their_own_albums_by_tag(picard_env):
    from coverup import glue

    a = loose_files(picard_env, 2, "One", "Band")
    b = loose_files(picard_env, 1, "Two", "Band")
    cluster = special_cluster(a + b)
    groups = glue.unique_targets([cluster])
    assert sorted(len(g.files) for g in groups) == [1, 2] and all(isinstance(g, glue.FileGroup) for g in groups)
    # picking a single file in the left pane works on just that file's album
    only = glue.unique_targets([a[0]])
    assert len(only) == 1 and only[0].files == [a[0]]
    q = glue.query_from(groups[0] if groups[0].files[0] in a else groups[1])
    assert (q.artist, q.album, q.year) == ("Band", "One", 1984) and len(q.album_dirs) == 1


def test_cover_embeds_in_loose_files_and_files_are_written_after_save(picard_env):
    from coverup import glue
    from coverup.model import ArtType, Candidate, Tier
    from coverup.pipeline import PlanItem
    from coverup.settings import Settings

    files = loose_files(picard_env, 3)
    cluster = special_cluster(files)
    assert cluster.can_show_coverart is False  # Picard cannot hold art on this node itself
    (group,) = glue.unique_targets([cluster])
    front = Candidate("caa", "1", "u", ArtType.FRONT, Tier.A, data=make_image("a", 900))
    s = Settings.from_mapping({"folder_mode": "subfolder", "folder_name": "covers"})
    glue.apply_plan(group, [PlanItem(ArtType.FRONT, front)], s, embed_on=True, files_on=True)
    for f in files:
        assert [i.types for i in f.metadata.images] == [["front"]]  # every loose file got the cover
    folder = os.path.dirname(files[0].filename)
    assert not os.path.exists(os.path.join(folder, "covers", "cover.jpg"))  # waits for Picard's save
    glue.on_file_saved(None, files[1])  # Picard reports a save: the plan is found from the file itself
    assert os.path.exists(os.path.join(folder, "covers", "cover.jpg")) and os.path.exists(os.path.join(folder, "cover.jpg"))
    msgs = glue.undo_last(group)
    assert msgs and not os.path.exists(os.path.join(folder, "covers", "cover.jpg"))


def test_applying_again_replaces_the_cover_on_loose_files(picard_env):
    from coverup import glue
    from coverup.model import ArtType, Candidate, Tier
    from coverup.pipeline import PlanItem
    from coverup.settings import Settings

    files = loose_files(picard_env, 2)
    (group,) = glue.unique_targets([special_cluster(files)])
    s = Settings.from_mapping({})
    for pattern in ("a", "b"):
        c = Candidate("caa", pattern, "u" + pattern, ArtType.FRONT, Tier.A, data=make_image(pattern, 800))
        glue.embed(group, [PlanItem(ArtType.FRONT, c)], s)
    for f in files:
        assert len(list(f.metadata.images)) == 1


def test_a_real_cluster_in_the_left_pane_still_applies_to_the_cluster(picard_env):
    from picard.cluster import Cluster

    from coverup import glue
    from coverup.model import ArtType, Candidate, Tier
    from coverup.pipeline import PlanItem
    from coverup.settings import Settings

    files = loose_files(picard_env, 2, "Clustered", "Band")
    cluster = Cluster("Clustered", "Band")
    for f in files:
        cluster.files.append(f)
        f.parent_item = cluster
    assert glue.unique_targets([cluster]) == [cluster] and glue.unique_targets([files[0]]) == [cluster]
    c = Candidate("caa", "1", "u", ArtType.FRONT, Tier.A, data=make_image("a", 800))
    glue.embed(cluster, [PlanItem(ArtType.FRONT, c)], Settings.from_mapping({}))
    assert all(len(list(f.metadata.images)) == 1 for f in files)
    assert len(list(cluster.metadata.images)) == 1


# ---- CoverUp as one of Picard's cover art providers ---------------------------------------------------

class FakeCoverArt:
    """The bits of Picard's CoverArt object that a provider uses."""

    def __init__(self, album, metadata, release):
        self.album, self.metadata, self.release = album, metadata, release
        self.queued, self.next_calls = [], 0
        self.front_image_found = False

    def queue_put(self, image):
        self.queued.append(image)

    def next_in_queue(self):
        self.next_calls += 1


def provider_env(monkeypatch, picard_env, routes):
    from coverup import glue, imaging, picard_provider
    from coverup.pipeline import Pipeline
    from picard.plugin3.api import CoverArtProvider
    from test_ui import FakeApi

    api = FakeApi(providers_enabled=["caa"])
    monkeypatch.setattr(glue.STATE, "api", api)
    http = FakeHttp(routes)
    monkeypatch.setattr(glue.STATE, "pipeline", lambda cancel=None: Pipeline(glue.STATE.settings(), http, imaging.fingerprint))
    # run the background work right here instead of on Picard's thread pool
    monkeypatch.setattr(picard_provider, "run_in_background", lambda work, cb: cb(*_run(work)))
    return picard_provider.make_provider_class(CoverArtProvider), glue


def _run(work):
    try:
        return work(), None
    except BaseException as exc:  # noqa: BLE001
        return None, exc


def caa_routes(rg="22222222-2222-4222-8222-222222222222"):
    from test_ui import routes

    r = routes()
    r[f"https://coverartarchive.org/release-group/{rg}"] = 404
    return r


def test_provider_hands_front_and_back_to_picard_and_schedules_the_files(picard_env, monkeypatch):
    from picard.plugin3.api import CoverArtProvider

    cls, glue = provider_env(monkeypatch, picard_env, caa_routes())
    glue.STATE.pending.clear()
    album, _files = build_album(picard_env, discs=2)
    glue.STATE.api.plugin_config["embed_types"] = ["front", "back"]
    coverart = FakeCoverArt(album, album.metadata, {"media": [{}, {}]})
    provider = cls(coverart)
    assert provider.enabled() is True
    state = provider.queue_images()
    assert state == CoverArtProvider.QueueState.FINISHED or state == CoverArtProvider.QueueState.WAIT
    assert coverart.next_calls == 1  # Picard's queue is released exactly once
    types = sorted(tuple(i.types) for i in coverart.queued)
    assert types == [("back",), ("front",)]
    assert all(i.can_be_saved_to_disk is False and i.datahash for i in coverart.queued)  # CoverUp writes its own files
    plan = glue.STATE.pending[glue.key_of(album)]
    assert {it.art_type.value for it in plan.items} >= {"front", "back"}
    assert album.metadata["_coverup_status"] == "applied" and album.metadata["_coverup_source"] == "caa"


def test_provider_with_the_default_embed_choice_hands_over_only_the_front(picard_env, monkeypatch):
    cls, glue = provider_env(monkeypatch, picard_env, caa_routes())
    glue.STATE.pending.clear()
    album, _ = build_album(picard_env, discs=2)
    coverart = FakeCoverArt(album, album.metadata, {})
    cls(coverart).queue_images()
    assert [tuple(i.types) for i in coverart.queued] == [("front",)] and coverart.next_calls == 1
    assert glue.STATE.pending  # the back cover and the rest are still written as files


def test_provider_never_stalls_picard_when_the_search_fails_or_finds_nothing(picard_env, monkeypatch):
    from coverup import picard_provider

    cls, glue = provider_env(monkeypatch, picard_env, {})  # every request is a 404: nothing found
    album, _ = build_album(picard_env, discs=1)
    coverart = FakeCoverArt(album, album.metadata, {})
    cls(coverart).queue_images()
    assert coverart.queued == [] and coverart.next_calls == 1
    assert album.metadata["_coverup_status"] == "none"
    # a crash inside the background work still releases the queue
    def boom(work, cb):
        cb(None, RuntimeError("boom"))

    monkeypatch.setattr(picard_provider, "run_in_background", boom)
    coverart2 = FakeCoverArt(album, album.metadata, {})
    cls(coverart2).queue_images()
    assert coverart2.next_calls == 1
    # and so does a release with no usable tags at all
    from picard.metadata import Metadata

    coverart3 = FakeCoverArt(album, Metadata(), {})
    state = cls(coverart3).queue_images()
    assert state == type(state).FINISHED and coverart3.next_calls == 0  # FINISHED: Picard continues by itself


def test_provider_is_listed_with_a_title_picard_can_show(picard_env, monkeypatch):
    cls, _ = provider_env(monkeypatch, picard_env, {})
    assert cls.name == "CoverUp" and "CoverUp" in cls.display_title()
