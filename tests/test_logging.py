import logging
import os
import time

from coverup.diagnostics import logging_setup as ls

SECRET = "FAKE-TEST-KEY-1234567890"


def read_all(folder):
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(folder.glob("coverup*.log*")))


def make(tmp_path, **kw):
    kw.setdefault("level", "TRACE")
    return ls.setup_logging(ls.LogSettings(folder=tmp_path / "logs", **kw), secrets=[SECRET], name="coverup.test")


def test_fixed_mode_never_exceeds_size_and_backup_limits(tmp_path):
    h = make(tmp_path, mode=ls.MODE_FIXED, max_bytes=20_000, backups=3)
    log = logging.getLogger("coverup.test")
    for i in range(2000):
        log.info("message number %d with some padding text to grow the file quickly", i)
    h.close()
    files = list((tmp_path / "logs").glob("coverup.log*"))
    assert 2 <= len(files) <= 4  # active file + at most 3 backups
    assert all(p.stat().st_size <= 20_000 + 400 for p in files)  # at most one record over the limit


def test_default_settings_are_two_megabytes_and_three_backups(tmp_path):
    s = ls.LogSettings(folder=tmp_path)
    assert (s.mode, s.max_bytes, s.backups, s.level) == ("fixed", 2 * 1024 * 1024, 3, "INFO")


def test_secrets_are_redacted_everywhere(tmp_path):
    h = make(tmp_path)
    log = logging.getLogger("coverup.test")
    log.info("calling provider with key %s", SECRET)
    log.info("GET https://api.example.com/x?api_key=hunter2hunter2&foo=1")
    log.info("headers Authorization: Bearer abc.def.ghi")
    log.warning("token=zzzzzzzz leaked? client_secret: topsecretvalue")
    try:
        raise RuntimeError(f"failed with {SECRET}")
    except RuntimeError:
        log.exception("boom")
    h.close()
    text = read_all(tmp_path / "logs")
    for leaked in (SECRET, "hunter2hunter2", "abc.def.ghi", "zzzzzzzz", "topsecretvalue"):
        assert leaked not in text
    assert "foo=1" in text  # unrelated query parameters survive


def test_secrets_can_be_updated_at_runtime(tmp_path):
    h = make(tmp_path)
    h.set_secrets(["brand-new-secret-9999"])
    logging.getLogger("coverup.test").info("value brand-new-secret-9999")
    h.close()
    assert "brand-new-secret-9999" not in read_all(tmp_path / "logs")


def test_run_and_album_ids_are_logged(tmp_path):
    h = make(tmp_path)
    log = logging.getLogger("coverup.test")
    with ls.log_context(run="r42", album="mbid-123"):
        log.info("inside")
    log.info("outside")
    h.close()
    lines = read_all(tmp_path / "logs").splitlines()
    assert "[run=r42 album=mbid-123]" in next(ln for ln in lines if "inside" in ln)
    assert "[run=- album=-]" in next(ln for ln in lines if "outside" in ln)


def test_repeated_messages_are_collapsed(tmp_path):
    h = make(tmp_path)
    log = logging.getLogger("coverup.test")
    for _ in range(200):
        log.warning("provider down")
    log.info("recovered")
    h.close()
    text = read_all(tmp_path / "logs")
    assert text.count("provider down") == 1
    assert "repeated 199 more times" in text


def test_level_filtering_and_runtime_change(tmp_path):
    h = make(tmp_path, level="WARNING")
    log = logging.getLogger("coverup.test")
    log.info("hidden-info")
    log.warning("shown-warning")
    h.set_level("DEBUG")
    log.debug("shown-debug")
    h.close()
    text = read_all(tmp_path / "logs")
    assert "hidden-info" not in text and "shown-warning" in text and "shown-debug" in text


def test_trace_level_exists_and_verbose_toggle(tmp_path):
    assert ls.level_from_name("trace") == ls.TRACE < logging.DEBUG
    s = ls.LogSettings(folder=tmp_path, level="ERROR", verbose_until_restart=True)
    assert s.effective_level() == logging.DEBUG


def test_unwritable_folder_degrades_without_raising(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    seen = []
    h = ls.setup_logging(
        ls.LogSettings(folder=blocker / "logs"), picard_sink=lambda lvl, msg: seen.append(msg), name="coverup.test2"
    )
    logging.getLogger("coverup.test2").error("still works")
    h.close()
    assert h.enabled is False and h.warnings
    assert any("File logging disabled" in m for m in seen)  # one warning reaches Picard's log
    assert any("still works" in m for m in seen)


def test_warnings_forwarded_to_picard_sink_but_not_info(tmp_path):
    seen = []
    h = ls.setup_logging(
        ls.LogSettings(folder=tmp_path / "logs", level="DEBUG"),
        picard_sink=lambda lvl, msg: seen.append((lvl, msg)),
        name="coverup.test3",
    )
    log = logging.getLogger("coverup.test3")
    log.info("detail only in file")
    log.warning("visible in picard")
    h.close()
    assert [m for _l, m in seen] == ["CoverUp: visible in picard"]


def test_mode_off_writes_no_file(tmp_path):
    h = make(tmp_path, mode=ls.MODE_OFF)
    logging.getLogger("coverup.test").error("nothing on disk")
    h.close()
    assert not list((tmp_path / "logs").glob("*.log*")) if (tmp_path / "logs").exists() else True


def test_session_mode_keeps_only_recent_sessions(tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    for i in range(8):
        p = folder / f"coverup-2026010{i}-000000.log"
        p.write_text("old")
        os.utime(p, (time.time() - (100 - i), time.time() - (100 - i)))
    h = ls.setup_logging(ls.LogSettings(folder=folder, mode=ls.MODE_SESSION, sessions_keep=3), name="coverup.test4")
    logging.getLogger("coverup.test4").info("new session")
    h.close()
    assert len(list(folder.glob("coverup-*.log"))) <= 3


def test_age_mode_prunes_old_files_and_respects_ceiling(tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    old = folder / "coverup.log.5"
    old.write_text("x" * 100)
    os.utime(old, (time.time() - 40 * 86400,) * 2)
    fresh = folder / "coverup.log.1"
    fresh.write_text("y" * 100)
    removed = ls.prune_by_age(folder, retain_days=14, ceiling_bytes=1_000_000)
    assert old in removed and fresh.exists()
    big = [folder / f"coverup.log.{i}" for i in (2, 3, 4)]
    for i, p in enumerate(big):
        p.write_text("z" * 600)
        os.utime(p, (time.time() - 100 + i,) * 2)
    ls.prune_by_age(folder, retain_days=14, ceiling_bytes=1000)
    assert sum(p.stat().st_size for p in folder.glob("coverup.log*")) <= 1000


def test_total_cap_mode_bounds_total_size(tmp_path):
    h = make(tmp_path, mode=ls.MODE_TOTAL, max_bytes=64 * 1024, total_cap_bytes=256 * 1024)
    log = logging.getLogger("coverup.test")
    for i in range(6000):
        log.info("line %d %s", i, "p" * 80)
    h.close()
    total = sum(p.stat().st_size for p in (tmp_path / "logs").glob("coverup.log*"))
    assert total <= 256 * 1024 + 64 * 1024  # cap plus the active file's slack


def test_anonymise_hashes_names_and_home(tmp_path):
    h = make(tmp_path, anonymise=True, sensitive_strings=("Pink Floyd", "The Wall"))
    logging.getLogger("coverup.test").info("album Pink Floyd - The Wall at %s/Music", os.path.expanduser("~"))
    h.close()
    text = read_all(tmp_path / "logs")
    assert "Pink Floyd" not in text and "The Wall" not in text and "<HOME>" in text and "anon-" in text
