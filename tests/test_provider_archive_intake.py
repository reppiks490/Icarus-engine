import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import zipfile
import zlib

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from tools import provider_archive_intake as intake

KEY = bytes(range(32))
ENV = {'ICARUS_DATA_ARCHIVE_KEY':base64.b64encode(KEY).decode()}
PAYLOAD = [{'symbol':'PRIVATE_SYMBOL','close':123.45,'timestamp':'2026-01-01','splitFactor':2}]

def envelope(payload, provider='tiingo', run='run-1', job='1-0', key=KEY, raw=None):
    nonce = b'x'*12
    raw = json.dumps(payload,sort_keys=True,separators=(',',':')).encode() if raw is None else raw
    return nonce + AESGCM(key).encrypt(nonce,zlib.compress(raw),f'{run}:{provider}:{job}'.encode())

def save(path,data):
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()

def checkpoint(payload=PAYLOAD, provider='tiingo', bad='', extra_bytes=0):
    db=sqlite3.connect(':memory:')
    db.executescript('CREATE TABLE operations(id,provider,descriptor,status); CREATE TABLE jobs(id,operation,asset); CREATE TABLE assets(id,provider,descriptor); CREATE TABLE receipts(job,at,sha,rows);')
    sha=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    db.execute('INSERT INTO operations VALUES(?,?,?,?)',('op',provider,'{}','OK'))
    db.execute('INSERT INTO jobs VALUES(?,?,?)',(1,'op',2))
    db.execute('INSERT INTO assets VALUES(?,?,?)',(2,provider,json.dumps({'symbol':'PRIVATE_SYMBOL'})))
    db.execute('INSERT INTO receipts VALUES(?,?,?,?)',(1,1700000000,'0'*64 if bad=='sha' else sha,99 if bad=='rows' else len(payload)))
    if extra_bytes:
        db.execute('CREATE TABLE filler(payload BLOB)')
        db.execute('INSERT INTO filler VALUES(?)',(b'x'*extra_bytes,))
    data=db.serialize();db.close()
    return envelope({'sqlite':base64.b64encode(data).decode()},provider=provider,run='checkpoint',job=provider)


def args(tmp_path, provider='tiingo', format='exhaustive', bad=''):
    archive=tmp_path/'payload.enc';check=tmp_path/'checkpoint.enc'
    return dict(archive=archive,archive_sha256=save(archive,envelope(PAYLOAD,provider=provider)),checkpoint=check,checkpoint_sha256=save(check,checkpoint(provider=provider,bad=bad)),provider=provider,run_id='run-1',job='1-0',format=format,source_repo='reppiks490/Icarus-engine',source_ref='a'*40,env=ENV)

@pytest.mark.parametrize('provider,format',[('tiingo','exhaustive'),('alphavantage','supplemental')])
def test_real_reads_private_diagnostics_and_binding(tmp_path,provider,format):
    result=intake.consume_archive(**args(tmp_path,provider,format))
    assert result['corpus_used'] and result['checkpoint_binding_verified']
    assert result['diagnostics']==dict(records_read=1,populated_records=1,scalar_fields_read=4,finite_numeric_fields=2,identity_fields_read=1,asset_identity_matches=1,timestamp_fields_read=1,corporate_action_fields_read=1)
    text=json.dumps(result)
    assert 'PRIVATE_SYMBOL' not in text and '123.45' not in text
    assert result['provider_requests']==0 and not result['execution_authorized']

@pytest.mark.parametrize('provider',['alphavantage','finnhub','unusual_whales'])
def test_native_hkdf_format(tmp_path,provider):
    from tools.provider_credentials import _PROVIDER_BINDINGS
    canonical=_PROVIDER_BINDINGS[provider][0]
    env={canonical:'synthetic-private-credential'}
    key=HKDF(algorithm=hashes.SHA256(),length=32,salt=b'icarus-native-provider-access-v1',info=provider.encode()).derive(env[canonical].encode())
    path=tmp_path/'native.enc';digest=save(path,envelope({'markets':[{'region':'synthetic'}]},provider=provider,job='native-access',key=key))
    result=intake.consume_archive(archive=path,archive_sha256=digest,provider=provider,run_id='run-1',job='native-access',format='native',source_repo='x/y',source_ref='a'*40,env=env)
    assert result['diagnostics']['records_read']==1
    assert not result['checkpoint_binding_verified']
    with pytest.raises(ValueError,match='authentication'):
        intake.decrypt(path.read_bytes(),provider=provider,run_id='wrong',job='native-access',format='native',env=env)

@pytest.mark.parametrize('bad',['sha','rows'])
def test_checkpoint_mismatch(tmp_path,bad):
    with pytest.raises(ValueError):intake.consume_archive(**args(tmp_path,bad=bad))

def test_pins_tamper_wrong_provider(tmp_path):
    kw=args(tmp_path)
    kw['archive'].write_bytes(kw['archive'].read_bytes()+b'bad')
    with pytest.raises(ValueError,match='pin'):intake.consume_archive(**kw)
    data=envelope(PAYLOAD)
    for kwargs in [dict(provider='fred',run_id='run-1',job='1-0'),dict(provider='tiingo',run_id='other',job='1-0'),dict(provider='tiingo',run_id='run-1',job='2-0')]:
        with pytest.raises(ValueError,match='authentication'):intake.decrypt(data,format='exhaustive',env=ENV,**kwargs)

@pytest.mark.parametrize('raw',[b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":1e999}',b'['*34+b'0'+b']'*34,b'{"n":'+b'1'*129+b'}'])
def test_json_rejections(raw):
    with pytest.raises(ValueError):intake.decrypt(envelope(None,raw=raw),provider='tiingo',run_id='run-1',job='1-0',format='exhaustive',env=ENV)

def test_zlib_bound_and_trailing(monkeypatch):
    monkeypatch.setattr(intake,'MAX_BYTES',200)
    nonce=b'x'*12
    for compressed in [zlib.compress(b' '*1000),zlib.compress(b'{}')+b'extra',zlib.compress(b'{}')[:-1]]:
        data=nonce+AESGCM(KEY).encrypt(nonce,compressed,b'run-1:tiingo:1-0')
        with pytest.raises(ValueError):intake.decrypt(data,provider='tiingo',run_id='run-1',job='1-0',format='exhaustive',env=ENV)

def test_private_io_symlinks_and_exclusive(tmp_path):
    original=tmp_path/'original';original.write_bytes(b'{}')
    link=tmp_path/'link';link.symlink_to(original)
    with pytest.raises(OSError):intake.read_regular(link)
    output=tmp_path/'receipt';intake.write_private(output,{'safe':True})
    if os.name=='posix':assert stat.S_IMODE(output.stat().st_mode)==0o600
    with pytest.raises(FileExistsError):intake.write_private(output,{'changed':True})
    assert json.loads(output.read_text())=={'safe':True}

@pytest.mark.parametrize('name',['../escape','/absolute','a/../../escape','a\\b','a:b'])
def test_zip_traversal(tmp_path,name):
    path=tmp_path/'input.zip'
    with zipfile.ZipFile(path,'w') as z:z.writestr(name,b'private')
    with pytest.raises(ValueError):intake.safe_extract_zip(path,tmp_path/'extract')
    assert not (tmp_path/'extract').exists()

def test_zip_regular_private_and_symlink(tmp_path):
    path=tmp_path/'input.zip'
    with zipfile.ZipFile(path,'w') as z:z.writestr('nested/archive.enc',b'encrypted')
    result=intake.safe_extract_zip(path,tmp_path/'extract')
    assert result[0].read_bytes()==b'encrypted'
    if os.name=='posix':assert stat.S_IMODE(result[0].stat().st_mode)==0o600
    with zipfile.ZipFile(path,'w') as z:
        info=zipfile.ZipInfo('link');info.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(info,'target')
    with pytest.raises(ValueError):intake.safe_extract_zip(path,tmp_path/'other')

def test_supplemental_time_series_reads(tmp_path):
    payload={'Time Series (Daily)':{'2026-01-01':{'4. close':'123.4'}}}
    assert intake._records(payload)==[{'timestamp':'2026-01-01','close':'123.4'}]

def test_parent_symlink_input(tmp_path):
    actual=tmp_path/'real';actual.mkdir();(actual/'payload').write_bytes(b'{}')
    (tmp_path/'alias').symlink_to(actual,target_is_directory=True)
    with pytest.raises(OSError):intake.read_regular(tmp_path/'alias'/'payload')

def test_checkpoint_authentication_and_provider_binding(tmp_path):
    kw=args(tmp_path)
    kw['checkpoint_sha256']=save(kw['checkpoint'],checkpoint(provider='fred'))
    with pytest.raises(ValueError,match='authentication'):intake.consume_archive(**kw)

def test_exhaustive_provider_derived_key():
    credential='synthetic-only'
    key=HKDF(algorithm=hashes.SHA256(),length=32,salt=b'icarus-provider-archive-v1',info=b'tiingo').derive(credential.encode())
    assert intake.decrypt(envelope(PAYLOAD,key=key),provider='tiingo',run_id='run-1',job='1-0',format='exhaustive',env={'TIINGO_API_TOKEN':credential})==PAYLOAD
    with pytest.raises(ValueError):intake.decrypt(envelope(PAYLOAD,key=key),provider='tiingo',run_id='run-1',job='1-0',format='exhaustive',env={'TIINGO_API_TOKEN':credential,**ENV})

def test_no_network_needed(tmp_path,monkeypatch):
    import socket
    def forbidden(*args,**kwargs):raise AssertionError('network attempted')
    monkeypatch.setattr(socket,'socket',forbidden)
    assert intake.consume_archive(**args(tmp_path))['corpus_used']

def test_native_format_rejects_other_provider():
    with pytest.raises(ValueError,match='native identity'):intake.decrypt(envelope(PAYLOAD),provider='tiingo',run_id='run-1',job='native-access',format='native',env=ENV)

def test_source_identity_pin(tmp_path):
    kw=args(tmp_path);kw['source_ref']='main'
    with pytest.raises(ValueError,match='immutable'):intake.consume_archive(**kw)

def test_fifo_cannot_block_before_type_check(tmp_path):
    import subprocess
    import sys
    fifo=tmp_path/'input.fifo';os.mkfifo(fifo)
    code='from pathlib import Path; from tools.provider_archive_intake import read_regular; import sys\ntry: read_regular(Path(sys.argv[1]))\nexcept ValueError: sys.exit(0)\nsys.exit(1)'
    result=subprocess.run([sys.executable,'-c',code,str(fifo)],cwd=Path(__file__).resolve().parents[1],timeout=3,capture_output=True)
    assert result.returncode==0,result.stderr.decode()

def test_missing_no_follow_fails_closed(tmp_path,monkeypatch):
    path=tmp_path/'input';path.write_bytes(b'{}')
    monkeypatch.delattr(os,'O_NOFOLLOW')
    with pytest.raises(ValueError,match='secure POSIX'):intake.read_regular(path)

def test_empty_exhaustive_wrapper_is_not_consumption(tmp_path):
    payload={'data':[], 'metadata':{'count':0, 'status':'OK'}}
    archive=tmp_path/'payload.enc';check=tmp_path/'checkpoint.enc'
    db=sqlite3.connect(':memory:')
    db.executescript('CREATE TABLE operations(id,provider,descriptor,status); CREATE TABLE jobs(id,operation,asset); CREATE TABLE assets(id,provider,descriptor); CREATE TABLE receipts(job,at,sha,rows);')
    sha=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    db.execute('INSERT INTO operations VALUES(?,?,?,?)',('op','tiingo','{}','OK'))
    db.execute('INSERT INTO jobs VALUES(?,?,?)',(1,'op',0))
    db.execute('INSERT INTO receipts VALUES(?,?,?,?)',(1,1700000000,sha,0))
    raw=db.serialize();db.close()
    encrypted=envelope({'sqlite':base64.b64encode(raw).decode()},run='checkpoint',job='tiingo')
    result=intake.consume_archive(archive=archive,archive_sha256=save(archive,envelope(payload)),checkpoint=check,checkpoint_sha256=save(check,encrypted),provider='tiingo',run_id='run-1',job='1-0',format='exhaustive',source_repo='x/y',source_ref='a'*40,env=ENV)
    assert not result['corpus_used']
    assert all(count==0 for count in result['diagnostics'].values())

def test_checkpoint_bound_diagnostic_counts_only(tmp_path):
    raw=b'{"private":"'+b'SECRET_LICENSED_VALUE'*10000+b'"}'
    data=envelope(None,run='checkpoint',job='tiingo',raw=raw)
    path=tmp_path/'checkpoint';digest=save(path,data)
    result=intake.checkpoint_bounds(checkpoint=path,checkpoint_sha256=digest,provider='tiingo',env=ENV)
    assert result['decompressed_bytes']==len(raw)
    assert result['decompressed_size_exact'] and not result['diagnostic_limit_reached']
    assert set(result)=={'encrypted_bytes','compressed_bytes','decompressed_bytes','decompressed_size_exact','diagnostic_limit_reached','baseline_intake_limit_bytes','baseline_intake_limit_exceeded'}
    assert 'SECRET' not in json.dumps(result)

def test_checkpoint_bound_diagnostic_abort_is_lower_bound(tmp_path):
    data=envelope(None,run='checkpoint',job='tiingo',raw=b' '*1000000)
    path=tmp_path/'checkpoint';digest=save(path,data)
    result=intake.checkpoint_bounds(checkpoint=path,checkpoint_sha256=digest,provider='tiingo',env=ENV,maximum_output=100000)
    assert result['decompressed_bytes']==100001
    assert not result['decompressed_size_exact'] and result['diagnostic_limit_reached']

def test_authenticated_large_checkpoint_is_consumed_without_raising_payload_limit(tmp_path):
    kw=args(tmp_path)
    encrypted=checkpoint(provider=kw['provider'],extra_bytes=25_000_000)
    kw['checkpoint_sha256']=save(kw['checkpoint'],encrypted)
    bounds=intake.checkpoint_bounds(checkpoint=kw['checkpoint'],checkpoint_sha256=kw['checkpoint_sha256'],provider=kw['provider'],env=kw['env'])
    assert kw['checkpoint'].stat().st_size < intake.MAX_BYTES
    assert bounds['decompressed_bytes'] > intake.MAX_BYTES

    result=intake.consume_archive(**kw)

    assert result['checkpoint_binding_verified'] and result['corpus_used']
    assert result['provider_requests']==0 and result['execution_authorized'] is False

def test_checkpoint_stream_enforces_total_decompressed_bound_and_cleans_partial_file(tmp_path, monkeypatch):
    encrypted = checkpoint()
    compressed = intake._authenticated_compressed(
        encrypted, provider='tiingo', run_id='checkpoint', job='tiingo',
        format='exhaustive', env=ENV)
    destination = tmp_path / 'checkpoint.sqlite'
    monkeypatch.setattr(intake, 'MAX_CHECKPOINT_JSON_BYTES', 64)

    with pytest.raises(ValueError, match='compressed payload'):
        intake._stream_checkpoint_database(compressed, destination)

    assert not destination.exists()

def test_checkpoint_diagnostic_auth_before_decompression(tmp_path):
    path=tmp_path/'checkpoint';digest=save(path,envelope(None,run='checkpoint',job='tiingo',raw=b' '*10000))
    with pytest.raises(ValueError,match='authentication'):
        intake.checkpoint_bounds(checkpoint=path,checkpoint_sha256=digest,provider='fred',env=ENV)

def test_checkpoint_diagnostic_trailing_stream_rejected(tmp_path):
    nonce=b'x'*12
    encrypted=nonce+AESGCM(KEY).encrypt(nonce,zlib.compress(b'{}')+b'trailing',b'checkpoint:tiingo:tiingo')
    path=tmp_path/'checkpoint';digest=save(path,encrypted)
    with pytest.raises(ValueError,match='compressed'):
        intake.checkpoint_bounds(checkpoint=path,checkpoint_sha256=digest,provider='tiingo',env=ENV)
