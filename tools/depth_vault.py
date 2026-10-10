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
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import zlib
from pathlib import Path

VAULT_DIR = Path("data/depth_vault")
SCHEMA = "icarus.depth_vault/1"
SKIP_DIRS = {"_raw_tmp", "_retry_raw"}
SUFFIXES = (".csv.gz", ".json")


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


def _files(cache: Path):
    for path in sorted(cache.rglob("*")):
        if not path.is_file() or not path.name.endswith(SUFFIXES):
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


def seal(caches: dict[str, Path], vault: Path = VAULT_DIR, env=os.environ) -> dict:
    """Encrypt every derived file in ``caches`` ({name: dir}) that the vault lacks."""
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
        for rel, path in _files(Path(cache)):
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
    ap.add_argument("action", choices=("seal", "restore"))
    ap.add_argument("--cache", action="append", required=True, help="NAME=DIR, repeatable")
    ap.add_argument("--vault", type=Path, default=VAULT_DIR)
    a = ap.parse_args(argv)
    fn = seal if a.action == "seal" else restore
    print(json.dumps(fn(_caches(a.cache), a.vault)))


if __name__ == "__main__":
    main()
