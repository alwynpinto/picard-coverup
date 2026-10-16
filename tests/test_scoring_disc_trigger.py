from coverup.creative.trigger import CreativeSettings, Situation, Trigger, should_generate
from coverup.matching.disc import assign_disc_numbers, disc_for_track, parse_disc_number, parse_vinyl_side
from coverup.matching.scoring import ResolutionLimits, check_limits, select_best
from coverup.model import ArtType, Candidate, Tier

ART_A = 0x0F0F0F0F0F0F0F0F  # artwork 1
ART_B = 0xF0F0F0F0F0F0F0F0  # artwork 2 (far from artwork 1)


def cand(provider, tier=Tier.C, phash=ART_A, size=1000, art=ArtType.FRONT, **kw):
    return Candidate(provider, provider + "-id", f"https://x/{provider}", art, tier, size, size, 200_000, phash=phash, **kw)


# ---- limits ----------------------------------------------------------------------------------------

def test_limits_reasons_are_explained():
    lim = ResolutionLimits(min_width=500, min_height=500, aspect_min=0.95, aspect_max=1.05, max_width=4000)
    assert check_limits(cand("a", size=1000), lim) is None
    assert "Too small: 300x300" in check_limits(cand("a", size=300), lim)
    assert "Too large" in check_limits(cand("a", size=5000), lim)
    wide = Candidate("a", "1", "u", width=1000, height=600, bytes=1)
    assert "Aspect ratio" in check_limits(wide, lim)


def test_below_minimum_candidates_are_rejected_but_kept():
    sel = select_best([cand("caa", Tier.A, size=300)], ArtType.FRONT)
    assert sel.winner is None and len(sel.rejected) == 1
    assert sel.rejected[0].rejected_reason.startswith("Too small")


# ---- selection -------------------------------------------------------------------------------------

def test_exact_release_beats_visually_different_web_results():
    cands = [cand("caa", Tier.A, ART_A, 1200)] + [cand(p, Tier.C, ART_B) for p in ("itunes", "deezer")]
    sel = select_best(cands, ArtType.FRONT, conflict_min_sources=3)
    assert sel.winner.provider == "caa"
    assert sel.auto_apply and not sel.conflict


def test_anchored_art_conflicting_with_big_consensus_is_flagged():
    cands = [cand("caa", Tier.A, ART_A, 1200)] + [cand(p, Tier.C, ART_B) for p in ("itunes", "deezer", "lastfm")]
    sel = select_best(cands, ArtType.FRONT, conflict_min_sources=3)
    assert sel.conflict and not sel.auto_apply
    assert sel.winner.provider == "caa"  # still reported, but not auto-applied
    assert "needs review" in sel.rationale


def test_without_anchor_the_largest_consensus_cluster_wins():
    cands = [cand("web", Tier.C, ART_B, 2000)] + [cand(p, Tier.C, ART_A, 800) for p in ("itunes", "deezer")]
    sel = select_best(cands, ArtType.FRONT)
    assert sel.winner.provider in ("itunes", "deezer")
    assert sel.auto_apply
    assert "visual-agreement" in sel.rationale


def test_generated_art_is_never_selected_as_real_art():
    gen = cand("ai", Tier.G, ART_B, generated=True)
    sel = select_best([gen], ArtType.FRONT)
    assert sel.winner is None


def test_score_breakdown_is_recorded_and_blank_is_penalised():
    good = cand("caa", Tier.A, ART_A)
    blank = cand("web", Tier.C, ART_B, blank=True)
    select_best([good, blank], ArtType.FRONT)
    assert "anchor" in good.breakdown and good.score > blank.score
    assert "placeholder_penalty" in blank.breakdown


# ---- disc matching ---------------------------------------------------------------------------------

def test_parse_disc_number_variants():
    assert parse_disc_number("Disc 2") == 2
    assert parse_disc_number("cd3 label") == 3
    assert parse_disc_number("DISK-1") == 1
    assert parse_disc_number("Disc two") == 2
    assert parse_disc_number("Front cover") is None
    assert parse_disc_number(None) is None
    assert parse_vinyl_side("Vinyl, Side B") == "B"


def test_assign_disc_numbers_discards_out_of_range():
    a = cand("caa", art=ArtType.DISC, comment="CD2")
    b = cand("caa", art=ArtType.DISC, comment="Disc 5")
    c = cand("caa", art=ArtType.DISC, comment="no number")
    given = cand("fanart", art=ArtType.DISC, disc_number=1)
    assign_disc_numbers([a, b, c, given], total_discs=2)
    assert (a.disc_number, b.disc_number, c.disc_number, given.disc_number) == (2, None, None, 1)


def test_disc_for_track():
    assert disc_for_track("2/3") == 2
    assert disc_for_track("1") == 1
    assert disc_for_track(None) == 1
    assert disc_for_track("") == 1


# ---- creative fallback triggers ----------------------------------------------------------------------

def test_creative_is_off_by_default():
    ok, _ = should_generate(Situation(ArtType.FRONT, found=False), CreativeSettings())
    assert not ok


def test_no_cover_trigger():
    cfg = CreativeSettings(triggers=Trigger.NO_COVER)
    assert should_generate(Situation(ArtType.FRONT, found=False), cfg)[0]
    assert not should_generate(Situation(ArtType.FRONT, found=True, best_side=1000), cfg)[0]


def test_low_resolution_trigger_uses_apply_minimum():
    cfg = CreativeSettings(triggers=Trigger.BELOW_MIN_RESOLUTION, apply_min_side=500)
    assert should_generate(Situation(ArtType.FRONT, found=True, best_side=300), cfg)[0]
    assert not should_generate(Situation(ArtType.FRONT, found=True, best_side=800), cfg)[0]


def test_always_generate_works_even_with_real_art_but_only_for_enabled_types():
    cfg = CreativeSettings(always_generate=True, art_types=(ArtType.FRONT,))
    assert should_generate(Situation(ArtType.FRONT, found=True, best_side=3000), cfg)[0]
    assert not should_generate(Situation(ArtType.BACK, found=True, best_side=3000), cfg)[0]


def test_combined_triggers():
    cfg = CreativeSettings(triggers=Trigger.NO_COVER | Trigger.LOW_CONFIDENCE)
    assert should_generate(Situation(ArtType.FRONT, found=True, conflict_or_tier_c_only=True), cfg)[0]


# ---- settings migration ------------------------------------------------------------------------------

def test_migration_moves_untouched_defaults_and_keeps_user_choices():
    from coverup.settings import SETTINGS_VERSION, migrate

    old_user = {"settings_version": 0, "apply_types": ["front"], "prefer_largest": False, "apply_min_side": 450,
                "jpeg_quality": 92, "record_source_in_comment": True}
    changed = migrate(old_user)
    assert old_user["apply_types"] == ["front", "back", "disc", "booklet", "artist"] and old_user["prefer_largest"] is True
    assert old_user["apply_min_side"] == 450  # the user's own value is kept
    assert set(changed) == {"apply_types", "prefer_largest", "jpeg_quality", "record_source_in_comment", "min_back", "min_disc", "min_booklet", "min_artist", "providers_enabled"}
    assert "wikimedia" in old_user["providers_enabled"]
    assert old_user["settings_version"] == SETTINGS_VERSION
    again = dict(old_user, prefer_largest=False)
    assert migrate(again) == [] and again["prefer_largest"] is False  # runs once only


def test_migration_from_0_3_keeps_a_users_own_choices():
    from coverup.settings import migrate

    # a user who had picked front and back only, and their own source list, keeps both
    cfg = {"settings_version": 2, "apply_types": ["front", "back"], "providers_enabled": ["caa", "discogs"]}
    assert migrate(cfg) == []
    assert cfg["apply_types"] == ["front", "back"] and cfg["providers_enabled"] == ["caa", "discogs"]
    # the 0.3 defaults move to the 0.4 defaults
    cfg = {"settings_version": 2, "apply_types": ["front", "back", "disc", "booklet"],
           "providers_enabled": ["caa", "discogs", "fanart", "audiodb", "itunes", "deezer", "local"]}
    assert set(migrate(cfg)) == {"apply_types", "providers_enabled"}
    assert "artist" in cfg["apply_types"] and "wikimedia" in cfg["providers_enabled"]


def test_artist_types_follow_the_artist_settings():
    from coverup.settings import Settings

    s = Settings.from_mapping({})
    assert s.artist_art_types() == {ArtType.ARTIST_THUMB}
    assert ArtType.ARTIST_THUMB in s.apply_art_types() and ArtType.ARTIST_LOGO not in s.apply_art_types()
    s = Settings.from_mapping({"artist_types": ["thumb", "logo", "banner"]})
    assert s.artist_art_types() == {ArtType.ARTIST_THUMB, ArtType.ARTIST_LOGO, ArtType.ARTIST_BANNER}
    off = Settings.from_mapping({"artist_art": False})
    assert off.artist_art_types() == set() and not (off.apply_art_types() & {ArtType.ARTIST_THUMB})
    # leaving "artist" out of the types list also turns the group off
    assert ArtType.ARTIST_THUMB not in Settings.from_mapping({"apply_types": ["front"]}).apply_art_types()


def test_embed_types():
    from coverup.settings import Settings

    assert Settings.from_mapping({}).embed_art_types() == {ArtType.FRONT}
    assert Settings.from_mapping({"embed_types": ["front", "disc"]}).embed_art_types() == {ArtType.FRONT, ArtType.DISC}


def test_cassette_and_dvd_fronts_are_not_rejected_as_non_square():
    from coverup.matching.scoring import limits_from_settings
    from coverup.settings import Settings

    s = Settings.from_mapping({})
    jcard = Candidate("caa", "1", "u", ArtType.FRONT, Tier.A, 640, 1000, 1)
    assert "Aspect" in (check_limits(jcard, limits_from_settings(s, ArtType.FRONT, "CD")) or "")
    assert check_limits(jcard, limits_from_settings(s, ArtType.FRONT, "Cassette")) is None
    assert check_limits(jcard, limits_from_settings(s, ArtType.FRONT, "DVD-Video")) is None
    tiny = Candidate("caa", "2", "u", ArtType.FRONT, Tier.A, 200, 320, 1)
    assert "Too small" in check_limits(tiny, limits_from_settings(s, ArtType.FRONT, "Cassette"))
