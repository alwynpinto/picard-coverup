import logging
import sys
import tomllib
import types
import uuid
from pathlib import Path

import coverup

ROOT = Path(__file__).resolve().parent.parent


def test_manifest_meets_picard_v3_spec():
    data = tomllib.loads((ROOT / "MANIFEST.toml").read_text(encoding="utf-8"))
    assert str(uuid.UUID(data["uuid"], version=4)) == data["uuid"]
    assert 1 <= len(data["name"]) <= 100
    assert 1 <= len(data["description"]) <= 200 and "\n" not in data["description"]
    assert data["api"] == ["3.0"]
    assert 1 <= len(data["long_description"]) <= 2000
    assert set(data["categories"]) <= {"metadata", "coverart", "ui", "scripting", "formats", "other"}
    assert data["license"] == "GPL-2.0-or-later"


class FakeConfig(dict):
    def register_option(self, key, default, **kw):
        self.setdefault(key, default)


class FakeApi:
    def __init__(self):
        self.plugin_config = FakeConfig()
        self.records = []

        outer = self

        class L:
            def warning(self, m):
                outer.records.append(("warning", m))

            def error(self, m):
                outer.records.append(("error", m))

        self.logger = L()


def test_enable_sets_up_logging_and_disable_closes_it(tmp_path, monkeypatch):
    appdirs = types.ModuleType("picard.const.appdirs")
    appdirs.cache_folder = lambda: str(tmp_path)
    const = types.ModuleType("picard.const")
    const.appdirs = appdirs
    monkeypatch.setitem(sys.modules, "picard", types.ModuleType("picard"))
    monkeypatch.setitem(sys.modules, "picard.const", const)
    monkeypatch.setitem(sys.modules, "picard.const.appdirs", appdirs)

    api = FakeApi()
    coverup.enable(api)
    assert api.plugin_config["log_mode"] == "fixed" and api.plugin_config["log_max_mb"] == 2
    logging.getLogger("coverup").warning("forward me")
    coverup.disable()
    log_file = tmp_path / "coverup" / "logs" / "coverup.log"
    assert "CoverUp 0.1.0 starting" in log_file.read_text(encoding="utf-8")
    assert ("warning", "CoverUp: forward me") in api.records
    assert coverup._log_handle is None
