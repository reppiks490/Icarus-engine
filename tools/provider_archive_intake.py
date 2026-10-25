"""Bounded offline private provider intake. Never acquires data or authorizes trades."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import zipfile
import zlib
from tools.provider_credentials import provider_credential

MAX_BYTES = 32_000_000
MAX_NODES = 500_000
MAX_CHECKPOINT_DB_BYTES = 384_000_000
MAX_CHECKPOINT_JSON_BYTES = 512_000_000
PROVIDERS = {'massive','twelve','fmp','eodhd','tiingo','intrinio','quiver','fred','alpaca','tickstream','bybit','alphavantage','finnhub','unusual_whales'}
NATIVE = {'alphavantage','finnhub','unusual_whales'}
SAFE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,110}\Z')
HEX = re.compile(r'[0-9a-f]{64}\Z')


def read_regular(path: Path, maximum=MAX_BYTES) -> bytes:
    if os.name != 'posix' or not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_NONBLOCK') or os.open not in os.supports_dir_fd:
        raise ValueError('secure POSIX file access unavailable')
    path = Path(path)
    # Walk directory descriptors so a symlink in any parent is also rejected.
    if '..' in path.parts:
        raise ValueError('parent traversal rejected')
    parent_fd = os.open('/' if path.is_absolute() else '.', os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        parts = path.parts[1:] if path.is_absolute() else path.parts
        if not parts:
            raise ValueError('file path required')
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0), dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = next_fd
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= maximum:
            raise ValueError('input size or type rejected')
        with os.fdopen(fd, 'rb', closefd=False) as file:
            data = file.read(maximum + 1)
        if len(data) > maximum or len(data) != info.st_size:
            raise ValueError('input changed or exceeded bound')
        return data
    finally:
        os.close(fd)


def _json(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    def integer(value):
        if len(value) > 128:
            raise ValueError('integer bound')
        return int(value)
    def floating(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('nonfinite JSON number')
        return result
    def reject(value):
        raise ValueError('nonfinite JSON constant')
    try:
        result = json.loads(raw, object_pairs_hook=pairs, parse_int=integer, parse_float=floating, parse_constant=reject)
    except (RecursionError, UnicodeError) as exc:
        raise ValueError('JSON rejected') from exc
    stack = [(result, 0)]
    count = 0
    while stack:
        value, depth = stack.pop()
        count += 1
        if count > MAX_NODES or depth > 32:
            raise ValueError('JSON structure bound')
        if isinstance(value, dict):
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)
    return result


def _authenticated_compressed(envelope: bytes, *, provider: str, run_id: str, job: str, format: str, env: dict):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    if provider not in PROVIDERS or format not in {'exhaustive','supplemental','native'}:
        raise ValueError('unsupported provider or format')
    if format == 'supplemental' and provider not in NATIVE:
        raise ValueError('supplemental provider rejected')
    if format == 'native' and (provider not in NATIVE or job != 'native-access'):
        raise ValueError('native identity rejected')
    if not SAFE_ID.fullmatch(run_id) or not SAFE_ID.fullmatch(job):
        raise ValueError('unsafe identity')
    if not 28 <= len(envelope) <= MAX_BYTES:
        raise ValueError('envelope size rejected')
    encoded = env.get('ICARUS_DATA_ARCHIVE_KEY', '').strip()
    if encoded:
        key = base64.b64decode(encoded, validate=True)
        if len(key) != 32:
            raise ValueError('archive key length rejected')
    else:
        credential = provider_credential(provider, env)
        if not credential:
            raise ValueError('archive credential unavailable')
        salt = b'icarus-native-provider-access-v1' if format == 'native' else b'icarus-provider-archive-v1'
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=provider.encode()).derive(credential.encode())
    try:
        compressed = AESGCM(key).decrypt(envelope[:12], envelope[12:], f'{run_id}:{provider}:{job}'.encode())
    except Exception:
        raise ValueError('archive authentication failed') from None
    return compressed


def decrypt(envelope: bytes, *, provider: str, run_id: str, job: str, format: str, env: dict):
    compressed = _authenticated_compressed(envelope, provider=provider, run_id=run_id, job=job, format=format, env=env)
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, MAX_BYTES + 1)
        if len(raw) > MAX_BYTES or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError('compressed payload rejected')
    except zlib.error:
        raise ValueError('compressed payload rejected') from None
    return _json(raw)


def _pinned(path, digest):
    if not isinstance(digest, str) or not HEX.fullmatch(digest):
        raise ValueError('SHA256 pin required')
    data = read_regular(Path(path))
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('input pin mismatch')
    return data



def checkpoint_bounds(*, checkpoint, checkpoint_sha256, provider, env,
                      maximum_output=512_000_000):
    """Count authenticated checkpoint bytes without parsing or exporting payloads.

    Each decompression allocation is at most 64 KiB. A diagnostic ceiling is
    independent of, and does not relax, normal intake limits. Truncated output
    reports a lower bound rather than an invented exact size.
    """
    if type(maximum_output) is not int or not 1 <= maximum_output <= 512_000_000:
        raise ValueError('diagnostic output bound rejected')
    envelope = _pinned(checkpoint, checkpoint_sha256)
    compressed = _authenticated_compressed(envelope, provider=provider,
        run_id='checkpoint', job=provider, format='exhaustive', env=env)
    decoder = zlib.decompressobj()
    total = 0
    limited = False
    try:
        for start in range(0, len(compressed), 65_536):
            pending = compressed[start:start + 65_536]
            while pending:
                block = decoder.decompress(pending, min(65_536, maximum_output - total + 1))
                total += len(block)
                if total > maximum_output:
                    limited = True
                    break
                pending = decoder.unconsumed_tail
                if decoder.unused_data:
                    raise ValueError('compressed payload rejected')
            if limited:
                break
        if not limited and (not decoder.eof or decoder.unused_data or decoder.unconsumed_tail):
            raise ValueError('compressed payload rejected')
    except zlib.error:
        raise ValueError('compressed payload rejected') from None
    return dict(encrypted_bytes=len(envelope), compressed_bytes=len(compressed),
                decompressed_bytes=total, decompressed_size_exact=not limited,
                diagnostic_limit_reached=limited, baseline_intake_limit_bytes=MAX_BYTES,
                baseline_intake_limit_exceeded=total > MAX_BYTES)


def _stream_checkpoint_database(compressed: bytes, destination: Path):
    """Stream one authenticated checkpoint JSON SQLite field into a private file.

    The ordinary provider payload limit remains MAX_BYTES. Checkpoint databases
    have a separate hard disk bound and are never materialized as a JSON string
    or an in-memory SQLite deserialize buffer.
    """
    prefix = (b'{', b'"sqlite"', b':', b'"')
    whitespace = b' \t\r\n'
    state = 'prefix'
    token_index = token_offset = 0
    carry = b''
    padded = False
    database_bytes = 0
    json_bytes = 0

    def write_base64(segment, output):
        nonlocal carry, padded, database_bytes
        if not segment:
            return
        if padded:
            raise ValueError('checkpoint database rejected')
        encoded = carry + segment
        complete = len(encoded) // 4 * 4
        if not complete:
            carry = encoded
            return
        chunk, carry = encoded[:complete], encoded[complete:]
        try:
            decoded = base64.b64decode(chunk, validate=True)
        except (ValueError, base64.binascii.Error):
            raise ValueError('checkpoint database rejected') from None
        if b'=' in chunk:
            if b'=' in chunk[:-4]:
                raise ValueError('checkpoint database rejected')
            padded = True
        database_bytes += len(decoded)
        if database_bytes > MAX_CHECKPOINT_DB_BYTES:
            raise ValueError('checkpoint database rejected')
        output.write(decoded)

    def feed(block, output):
        nonlocal state, token_index, token_offset, json_bytes
        json_bytes += len(block)
        if json_bytes > MAX_CHECKPOINT_JSON_BYTES:
            raise ValueError('compressed payload rejected')
        offset = 0
        while offset < len(block):
            if state == 'prefix':
                value = block[offset]
                offset += 1
                if token_offset == 0 and value in whitespace:
                    continue
                token = prefix[token_index]
                if value != token[token_offset]:
                    raise ValueError('checkpoint schema rejected')
                token_offset += 1
                if token_offset == len(token):
                    token_index += 1
                    token_offset = 0
                    if token_index == len(prefix):
                        state = 'base64'
            elif state == 'base64':
                ending = block.find(b'"', offset)
                stop = len(block) if ending < 0 else ending
                write_base64(block[offset:stop], output)
                offset = stop
                if ending >= 0:
                    if carry or database_bytes < 100:
                        raise ValueError('checkpoint database rejected')
                    state = 'suffix'
                    token_index = token_offset = 0
                    offset += 1
            elif state == 'suffix':
                value = block[offset]
                offset += 1
                if token_offset == 0 and value in whitespace:
                    continue
                if value != b'}'[token_offset]:
                    raise ValueError('checkpoint schema rejected')
                token_offset += 1
                if token_offset == 1:
                    state = 'done'
                    token_offset = 0
            else:
                if any(value not in whitespace for value in block[offset:]):
                    raise ValueError('checkpoint schema rejected')
                return

    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as output:
            decoder = zlib.decompressobj()
            try:
                for start in range(0, len(compressed), 65_536):
                    pending = compressed[start:start + 65_536]
                    while pending:
                        block = decoder.decompress(pending, 65_536)
                        feed(block, output)
                        if decoder.unused_data:
                            raise ValueError('compressed payload rejected')
                        pending = decoder.unconsumed_tail
                if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                    raise ValueError('compressed payload rejected')
            except zlib.error:
                raise ValueError('compressed payload rejected') from None
            if state != 'done' or database_bytes > MAX_CHECKPOINT_DB_BYTES:
                raise ValueError('checkpoint schema rejected')
            output.flush()
            os.fsync(output.fileno())
        if not 100 <= database_bytes <= MAX_CHECKPOINT_DB_BYTES:
            raise ValueError('checkpoint database rejected')
        with Path(destination).open('rb') as source:
            if source.read(16) != b'SQLite format 3\x00':
                raise ValueError('checkpoint database rejected')
        return database_bytes
    except BaseException:
        try:
            Path(destination).unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _bind_database(db, provider, job, payload_sha):
    match = re.fullmatch(r'([1-9][0-9]*)-([0-9]+)', job)
    if not match:
        raise ValueError('job identity rejected')
    job_id = int(match[1])
    if job_id > 2**63 - 1:
        raise ValueError('job identity rejected')
    try:
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('PRAGMA query_only=ON')
        db.set_progress_handler(lambda: 1, 100_000)
        schemas = db.execute("SELECT name,type,sql FROM sqlite_master WHERE name IN ('operations','assets','jobs','receipts')").fetchall()
        if any(not isinstance(sql, str) or 'VIRTUAL TABLE' in sql.upper() for _, _, sql in schemas):
            raise ValueError('checkpoint virtual schema rejected')
        tables = {name: kind for name, kind, _ in schemas}
        if tables != dict.fromkeys(('operations','assets','jobs','receipts'), 'table'):
            raise ValueError('checkpoint tables rejected')
        found = db.execute('SELECT j.operation,j.asset,o.provider FROM jobs j JOIN operations o ON o.id=j.operation WHERE j.id=?', (job_id,)).fetchall()
        if len(found) != 1 or found[0][2] != provider or not isinstance(found[0][0], str):
            raise ValueError('checkpoint job binding rejected')
        operation, asset_id, _ = found[0]
        receipts = db.execute('SELECT at,rows FROM receipts WHERE job=? AND sha=?', (job_id, payload_sha)).fetchall()
        if not receipts or any(type(at) not in (int,float) or not math.isfinite(at) or at <= 0 or type(rows) is not int or rows < 0 for at, rows in receipts):
            raise ValueError('checkpoint payload receipt rejected')
        if type(asset_id) is not int or asset_id < 0:
            raise ValueError('asset binding rejected')
        asset = None
        if asset_id:
            rows = db.execute('SELECT provider,descriptor FROM assets WHERE id=?', (asset_id,)).fetchall()
            if len(rows) != 1 or rows[0][0] != provider:
                raise ValueError('asset binding rejected')
            if not isinstance(rows[0][1], str) or len(rows[0][1].encode()) > 1_000_000:
                raise ValueError('asset descriptor rejected')
            asset = _json(rows[0][1].encode())
            if not isinstance(asset, dict):
                raise ValueError('asset descriptor rejected')
        return operation, asset, receipts
    except sqlite3.Error:
        raise ValueError('checkpoint database rejected') from None


def _bind_checkpoint(checkpoint_envelope, provider, job, payload_sha, env, directory):
    compressed = _authenticated_compressed(checkpoint_envelope, provider=provider,
        run_id='checkpoint', job=provider, format='exhaustive', env=env)
    path = Path(directory) / 'checkpoint.sqlite'
    _stream_checkpoint_database(compressed, path)
    uri = path.resolve().as_uri() + '?mode=ro'
    db = sqlite3.connect(uri, uri=True)
    try:
        return _bind_database(db, provider, job, payload_sha)
    finally:
        db.close()


def _records(payload):
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, (dict,str))]
    if isinstance(payload, dict):
        for name in ('symbols','results','data','values','list','securities','companies','exchanges','releases','sources','categories','seriess','observations','stock_prices','options','trades','quotes','news','markets','bestMatches','top_gainers','top_losers','most_actively_traded','feed','earningsCalendar','economicCalendar'):
            value = payload.get(name)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, (dict,str))]
        for name in ('result','data'):
            if isinstance(payload.get(name), dict):
                return _records(payload[name])
        if isinstance(payload.get('Global Quote'), dict) and payload['Global Quote']:
            return [payload['Global Quote']]
        for name, value in payload.items():
            if 'time series' in name.lower() and isinstance(value, dict):
                return [dict(timestamp=stamp, **{re.sub(r'^\d+\.\s*', '', str(key)).strip().lower().replace(' ', '_'): item for key, item in row.items()}) for stamp, row in value.items() if isinstance(row, dict)]
        return []
    return []


def _diagnostics(records, asset):
    out = dict(records_read=len(records), populated_records=0, scalar_fields_read=0,
               finite_numeric_fields=0, identity_fields_read=0, asset_identity_matches=0,
               timestamp_fields_read=0, corporate_action_fields_read=0)
    identities = {str(asset[k]) for k in ('symbol','identifier') if asset and k in asset}
    for record in records:
        stack = [record]
        populated = False
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                for key, item in value.items():
                    lower = key.lower()
                    scalar = not isinstance(item, (dict,list))
                    if scalar and item is not None:
                        if lower in {'symbol','ticker','code','identifier','series_id'}:
                            out['identity_fields_read'] += 1
                            out['asset_identity_matches'] += int(str(item) in identities)
                        if lower in {'date','datetime','timestamp','time','t','updated_at','realtime_start','realtime_end'}:
                            out['timestamp_fields_read'] += 1
                        if lower in {'split','splitfactor','split_factor','dividend','divcash','distribution','exdate','ex_date'}:
                            out['corporate_action_fields_read'] += 1
                    stack.append(item)
            elif isinstance(value, list):
                stack.extend(value)
            elif value is not None:
                out['scalar_fields_read'] += 1
                populated |= not isinstance(value, str) or bool(value.strip())
                if type(value) in (int,float):
                    out['finite_numeric_fields'] += 1
        out['populated_records'] += int(populated)
    return out


def consume_archive(*, archive, archive_sha256, provider, run_id, job, format,
                    source_repo, source_ref, env, checkpoint=None, checkpoint_sha256=None):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', source_repo) or not re.fullmatch(r'[0-9a-f]{40}', source_ref):
        raise ValueError('immutable source identity required')
    payload = decrypt(_pinned(archive, archive_sha256), provider=provider, run_id=run_id, job=job, format=format, env=env)
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    payload_sha = hashlib.sha256(canonical).hexdigest()
    asset = None
    operation = None
    receipts = []
    if format != 'native':
        if checkpoint is None or checkpoint_sha256 is None:
            raise ValueError('checkpoint pin required')
        checkpoint_envelope = _pinned(checkpoint, checkpoint_sha256)
        with tempfile.TemporaryDirectory(prefix='icarus-provider-checkpoint-') as directory:
            operation, asset, receipts = _bind_checkpoint(
                checkpoint_envelope, provider, job, payload_sha, env, directory)
    elif checkpoint is not None or checkpoint_sha256 is not None:
        raise ValueError('native checkpoint unsupported')
    records = _records(payload)
    # Native fixed snapshots can be scalar objects (for example Finnhub quotes).
    # Exhaustive zero-record wrappers must never become a fabricated record.
    native_scalar = format == 'native' and provider == 'finnhub' and isinstance(payload, dict) and bool(payload)
    diagnostics = _diagnostics(records or ([payload] if native_scalar else []), asset)
    if receipts and not all(count == len(records) for _, count in receipts):
        raise ValueError('record count binding rejected')
    return dict(schema_version='icarus-private-provider-consumption-v1', provider=provider,
                run_id=run_id, format=format, source_repository=source_repo, source_ref=source_ref,
                archive_sha256=archive_sha256, checkpoint_sha256=checkpoint_sha256,
                payload_sha256=payload_sha, operation_sha256=hashlib.sha256(operation.encode()).hexdigest() if operation else None,
                checkpoint_binding_verified=bool(receipts), asset_binding_present=asset is not None,
                diagnostics=diagnostics, corpus_used=diagnostics['populated_records'] > 0,
                raw_values_exported=False, provider_requests=0, execution_authorized=False,
                historical_coverage_verified=False, fresh_feed_access_verified=False)


def write_private(path: Path, value):
    raw = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as file:
            file.write(raw)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        os.close(fd)


def safe_extract_zip(zip_path: Path, destination: Path):
    """Extract bounded regular members exclusively into a newly created private tree."""
    raw = read_regular(zip_path)
    import io
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) > 500:
            raise ValueError('ZIP member bound')
        names = set()
        total = 0
        for member in members:
            name = member.filename
            parts = name.rstrip('/').split('/')
            mode = member.external_attr >> 16
            if not name or name.startswith('/') or '\\' in name or any(part in ('','.','..') or ':' in part for part in parts) or name in names or stat.S_ISLNK(mode):
                raise ValueError('ZIP path rejected')
            if mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError('ZIP type rejected')
            names.add(name)
            total += member.file_size
            if member.file_size > MAX_BYTES or total > MAX_BYTES:
                raise ValueError('ZIP size bound')
        destination.mkdir(mode=0o700)
        result = []
        for member in members:
            path = destination.joinpath(*member.filename.rstrip('/').split('/'))
            if member.is_dir():
                path.mkdir(mode=0o700, parents=True, exist_ok=True)
            else:
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                value = archive.read(member)
                if len(value) != member.file_size:
                    raise ValueError('ZIP member size mismatch')
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
                with os.fdopen(fd, 'wb') as file:
                    file.write(value)
                result.append(path)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('format','provider','run-id','archive','archive-sha256','source-repo','source-ref','output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--job')
    parser.add_argument('--checkpoint')
    parser.add_argument('--checkpoint-sha256')
    args = vars(parser.parse_args())
    output = Path(args.pop('output'))
    args['job'] = args['job'] or ('native-access' if args['format'] == 'native' else '')
    receipt = consume_archive(**args, env=dict(os.environ))
    write_private(output, receipt)

if __name__ == '__main__':
    main()
