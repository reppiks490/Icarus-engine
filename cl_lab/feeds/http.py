# CL (Claude, Anthropic) — 2026-10-03 — cl_lab.feeds.http: polite stdlib HTTP GET with retries and a request budget
from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; icarus-cl-lab/0.1; +https://github.com/reppiks490/Icarus-engine)"
MAX_REQUESTS = 400
_used = 0


class FeedError(RuntimeError):
    pass


def get_bytes(url, params=None, headers=None, timeout=30, retries=3, backoff=2.0) -> bytes:
    """GET with retry on 429/5xx/network errors; honours HTTPS_PROXY via urllib's env proxy handler."""
    global _used
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    last = None
    for attempt in range(retries + 1):
        if _used >= MAX_REQUESTS:
            raise FeedError(f"request budget {MAX_REQUESTS} exhausted")
        _used += 1
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} for {url}"
            if e.code not in (429, 500, 502, 503, 504):
                raise FeedError(last) from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = f"{type(e).__name__}: {e} for {url}"
        if attempt < retries:
            time.sleep(backoff ** attempt)
    raise FeedError(last or f"failed: {url}")
