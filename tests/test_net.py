"""The real HTTP client against a local test server: retries, Retry-After, caching, ranges, cancel, redaction."""

import http.server
import threading
import time

import pytest

from coverup import net


class Handler(http.server.BaseHTTPRequestHandler):
    hits: dict = {}

    def log_message(self, *a):
        pass

    def do_GET(self):
        Handler.hits[self.path] = Handler.hits.get(self.path, 0) + 1
        n = Handler.hits[self.path]
        if self.path == "/flaky" and n == 1:
            self.send_response(429)
            self.send_header("Retry-After", "0.1")
            self.end_headers()
            return
        if self.path == "/gone":
            self.send_response(404)
            self.end_headers()
            return
        body = b'{"ok": true, "n": %d}' % n if self.path != "/big" else b"x" * 200_000
        rng = self.headers.get("Range")
        if rng and self.path == "/big":
            body = body[:1000]
            self.send_response(206)
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_retry_after_429(server):
    c = net.HttpClient(retries=2)
    assert c.get_json(server + "/flaky", cache=False)["ok"]
    assert Handler.hits["/flaky"] == 2


def test_404_raises_with_status(server):
    with pytest.raises(net.HttpError) as e:
        net.HttpClient(retries=0).get(server + "/gone")
    assert e.value.status == 404


def test_disk_cache(server, tmp_path):
    c = net.HttpClient(cache_dir=tmp_path, cache_hours=1)
    first = c.get_json(server + "/cached")
    second = c.get_json(server + "/cached")
    assert first == second and Handler.hits["/cached"] == 1 and c.stats["cache_hits"] == 1


def test_range_request(server):
    r = net.HttpClient().get(server + "/big", range_bytes=1000, cache=False)
    assert len(r.data) == 1000


def test_cancel(server):
    ev = threading.Event()
    ev.set()
    with pytest.raises(net.Cancelled):
        net.HttpClient(cancel=ev).get(server + "/x")


def test_per_host_rate_limit(server, monkeypatch):
    monkeypatch.setitem(net.HOST_INTERVALS, "127.0.0.1", 0.2)
    c = net.HttpClient()
    t0 = time.monotonic()
    for i in range(3):
        c.get(server + f"/r{i}", cache=False)
    assert time.monotonic() - t0 >= 0.39


def test_redact_url():
    assert net.redact_url("https://x/api?api_key=SECRET&q=1") == "https://x/api?api_key=%2A%2A%2A&q=1"
    assert "SECRET" not in net.redact_url("https://www.theaudiodb.com/api/v1/json/SECRET/album-mb.php?i=1")
