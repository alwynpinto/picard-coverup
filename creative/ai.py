# -*- coding: utf-8 -*-
# CoverUp: MusicBrainz Picard plugin. GPL-2.0-or-later.
"""AI image-generation backends. All are configured by the user with their own endpoint and key;
CoverUp bundles and hosts nothing.

- automatic1111: a local Stable Diffusion web UI started with ``--api`` (``/sdapi/v1/txt2img``, ``img2img``)
- openai: any OpenAI-compatible ``/v1/images/generations`` endpoint
- custom: POST JSON ``{prompt, negative_prompt, width, height, seed, n}``; the response may contain
  ``images: [base64]``, ``image: base64`` or ``data: [{b64_json | url}]``
"""

from __future__ import annotations

import base64
import ipaddress
import logging
import urllib.parse
from dataclasses import dataclass

from ..net import HttpClient, HttpError

log = logging.getLogger("coverup.creative.ai")

BACKENDS = ("none", "automatic1111", "openai", "custom")


@dataclass
class GenRequest:
    prompt: str
    negative: str
    size: int
    seed: int
    n: int = 1
    reference: bytes | None = None  # image-to-image source (e.g. the low-resolution cover)
    strength: float = 0.55  # img2img denoising: lower stays closer to the reference


def is_remote(url: str) -> bool:
    """True unless the host is localhost or a private/LAN address."""
    host = urllib.parse.urlsplit(url).hostname or ""
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local)
    except ValueError:
        return True


def host_of(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or url


def _b64(s: str) -> bytes:
    if "," in s[:100] and s.startswith("data:"):
        s = s.split(",", 1)[1]
    return base64.b64decode(s)


def decode_images(payload, http: HttpClient | None = None) -> list[bytes]:
    """Accept the common response shapes of image APIs."""
    out: list[bytes] = []
    if not isinstance(payload, dict):
        return out
    for img in payload.get("images") or []:
        if isinstance(img, str):
            out.append(_b64(img))
    if isinstance(payload.get("image"), str):
        out.append(_b64(payload["image"]))
    for item in payload.get("data") or []:
        if isinstance(item, dict):
            if item.get("b64_json"):
                out.append(_b64(item["b64_json"]))
            elif item.get("url") and http is not None:
                out.append(http.get(item["url"], cache=False).data)
    return out


class Backend:
    NAME = "none"

    def __init__(self, http: HttpClient, url: str, api_key: str = "", model: str = "", steps: int = 30):
        self.http = http
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.steps = steps

    def supports_img2img(self) -> bool:
        return False

    def generate(self, req: GenRequest) -> list[bytes]:
        raise NotImplementedError


class Automatic1111(Backend):
    NAME = "automatic1111"

    def supports_img2img(self) -> bool:
        return True

    def generate(self, req: GenRequest) -> list[bytes]:
        body = {
            "prompt": req.prompt,
            "negative_prompt": req.negative,
            "width": req.size,
            "height": req.size,
            "seed": req.seed,
            "steps": self.steps,
            "batch_size": req.n,
            "n_iter": 1,
        }
        endpoint = "/sdapi/v1/txt2img"
        if req.reference:
            body["init_images"] = [base64.b64encode(req.reference).decode("ascii")]
            body["denoising_strength"] = req.strength
            endpoint = "/sdapi/v1/img2img"
        if self.model:
            body["override_settings"] = {"sd_model_checkpoint": self.model}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        return decode_images(self.http.post_json(self.url + endpoint, body, headers, timeout=600))


class OpenAICompatible(Backend):
    NAME = "openai"

    def generate(self, req: GenRequest) -> list[bytes]:
        base = self.url if self.url.endswith("/v1") else self.url + "/v1"
        body = {
            "prompt": f"{req.prompt}\nAvoid: {req.negative}",
            "n": req.n,
            "size": f"{req.size}x{req.size}",
        }
        if self.model:
            body["model"] = self.model
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            payload = self.http.post_json(base + "/images/generations", body, headers, timeout=600)
        except HttpError as exc:
            if exc.status == 400 and req.n > 1:  # some models only allow n=1
                out = []
                for _ in range(req.n):
                    out += decode_images(self.http.post_json(base + "/images/generations", {**body, "n": 1}, headers, timeout=600), self.http)
                return out
            raise
        return decode_images(payload, self.http)


class CustomHttp(Backend):
    NAME = "custom"

    def supports_img2img(self) -> bool:
        return True

    def generate(self, req: GenRequest) -> list[bytes]:
        body = {
            "prompt": req.prompt, "negative_prompt": req.negative, "width": req.size, "height": req.size,
            "seed": req.seed, "n": req.n, "model": self.model or None,
        }
        if req.reference:
            body["init_image"] = base64.b64encode(req.reference).decode("ascii")
            body["strength"] = req.strength
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        return decode_images(self.http.post_json(self.url, body, headers, timeout=600), self.http)


def make_backend(name: str, http: HttpClient, settings) -> Backend | None:
    cls = {"automatic1111": Automatic1111, "openai": OpenAICompatible, "custom": CustomHttp}.get(name)
    if not cls:
        return None
    return cls(http, settings["ai_url"], settings["ai_api_key"], settings["ai_model"], int(settings["ai_steps"]))
