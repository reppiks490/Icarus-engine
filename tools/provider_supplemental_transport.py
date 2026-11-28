"""Hardened transport adapter for supplemental ICARUS providers.

Keeps the additive provider catalog/state model in provider_supplemental_collection
while handling Unusual Whales' provider-specific cursor semantics without weakening
the K1 secret-name filter.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

from tools import provider_exhaustive_collection as core
from tools import provider_supplemental_collection as base


def _container(data):
    if not isinstance(data, dict):
        return {}
    nested = data.get("data")
    return nested if isinstance(nested, dict) else data


def _uw_next_page(data, current):
    # Pinned official UW docs define list_tokens with limit only (max 1000),
    # and no cursor/page parameter. In our catalog that call is uniquely bound
    # as {limit: 1000}; it is therefore terminal even if response metadata
    # contains a URL-like field that the generic K1 parser could misclassify.
    if current == {"limit": 1000}:
        return None

    container = _container(data)
    token = container.get("next_token") or container.get("nextToken")
    if token:
        return {"params": {**current, "next_token": token}}

    next_url = container.get("next_url")
    if isinstance(next_url, str) and next_url:
        parsed = urlsplit(next_url)
        if parsed.scheme or parsed.netloc:
            # Only the Unusual Whales API authority is allowed for absolute cursors.
            if parsed.scheme != "https" or parsed.netloc != "api.unusualwhales.com" or parsed.username or parsed.password:
                raise ValueError("unsafe Unusual Whales pagination authority")
        elif not next_url.startswith("/"):
            raise ValueError("unsafe Unusual Whales pagination path")
        params = {}
        for key, value in parse_qsl(parsed.query):
            # next_token is a pagination cursor, not an account credential.
            if key == "next_token" or not core.SECRET.search(key):
                params[key] = value
        return {"path": parsed.path, "params": params}

    # UW page/offset endpoints explicitly carry these counters in the request.
    if current.get("limit"):
        count = len(base.rows(data))
        limit = int(current["limit"])
        if count >= limit:
            if "page" in current:
                return {"params": {**current, "page": int(current["page"]) + 1}}
            if "offset" in current:
                return {"params": {**current, "offset": int(current["offset"]) + 1}}

    # Important: do not fall through to K1 generic next_url logic. Some UW
    # response metadata is not a collection cursor.
    return None


def next_page(provider, data, current):
    if provider == "unusual_whales":
        return _uw_next_page(data, current)
    return base.next_page(provider, data, current)


def request(provider, path, params, key):
    if provider != "unusual_whales":
        return base.request(provider, path, params, key)

    spec = core.PROVIDERS[provider]
    # Resource names (for example list_tokens) are not credential fields.
    # Keep query data separate and reject ambiguous/encoded URL structure.
    if (
        not path.startswith("/") or path.startswith("//")
        or "://" in path or ".." in path
        or any(char in path for char in "?#\\%")
        or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in path)
    ):
        raise ValueError("unsafe path")

    safe = {}
    for name, value in params.items():
        if value is None:
            continue
        # UW's documented next_token is an opaque cursor, not authentication.
        if name == "next_token" or not core.SECRET.search(name):
            safe[name] = value

    headers = {
        "User-Agent": "ICARUS-catalog-acquisition/1",
        "Accept": "application/json",
        "Authorization": "Bearer " + key,
    }
    url = spec["base"] + path + ("?" + urlencode(safe, doseq=True) if safe else "")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise core.ProviderFailure("REDIRECT_BLOCKED")

    with urllib.request.build_opener(NoRedirect).open(
        urllib.request.Request(url, headers=headers), timeout=20
    ) as response:
        raw = response.read(20_000_001)
    if len(raw) > 20_000_000:
        raise core.ProviderFailure("PAYLOAD_LIMIT_INCOMPLETE")
    return json.loads(raw)


def run_cycle(root: Path, provider: str, env: dict[str, str], *, run_id: str, request_budget: int = 20, delay_seconds: float = 13):
    base.install_extensions()
    core.next_page = next_page
    return core.cycle(
        root,
        base.load_operations(root, provider),
        env,
        run_id=run_id,
        request_budget=request_budget,
        fetch=request,
        delay_seconds=delay_seconds,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--request-budget", type=int, default=20)
    parser.add_argument("--delay-seconds", type=float, default=13)
    parser.add_argument("--provider", required=True, choices=sorted(base.EXTENDED_PROVIDERS))
    args = parser.parse_args()
    result = run_cycle(
        args.root,
        args.provider,
        dict(os.environ),
        run_id=args.run_id,
        request_budget=args.request_budget,
        delay_seconds=args.delay_seconds,
    )
    print(json.dumps({
        "providers": {name: state["status"] for name, state in result["providers"].items()},
        "requests": result["requests"],
        "coverage": result["catalog"],
    }))


if __name__ == "__main__":
    main()
