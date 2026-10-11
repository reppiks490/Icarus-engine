"""Encrypted, content-addressed vault for the derived Databento depth caches.

Why this exists: the reduced order-book features (1-minute microstructure rows and
event-level resilience rows) lived only in the GitHub Actions cache, and the raw
DBN they came from is deleted after reduction. On 2026-10-10 the NQ MBP-10 sweep
cache was evicted ("Cache not found for input keys: databento-sweep-"), losing 18
paid regular-session days. The sweep ledger still counts those days as held, so
they are never bought again. A cache is not storage.

The repository is public and the rows are licensed vendor derivatives, so they are
never committed in the clear. Each file is compressed, encrypted with AES-256-GCM
and stored under the SHA-256 of its plaintext; the plaintext hash is also bound in
as associated data, so a swapped or truncated object fails authentication instead
of restoring the wrong day. Only new content is written, so re-sealing an
unchanged cache produces no commit.

Key: ``ICARUS_DATA_ARCHIVE_KEY`` (base64, 32 bytes) when set -- the same secret the
provider archive uses -- otherwise HKDF of ``DATABENTO_API_KEY``. The manifest
records which, never the key. Rotating the Databento key without the archive key
set makes older objects unreadable, which is why the archive key is preferred.

Raw DBN (``_raw_tmp``, ``_retry_raw``) is never sealed: it is large, and keeping it
is a licensing decision this tool does not make.

The vault also holds the 13-market 5-minute panel (``data/panel``), a preserved original
pulled from Polygon in September 2026 that must not sit in the public tree as plain CSV.

Provenance is explicit, never guessed. ``sources.json`` is written by hand: per cache, whether it
is a ``new_acquisition`` or a ``preserved_original``, the provider and the evidence.
``label`` turns it into ``origins.json``, one record per object, with the purchase time copied
from the matching spend-ledger entry where one exists and ``null`` where none does.
``verify`` decrypts every object in memory, checks it against its manifest hash and its
label, and writes no plaintext anywhere.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import zlib
from datetime import datetime, timezone
from pathlib import Path

VAULT_DIR = Path("data/depth_vault")
SCHEMA = "icarus.depth_vault/1"
SKIP_DIRS = {"_raw_tmp", "_retry_raw"}
SUFFIXES = (".csv.gz", ".json")
LEDGERS = Path("automation_intelligence/cl_lab/spend")
ORIGINS = ("new_acquisition", "preserved_original")
# features/<account>/<schema>/<root>/<market day>.csv.gz, as written by the depth and sweep lanes.
_FEATURE = re.compile(r"^features/(?P<account>\w+)/(?P<schema>\w+)/(?P<root>\w+)/(?P<day>\d{4}-\d{2}-\d{2})\.csv\.gz$")
_DAY = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _key(env) -> tuple[bytes, str]:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    encoded = env.get("ICARUS_DATA_ARCHIVE_KEY", "").strip()
    if encoded:
        key = base64.b64decode(encoded, validate=True)
        if len(key) != 32:
            raise ValueError("ICARUS_DATA_ARCHIVE_KEY must decode to 32 bytes")
        return key, "ICARUS_DATA_ARCHIVE_KEY"
    source = env.get("DATABENTO_API_KEY", "").strip()
    if not source:
        raise ValueError("depth vault needs ICARUS_DATA_ARCHIVE_KEY or DATABENTO_API_KEY")
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"icarus-depth-vault-v1",
               info=b"databento-depth").derive(source.encode())
    return key, "HKDF(DATABENTO_API_KEY)"


def _files(cache: Path, suffixes=SUFFIXES):
    for path in sorted(cache.rglob("*")):
        if not path.is_file() or not path.name.endswith(tuple(suffixes)):
            continue
        rel = path.relative_to(cache)
        if rel.parts[0] in SKIP_DIRS or path.name.endswith(".tmp"):
            continue
        yield rel.as_posix(), path


def _load_manifest(vault: Path) -> dict:
    path = vault / "manifest.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"schema": SCHEMA, "caches": {}}


def seal(caches: dict[str, Path], vault: Path = VAULT_DIR, env=os.environ, suffixes=SUFFIXES) -> dict:
    """Encrypt every file in ``caches`` ({name: dir}) ending in ``suffixes`` that the vault lacks."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key, key_source = _key(env)
    aead = AESGCM(key)
    manifest = _load_manifest(vault)
    if manifest.get("key_source") not in (None, key_source):
        raise ValueError(f"vault was sealed with {manifest['key_source']}, not {key_source}")
    manifest["key_source"] = key_source
    objects = vault / "objects"
    objects.mkdir(parents=True, exist_ok=True)
    added = 0
    for name, cache in caches.items():
        if not Path(cache).is_dir():
            continue
        entries = manifest["caches"].setdefault(name, {})
        for rel, path in _files(Path(cache), suffixes):
            plain = path.read_bytes()
            digest = hashlib.sha256(plain).hexdigest()
            obj = objects / f"{digest}.bin"
            if not obj.exists():
                nonce = os.urandom(12)
                obj.write_bytes(nonce + aead.encrypt(nonce, zlib.compress(plain, 9), digest.encode()))
                added += 1
            entries[rel] = {"sha256": digest, "bytes": len(plain)}
    (vault / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    total = sum(len(v) for v in manifest["caches"].values())
    return {"added_objects": added, "files": total, "key_source": key_source}


def restore(caches: dict[str, Path], vault: Path = VAULT_DIR, env=os.environ) -> dict:
    """Write every vaulted file missing from ``caches``; a present file is never overwritten."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    manifest = _load_manifest(vault)
    if not manifest["caches"]:
        return {"restored": 0, "present": 0}
    key, key_source = _key(env)
    if manifest.get("key_source") not in (None, key_source):
        raise ValueError(f"vault was sealed with {manifest['key_source']}, not {key_source}")
    aead = AESGCM(key)
    restored = present = 0
    for name, entries in manifest["caches"].items():
        if name not in caches:
            continue
        root = Path(caches[name])
        for rel, meta in entries.items():
            dest = root / rel
            if dest.exists():
                present += 1
                continue
            blob = (vault / "objects" / f"{meta['sha256']}.bin").read_bytes()
            plain = zlib.decompress(aead.decrypt(blob[:12], blob[12:], meta["sha256"].encode()))
            if hashlib.sha256(plain).hexdigest() != meta["sha256"]:
                raise ValueError(f"vault object for {name}/{rel} does not match its manifest hash")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".vault-tmp")
            tmp.write_bytes(plain)
            os.replace(tmp, dest)
            restored += 1
    return {"restored": restored, "present": present}


def _ledger_entries(ledger_dir: Path) -> list[tuple[str, int, dict, str]]:
    out = []
    for path in sorted(Path(ledger_dir).glob("*.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for i, entry in enumerate(d.get("entries") or []):
            out.append((path.as_posix(), i, entry, str(d.get("account") or "")))
    return out


def _purchase(rel: str, entries) -> tuple[str | None, str]:
    """The ledger purchase time for one feature file, or None and the reason there is none.

    A match needs the same root, schema, market day and buying account. Anything other than
    exactly one match is reported, not resolved by guessing.
    """
    m = _FEATURE.match(rel)
    if not m:
        return None, "not a per-day feature file"
    want = [m["root"].upper(), m["schema"].replace("-", "").lower(), m["day"]]
    hits = []
    for path, i, entry, account in entries:
        words = str(entry.get("what") or "").split()
        if len(words) >= 3 and [words[0].upper(), words[1].replace("-", "").lower(), words[2]] == want \
                and account == m["account"]:
            hits.append((path, i, entry))
    if len(hits) == 1:
        path, i, entry = hits[0]
        return entry.get("at"), f"{path}#entries[{i}]"
    return None, "no ledger entry" if not hits else f"{len(hits)} ledger entries match"


def label(vault: Path = VAULT_DIR, ledger_dir: Path = LEDGERS) -> dict:
    """Write ``origins.json``: one provenance record per vaulted object, from ``sources.json`` and the ledgers."""
    manifest = _load_manifest(vault)
    sources = json.loads((vault / "sources.json").read_text(encoding="utf-8")).get("caches", {})
    entries = _ledger_entries(ledger_dir)
    objects, unlabelled = {}, []
    for name, files in sorted(manifest["caches"].items()):
        src = sources.get(name) or {}
        if src.get("origin") not in ORIGINS:
            unlabelled.append(name)
        for rel, meta in sorted(files.items()):
            at, evidence = _purchase(rel, entries) if src.get("origin") == "new_acquisition" else (None, "see sources.json")
            day = _DAY.search(rel)
            objects[f"{name}/{rel}"] = {
                "sha256": meta["sha256"], "bytes": meta["bytes"],
                "origin": src.get("origin"), "provider": src.get("provider"),
                "market_day": day.group(1) if day else None,
                "purchased_at": at, "purchase_evidence": evidence,
            }
    out = {"schema": "icarus.vault_origins/1", "unlabelled_caches": unlabelled, "objects": objects,
           "execution_authorized": False}
    (vault / "origins.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return {"objects": len(objects), "unlabelled_caches": unlabelled,
            "purchased_at_known": sum(1 for o in objects.values() if o["purchased_at"])}


def verify(vault: Path = VAULT_DIR, env=os.environ, now: datetime | None = None) -> dict:
    """Decrypt every manifest object in memory and check hash and label. Writes nothing."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    manifest = _load_manifest(vault)
    origins_path = vault / "origins.json"
    origins = json.loads(origins_path.read_text(encoding="utf-8")).get("objects", {}) if origins_path.exists() else {}
    key, key_source = _key(env)
    if manifest.get("key_source") not in (None, key_source):
        raise ValueError(f"vault was sealed with {manifest['key_source']}, not {key_source}")
    aead = AESGCM(key)
    caches, failures, referenced = {}, [], set()
    for name, files in sorted(manifest["caches"].items()):
        ok = nbytes = unlabelled = 0
        for rel, meta in sorted(files.items()):
            referenced.add(meta["sha256"])
            obj = vault / "objects" / f"{meta['sha256']}.bin"
            try:
                blob = obj.read_bytes()
                plain = zlib.decompress(aead.decrypt(blob[:12], blob[12:], meta["sha256"].encode()))
                if hashlib.sha256(plain).hexdigest() != meta["sha256"] or len(plain) != meta["bytes"]:
                    raise ValueError("hash or size mismatch")
            except Exception as ex:  # noqa: BLE001 - every failure is reported by name
                failures.append(f"{name}/{rel}: {type(ex).__name__}")
                continue
            ok += 1
            nbytes += len(plain)
            if (origins.get(f"{name}/{rel}") or {}).get("origin") not in ORIGINS:
                unlabelled += 1
        caches[name] = {"files": len(files), "authenticated": ok, "plaintext_bytes": nbytes, "unlabelled": unlabelled}
    stored = {p.stem for p in (vault / "objects").glob("*.bin")} if (vault / "objects").is_dir() else set()
    unlabelled_total = sum(c["unlabelled"] for c in caches.values())
    verdict = "OK" if not failures and not unlabelled_total else "FAILED"
    return {"schema": "icarus.vault_verify/1", "verdict": verdict, "key_source": key_source,
            "verified_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
            "caches": caches, "failures": failures[:50], "failure_count": len(failures),
            "unreferenced_objects": len(stored - referenced), "plaintext_written": False,
            "execution_authorized": False}


def write_receipt(path: Path, receipt: dict, refresh_h: float = 24.0) -> bool:
    """Write the verify receipt when anything but its timestamp changed, or once a day."""
    path = Path(path)
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = None
    if old:
        same = {k: v for k, v in old.items() if k != "verified_at"} == {k: v for k, v in receipt.items() if k != "verified_at"}
        age_h = (datetime.fromisoformat(receipt["verified_at"]) - datetime.fromisoformat(old["verified_at"])).total_seconds() / 3600
        if same and age_h < refresh_h:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return True


def _caches(pairs: list[str]) -> dict[str, Path]:
    out = {}
    for pair in pairs:
        name, _, path = pair.partition("=")
        if not name or not path:
            raise SystemExit(f"--cache wants NAME=DIR, got {pair!r}")
        out[name] = Path(path)
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=("seal", "restore", "label", "verify"))
    ap.add_argument("--cache", action="append", default=[], help="NAME=DIR, repeatable (seal, restore)")
    ap.add_argument("--suffix", action="append", help=f"file endings to seal (default {', '.join(SUFFIXES)})")
    ap.add_argument("--vault", type=Path, default=VAULT_DIR)
    ap.add_argument("--ledgers", type=Path, default=LEDGERS)
    ap.add_argument("--out", type=Path, help="verify: write the receipt here")
    a = ap.parse_args(argv)
    if a.action in ("seal", "restore") and not a.cache:
        ap.error(f"{a.action} needs at least one --cache NAME=DIR")
    if a.action == "seal":
        result = seal(_caches(a.cache), a.vault, suffixes=tuple(a.suffix or SUFFIXES))
    elif a.action == "restore":
        result = restore(_caches(a.cache), a.vault)
    elif a.action == "label":
        result = label(a.vault, a.ledgers)
    else:
        result = verify(a.vault)
        if a.out:
            result["receipt_written"] = write_receipt(a.out, {k: v for k, v in result.items()})
        print(json.dumps({k: result[k] for k in ("verdict", "caches", "failure_count", "unreferenced_objects")}))
        if result["verdict"] != "OK":
            raise SystemExit(1)
        return
    print(json.dumps(result))


if __name__ == "__main__":
    main()
