"""Encrypted, content-addressed vault for licensed ICARUS research data.

The reduced Databento depth caches and the preserved vendor asset panel must not
live only in ephemeral caches or as plaintext in a public repository. Files are
compressed, encrypted with AES-256-GCM and stored under the SHA-256 of their
plaintext. The plaintext digest is authenticated as associated data, so swapped
or truncated objects fail closed.

Key: ``ICARUS_DATA_ARCHIVE_KEY`` (base64, 32 bytes) when set -- the same secret the
provider archive uses -- otherwise HKDF of ``DATABENTO_API_KEY``. The manifest
records only the key *source name*, never secret material.

Raw DBN (``_raw_tmp``, ``_retry_raw``) is never sealed: retaining raw licensed data
is a separate licensing decision this tool does not make.
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
from pathlib import Path, PurePosixPath

VAULT_DIR = Path("data/depth_vault")
SCHEMA = "icarus.depth_vault/1"
SKIP_DIRS = {"_raw_tmp", "_retry_raw"}
SUFFIXES = (".csv.gz", ".json")
LEDGERS = Path("automation_intelligence/cl_lab/spend")
ORIGINS = ("new_acquisition", "preserved_original")
_FEATURE = re.compile(
    r"^features/(?P<account>\w+)/(?P<schema>\w+)/(?P<root>\w+)/(?P<day>\d{4}-\d{2}-\d{2})\.csv\.gz$"
)
_DAY = re.compile(r"(\d{4}-\d{2}-\d{2})")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"icarus-depth-vault-v1",
        info=b"databento-depth",
    ).derive(source.encode())
    return key, "HKDF(DATABENTO_API_KEY)"


def _files(cache: Path, suffixes=SUFFIXES):
    suffixes = tuple(suffixes)
    for path in sorted(cache.rglob("*")):
        if not path.is_file() or not path.name.endswith(suffixes):
            continue
        rel = path.relative_to(cache)
        if rel.parts and rel.parts[0] in SKIP_DIRS or path.name.endswith(".tmp"):
            continue
        yield rel.as_posix(), path


def _load_manifest(vault: Path) -> dict:
    path = vault / "manifest.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"schema": SCHEMA, "caches": {}}


def seal(
    caches: dict[str, Path],
    vault: Path = VAULT_DIR,
    env=os.environ,
    suffixes=SUFFIXES,
) -> dict:
    """Encrypt files in ``caches`` that match ``suffixes`` and are not already vaulted."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key, key_source = _key(env)
    aead = AESGCM(key)
    manifest = _load_manifest(vault)
    if manifest.get("key_source") not in (None, key_source):
        raise ValueError(f"vault was sealed with {manifest['key_source']}, not {key_source}")
    manifest["key_source"] = key_source
    manifest.setdefault("schema", SCHEMA)
    manifest.setdefault("caches", {})
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
    text = json.dumps(manifest, indent=1, sort_keys=True) + "\n"
    manifest_path = vault / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if not manifest_path.exists() or manifest_path.read_text(encoding="utf-8") != text:
        manifest_path.write_text(text, encoding="utf-8")
    total = sum(len(v) for v in manifest["caches"].values())
    return {"added_objects": added, "files": total, "key_source": key_source}


def _object_name(meta: dict) -> str:
    digest = str(meta.get("sha256") or "")
    if not _SHA256.fullmatch(digest):
        raise ValueError(f"vault manifest hash is malformed: {digest[:80]!r}")
    return f"{digest}.bin"


def _safe_dest(root: Path, rel: str) -> Path:
    """Return a restore target under ``root``; reject traversal and symlink escapes."""
    pure = PurePosixPath(rel)
    if not rel or "\\" in rel or pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"vault manifest path escapes its cache: {rel!r}")
    base = Path(root).resolve()
    target = (Path(root) / pure).resolve()
    if target != base and base not in target.parents:
        raise ValueError(f"vault manifest path escapes its cache: {rel!r}")
    return Path(root) / pure


def restore(caches: dict[str, Path], vault: Path = VAULT_DIR, env=os.environ) -> dict:
    """Restore missing vaulted files. Existing files are never overwritten."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    manifest = _load_manifest(vault)
    if not manifest.get("caches"):
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
            dest = _safe_dest(root, rel)
            obj_name = _object_name(meta)
            if dest.exists():
                present += 1
                continue
            blob = (vault / "objects" / obj_name).read_bytes()
            if len(blob) < 13:
                raise ValueError(f"vault object for {name}/{rel} is truncated")
            plain = zlib.decompress(aead.decrypt(blob[:12], blob[12:], meta["sha256"].encode()))
            if hashlib.sha256(plain).hexdigest() != meta["sha256"] or len(plain) != int(meta["bytes"]):
                raise ValueError(f"vault object for {name}/{rel} does not match its manifest")
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
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for i, entry in enumerate(doc.get("entries") or []):
            out.append((path.as_posix(), i, entry, str(doc.get("account") or "")))
    return out


def _purchase(rel: str, entries) -> tuple[str | None, str]:
    match = _FEATURE.match(rel)
    if not match:
        return None, "not a per-day feature file"
    want = [match["root"].upper(), match["schema"].replace("-", "").lower(), match["day"]]
    hits = []
    for path, i, entry, account in entries:
        words = str(entry.get("what") or "").split()
        normalized = [words[0].upper(), words[1].replace("-", "").lower(), words[2]] if len(words) >= 3 else []
        if normalized == want and account == match["account"]:
            hits.append((path, i, entry))
    if len(hits) == 1:
        path, i, entry = hits[0]
        return entry.get("at"), f"{path}#entries[{i}]"
    return None, "no ledger entry" if not hits else f"{len(hits)} ledger entries match"


def _load_sources(vault: Path) -> dict:
    try:
        return json.loads((vault / "sources.json").read_text(encoding="utf-8")).get("caches", {})
    except (OSError, ValueError):
        return {}


def _build_origins(vault: Path, ledger_dir: Path) -> dict:
    manifest = _load_manifest(vault)
    sources = _load_sources(vault)
    entries = _ledger_entries(ledger_dir)
    objects: dict[str, dict] = {}
    unlabelled = []
    for name, files in sorted((manifest.get("caches") or {}).items()):
        src = sources.get(name) or {}
        origin = src.get("origin")
        if origin not in ORIGINS:
            unlabelled.append(name)
        for rel, meta in sorted(files.items()):
            if origin == "new_acquisition":
                purchased_at, purchase_evidence = _purchase(rel, entries)
            else:
                purchased_at, purchase_evidence = None, "see sources.json"
            day = _DAY.search(rel)
            objects[f"{name}/{rel}"] = {
                "sha256": meta.get("sha256"),
                "bytes": meta.get("bytes"),
                "origin": origin,
                "provider": src.get("provider"),
                "market_day": day.group(1) if day else None,
                "purchased_at": purchased_at,
                "purchase_evidence": purchase_evidence,
            }
    return {
        "schema": "icarus.vault_origins/1",
        "unlabelled_caches": sorted(set(unlabelled)),
        "objects": objects,
        "execution_authorized": False,
    }


def label(vault: Path = VAULT_DIR, ledger_dir: Path = LEDGERS) -> dict:
    """Write deterministic per-object provenance from sources.json and spend ledgers."""
    out = _build_origins(vault, ledger_dir)
    (vault / "origins.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    objects = out["objects"]
    return {
        "objects": len(objects),
        "unlabelled_caches": out["unlabelled_caches"],
        "purchased_at_known": sum(1 for row in objects.values() if row.get("purchased_at")),
    }


def verify(
    vault: Path = VAULT_DIR,
    env=os.environ,
    now: datetime | None = None,
    ledger_dir: Path = LEDGERS,
) -> dict:
    """Authenticate every manifest object in memory and compare deterministic provenance labels."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    manifest = _load_manifest(vault)
    key, key_source = _key(env)
    if manifest.get("key_source") not in (None, key_source):
        raise ValueError(f"vault was sealed with {manifest['key_source']}, not {key_source}")
    aead = AESGCM(key)
    try:
        origins = json.loads((vault / "origins.json").read_text(encoding="utf-8")).get("objects", {})
    except (OSError, ValueError):
        origins = {}
    expected_doc = _build_origins(vault, ledger_dir)
    expected = expected_doc["objects"]
    caches = {}
    failures = []
    mismatches = []
    referenced = set()
    for name, files in sorted((manifest.get("caches") or {}).items()):
        authenticated = nbytes = bad_labels = 0
        for rel, meta in sorted(files.items()):
            record_key = f"{name}/{rel}"
            want = expected.get(record_key) or {}
            got = origins.get(record_key)
            if got != want or want.get("origin") not in ORIGINS:
                bad_labels += 1
                fields = sorted(k for k in set(want) | set(got or {}) if (got or {}).get(k) != want.get(k))
                mismatches.append(f"{record_key}: {', '.join(fields) or 'origin not allowed'}")
            try:
                obj_name = _object_name(meta)
                referenced.add(meta["sha256"])
                blob = (vault / "objects" / obj_name).read_bytes()
                if len(blob) < 13:
                    raise ValueError("truncated ciphertext")
                plain = zlib.decompress(aead.decrypt(blob[:12], blob[12:], meta["sha256"].encode()))
                if hashlib.sha256(plain).hexdigest() != meta["sha256"] or len(plain) != int(meta["bytes"]):
                    raise ValueError("hash or size mismatch")
            except Exception as ex:  # report type only; never payload or key material
                failures.append(f"{name}/{rel}: {type(ex).__name__}")
                continue
            authenticated += 1
            nbytes += len(plain)
        caches[name] = {
            "files": len(files),
            "authenticated": authenticated,
            "plaintext_bytes": nbytes,
            "label_mismatches": bad_labels,
        }
    stale = sorted(set(origins) - set(expected))
    mismatches.extend(f"{key}: label for an object the manifest does not hold" for key in stale)
    stored = {p.stem for p in (vault / "objects").glob("*.bin")} if (vault / "objects").is_dir() else set()
    verdict = "OK" if not failures and not mismatches and not expected_doc["unlabelled_caches"] else "FAILED"
    return {
        "schema": "icarus.vault_verify/1",
        "verdict": verdict,
        "key_source": key_source,
        "verified_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "caches": caches,
        "failures": failures[:50],
        "failure_count": len(failures),
        "label_mismatches": mismatches[:50],
        "label_mismatch_count": len(mismatches),
        "unlabelled_caches": expected_doc["unlabelled_caches"],
        "unreferenced_objects": len(stored - referenced),
        "plaintext_written": False,
        "execution_authorized": False,
    }


def write_receipt(path: Path, receipt: dict, refresh_h: float = 24.0) -> bool:
    """Persist verification when content changes or the prior receipt is at least refresh_h old."""
    path = Path(path)
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = None
    if old:
        old_no_time = {k: v for k, v in old.items() if k != "verified_at"}
        new_no_time = {k: v for k, v in receipt.items() if k != "verified_at"}
        try:
            age_h = (
                datetime.fromisoformat(receipt["verified_at"]) - datetime.fromisoformat(old["verified_at"])
            ).total_seconds() / 3600
        except (KeyError, TypeError, ValueError):
            age_h = refresh_h
        if old_no_time == new_no_time and age_h < refresh_h:
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
    ap.add_argument("--cache", action="append", default=[], help="NAME=DIR, repeatable (seal/restore)")
    ap.add_argument("--suffix", action="append", help=f"file ending to seal; repeatable (default {', '.join(SUFFIXES)})")
    ap.add_argument("--vault", type=Path, default=VAULT_DIR)
    ap.add_argument("--ledgers", type=Path, default=LEDGERS)
    ap.add_argument("--out", type=Path, help="verify: write receipt to this path")
    args = ap.parse_args(argv)
    if args.action in ("seal", "restore") and not args.cache:
        ap.error(f"{args.action} needs at least one --cache NAME=DIR")
    if args.action == "seal":
        result = seal(_caches(args.cache), args.vault, suffixes=tuple(args.suffix or SUFFIXES))
    elif args.action == "restore":
        result = restore(_caches(args.cache), args.vault)
    elif args.action == "label":
        result = label(args.vault, args.ledgers)
    else:
        result = verify(args.vault, ledger_dir=args.ledgers)
        if args.out:
            result["receipt_written"] = write_receipt(args.out, result)
        print(json.dumps({
            "verdict": result["verdict"],
            "caches": result["caches"],
            "failure_count": result["failure_count"],
            "label_mismatch_count": result["label_mismatch_count"],
            "unlabelled_caches": result["unlabelled_caches"],
            "unreferenced_objects": result["unreferenced_objects"],
        }))
        if result["verdict"] != "OK":
            raise SystemExit(1)
        return
    print(json.dumps(result))


if __name__ == "__main__":
    main()
