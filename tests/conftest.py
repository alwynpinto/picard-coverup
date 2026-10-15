# -*- coding: utf-8 -*-
"""Test setup: load the repository root as the ``coverup`` package, run Qt off-screen, and optionally put
a Picard 3 source tree on the path (set PICARD_SRC) for the integration tests."""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("XDG_RUNTIME_DIR", "/tmp")
if os.environ.get("PICARD_SRC") and os.environ["PICARD_SRC"] not in sys.path:
    sys.path.insert(0, os.environ["PICARD_SRC"])


def _load_package() -> None:
    if "coverup" in sys.modules:
        return
    spec = importlib.util.spec_from_file_location("coverup", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["coverup"] = module
    spec.loader.exec_module(module)


_load_package()


def have_qt() -> bool:
    try:
        import PyQt6.QtGui  # noqa: F401

        return True
    except ImportError:
        return False


def have_picard() -> bool:
    try:
        import picard.plugin3.api  # noqa: F401

        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def qapp():
    if not have_qt():
        pytest.skip("PyQt6 not installed")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def wait_until(pred, timeout=20.0):
    """Process Qt events until ``pred()`` is true."""
    import time

    from PyQt6.QtWidgets import QApplication

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if pred():
            return True
        time.sleep(0.01)
    return False
