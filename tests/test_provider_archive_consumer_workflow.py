"""Executable security contracts for offline, retained-artifact provider consumption."""
from __future__ import annotations
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import textwrap
import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/provider-archive-consumer.yml'

def step(name):
    text = WORKFLOW.read_text()
    start = text.index('      - name: ' + name + '\n')
    end = text.find('\n      - ', start + 1)
    return text[start:] if end < 0 else text[start:end]

def script(name):
    return textwrap.dedent(step(name).split('        run: |\n')[1])

def python(name):
    return script(name).split("<<'PY'", 1)[1].split('\n', 1)[1].split('\nPY', 1)[0]

def execute(name):
    exec(compile(python(name), name, 'exec'), {})

def env(tmp_path, monkeypatch, profile='fred', ref='a'*40):
    values={'RUNNER_TEMP':str(tmp_path),'GITHUB_ENV':str(tmp_path/'environment'),'PROFILE':profile,'ENGINE_REF':ref,'SOURCE_REF':'84dd20e5186cc26fe4c95a371ea5fbbfed2ecdfe'}
    for key,value in values.items():
        monkeypatch.setenv(key,value)
    return values

def setup(tmp_path, monkeypatch):
    env(tmp_path, monkeypatch)
    execute('Validate immutable profile')
    assignments=dict(row.split('=',1) for row in (tmp_path/'environment').read_text().splitlines())
    root=Path(assignments['PROOF_ROOT'])
    monkeypatch.setenv('PROOF_ROOT',str(root))
    pin=json.loads((root/'pin.json').read_text()); pin['checkpoint_sha256']='a'*64
    (root/'pin.json').write_text(json.dumps(pin)); (root/'receipts').mkdir()
    return root,pin

def receipt(pin):
    return dict(schema_version='icarus-private-provider-consumption-v1', provider=pin['provider'],run_id=pin['run_id'],format=pin['format'],source_repository='reppiks490/Icarus-engine',source_ref=os.environ['SOURCE_REF'],archive_sha256='b'*64,checkpoint_sha256='a'*64,payload_sha256='c'*64,operation_sha256='d'*64,checkpoint_binding_verified=True,asset_binding_present=True,diagnostics={name:1 for name in ('records_read','populated_records','scalar_fields_read','finite_numeric_fields','identity_fields_read','asset_identity_matches','timestamp_fields_read','corporate_action_fields_read')},corpus_used=True,raw_values_exported=False,provider_requests=0,execution_authorized=False,historical_coverage_verified=False,fresh_feed_access_verified=False)

def test_only_narrow_push_or_manual_and_read_only_permissions():
    text=WORKFLOW.read_text()
    assert 'branches: ["codex/provider-private-workflow-20261019"]' in text
    assert 'paths: [".github/workflows/provider-archive-consumer.yml"]' in text
    assert 'contents: read' in text and 'actions: read' in text
    assert not any(word in text for word in ('schedule:', 'workflow_run:', 'contents: write', 'git push', 'collector.cycle', 'continue-on-error'))
    assert 'timeout-minutes: 20' in text
    assert text.count('persist-credentials: false')==2
    assert text.index('Validate immutable profile')<text.index('actions/checkout@')

@pytest.mark.parametrize('profile',['', 'arbitrary','fred\nEVIL=1','$(touch unsafe)'])
def test_unrecognized_profile_cannot_reach_environment(tmp_path,monkeypatch,profile):
    env(tmp_path,monkeypatch,profile=profile)
    with pytest.raises(SystemExit): execute('Validate immutable profile')
    assert not (tmp_path/'environment').exists()

@pytest.mark.parametrize('ref',['main','A'*40,'a'*39,'a'*40+'\n','$(touch unsafe)'])
def test_mutable_or_interpretable_ref_rejected(tmp_path,monkeypatch,ref):
    env(tmp_path,monkeypatch,ref=ref)
    with pytest.raises(SystemExit): execute('Validate immutable profile')
    assert not (tmp_path/'environment').exists()

@pytest.mark.parametrize('profile',['massive','twelve','fmp','eodhd','tiingo','fred','alphavantage','native_alphavantage'])
def test_pins_private_storage_and_no_stdout(tmp_path,monkeypatch,capsys,profile):
    env(tmp_path,monkeypatch,profile=profile)
    execute('Validate immutable profile')
    assignments=dict(row.split('=',1) for row in (tmp_path/'environment').read_text().splitlines())
    root=Path(assignments['PROOF_ROOT']); pin=json.loads((root/'pin.json').read_text())
    assert root.stat().st_mode&0o777==0o700
    assert re.fullmatch(r'[0-9a-f]{40}',pin['workflow_head'])
    assert re.fullmatch(r'sha256:[0-9a-f]{64}',pin['digest'])
    assert pin['artifact_id']>0 and pin['workflow_run']>0
    assert capsys.readouterr().out==''

def test_credential_isolation_socket_guards_and_private_logs():
    text=WORKFLOW.read_text(); intake=step('Consume private archive offline')
    assert text.count('secrets.')==intake.count('secrets.')
    assert text.count('GH_TOKEN:')==1
    assert 'GH_TOKEN' not in intake
    assert 'os.environ.pop(\'PROVIDER_ARCHIVE_CREDENTIAL\'' in intake
    for name in ('Consume private archive offline','Extract encrypted members safely'):
        value=step(name)
        assert 'socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = offline' in value
        assert '> "$PROOF_ROOT/' in value and '2>&1' in value
    assert 'runpy.run_module(\'tools.provider_archive_intake\'' in intake
    assert '--checkpoint-sha256' in intake and '--archive-sha256' in intake
    assert 'safe_extract_zip(' in step('Extract encrypted members safely')
    assert 'if: always()' in step('Remove all private payloads and logs')
    assert 'path: ${{ env.PROOF_ROOT }}/receipts/*.json' in step('Upload metadata receipts only')

def test_download_binds_artifact_run_digest_repository_and_checkpoint_blob():
    value=step('Download immutable encrypted artifact')
    for key in ('artifact_id','artifact_name','digest','workflow_run','workflow_head','repository_id','checkpoint_blob','SOURCE_REF'):
        assert key in value
    assert 'hashlib.sha256(data).hexdigest()' in value
    assert "hashlib.sha1(b'blob '" in value
    assert '128 * 1024 * 1024 + 1' in value


def test_valid_metadata_receipt_passes(tmp_path,monkeypatch):
    root,pin=setup(tmp_path,monkeypatch)
    (root/'receipts/0.json').write_text(json.dumps(receipt(pin)))
    execute('Validate metadata only receipts')

@pytest.mark.parametrize('patch',[{'raw_values_exported':True},{'execution_authorized':True},{'provider_requests':1},{'provider_requests':False},{'historical_coverage_verified':True},{'fresh_feed_access_verified':True},{'corpus_used':False},{'checkpoint_binding_verified':False},{'asset_binding_present':'yes'},{'source_ref':'main'},{'provider':'other'},{'format':'native'},{'raw_quotes':['licensed']},{'archive_sha256':'bad'},{'operation_sha256':None},{'checkpoint_sha256':'b'*64}])
def test_receipt_gate_refuses_raw_values_authority_and_misbinding(tmp_path,monkeypatch,patch):
    root,pin=setup(tmp_path,monkeypatch)
    (root/'receipts/0.json').write_text(json.dumps({**receipt(pin),**patch}))
    with pytest.raises(ValueError): execute('Validate metadata only receipts')

@pytest.mark.parametrize('bad',[True,-1,1.5,'1',100_000_001])
def test_diagnostic_counts_strict_and_bounded(tmp_path,monkeypatch,bad):
    root,pin=setup(tmp_path,monkeypatch); doc=receipt(pin)
    doc['diagnostics']['records_read']=bad
    (root/'receipts/0.json').write_text(json.dumps(doc))
    with pytest.raises(ValueError): execute('Validate metadata only receipts')

def test_missing_receipts_fail(tmp_path,monkeypatch):
    setup(tmp_path,monkeypatch)
    with pytest.raises(ValueError): execute('Validate metadata only receipts')

def test_all_embedded_programs_parse():
    for name in ('Validate immutable profile','Download immutable encrypted artifact','Extract encrypted members safely','Consume private archive offline','Report safe intake diagnostics','Validate metadata only receipts'):
        ast.parse(python(name))
        result=subprocess.run(['bash','-n'],input=script(name),text=True,capture_output=True)
        assert result.returncode==0,result.stderr


def test_actual_intake_invocation_maps_only_selected_credential_and_blocks_network(tmp_path,monkeypatch):
    import runpy
    import socket
    import sys
    root,pin=setup(tmp_path,monkeypatch)
    (root/'receipts').rmdir()
    directory=root/'extracted/.provider_collection_archives'/pin['run_id']/pin['provider']
    directory.mkdir(parents=True)
    (directory/'3-0.enc').write_bytes(b'ciphertext-only')
    monkeypatch.setenv('PROVIDER_ARCHIVE_CREDENTIAL','synthetic-test-value')
    monkeypatch.setattr(sys,'argv',[])
    monkeypatch.setattr(sys,'excepthook',sys.excepthook)
    from types import ModuleType
    intake_module=ModuleType('tools.provider_archive_intake')
    intake_module.checkpoint_bounds=lambda **kwargs: {}
    monkeypatch.setitem(sys.modules,'tools.provider_archive_intake',intake_module)
    for name in ('connect','connect_ex'):
        monkeypatch.setattr(socket.socket,name,getattr(socket.socket,name))
    for name in ('create_connection','getaddrinfo'):
        monkeypatch.setattr(socket,name,getattr(socket,name))
    seen=[]
    def invoke(name,run_name):
        assert name=='tools.provider_archive_intake' and run_name=='__main__'
        assert os.environ['FRED_API_KEY']=='synthetic-test-value'
        assert 'PROVIDER_ARCHIVE_CREDENTIAL' not in os.environ
        with pytest.raises(PermissionError): socket.create_connection(('provider.invalid',443))
        with pytest.raises(PermissionError): socket.getaddrinfo('provider.invalid',443)
        with socket.socket() as client:
            with pytest.raises(PermissionError): client.connect(('127.0.0.1',80))
        seen.append(list(sys.argv))
    monkeypatch.setattr(runpy,'run_module',invoke)
    # The script creates its canonical environment entry; scope that write too.
    monkeypatch.setenv('FRED_API_KEY','')
    execute('Consume private archive offline')
    assert len(seen)==1
    args=seen[0]
    assert args[args.index('--job')+1]=='3-0'
    assert args[args.index('--source-ref')+1]==os.environ['SOURCE_REF']
    assert args[args.index('--checkpoint-sha256')+1]=='a'*64
    assert 'synthetic-test-value' not in args
    assert '--archive-sha256' in args


def test_workflow_proof_binds_actual_receipt_hash_and_immutable_artifact(tmp_path,monkeypatch):
    import hashlib
    root,pin=setup(tmp_path,monkeypatch)
    path=root/'receipts/0.json'; path.write_text(json.dumps(receipt(pin)))
    execute('Validate metadata only receipts')
    proof=json.loads((root/'receipts/workflow-proof.json').read_text())
    assert proof['archive_receipts']==[{'name':'0.json','sha256':hashlib.sha256(path.read_bytes()).hexdigest()}]
    assert proof['artifact_id']==12157403530
    assert proof['consumer_ref']=='a'*40
    assert proof['provider_requests']==0 and proof['raw_values_exported'] is False


def redirect_handler():
    """Execute the actual redirect class without making any network request."""
    tree=ast.parse(python('Download immutable encrypted artifact'))
    node=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='ScopedRedirect')
    import urllib.request
    import urllib.parse
    namespace={'urllib':__import__('urllib')}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'redirect-contract','exec'),namespace)
    return namespace['ScopedRedirect']()


@pytest.mark.parametrize('target',['https://signed.blob.core.windows.net/object?signature=private','https://bucket.s3.amazonaws.com/object'])
def test_cross_host_artifact_redirect_never_forwards_github_authorization(target):
    import urllib.request
    request=urllib.request.Request('https://api.github.com/repos/owner/repo/actions/artifacts/1/zip',headers={'Authorization':'Bearer synthetic-private-value','Accept':'application/vnd.github+json'})
    redirected=redirect_handler().redirect_request(request,None,302,'Found',{},target)
    assert redirected.full_url==target
    assert not redirected.has_header('Authorization')
    assert 'synthetic-private-value' not in str(redirected.header_items())
    assert request.has_header('Authorization')


def test_same_host_https_redirect_keeps_scoped_authorization():
    import urllib.request
    request=urllib.request.Request('https://api.github.com/one',headers={'Authorization':'Bearer synthetic-private-value'})
    redirected=redirect_handler().redirect_request(request,None,302,'Found',{},'https://api.github.com/two')
    assert redirected.get_header('Authorization')=='Bearer synthetic-private-value'


@pytest.mark.parametrize('target',['http://api.github.com/one','https://attacker:password@api.github.com/path'])
def test_insecure_or_credentialed_redirect_rejected(target):
    import urllib.request
    request=urllib.request.Request('https://api.github.com/one',headers={'Authorization':'Bearer synthetic-private-value'})
    with pytest.raises(ValueError): redirect_handler().redirect_request(request,None,302,'Found',{},target)


def test_downloader_uses_guarded_opener_and_intake_has_only_fixed_failure_code():
    download=step('Download immutable encrypted artifact')
    assert 'opener = urllib.request.build_opener(ScopedRedirect())' in download
    assert download.count('opener.open(request(')==2
    assert 'urllib.request.urlopen(' not in download
    intake=step('Consume private archive offline')
    assert "echo '::error::PROVIDER_ARCHIVE_OFFLINE_INTAKE_FAILED'" in intake
    assert 'cat ' not in intake and 'tail ' not in intake
    assert 'exit "$intake_exit"' in intake


@pytest.mark.parametrize('error,expected',[(ValueError('compressed payload rejected'),'DECOMPRESSED_PAYLOAD_BOUND_OR_FORMAT'),(ValueError('checkpoint payload receipt rejected'),'CHECKPOINT_PAYLOAD_RECEIPT'),(ValueError('record count binding rejected'),'RECORD_COUNT_BINDING'),(ValueError('input size or type rejected'),'INPUT_SIZE_OR_TYPE'),(ValueError('private-key-or-licensed-value'),'UNCLASSIFIED'),(RuntimeError('private-path-or-token'),'UNCLASSIFIED')])
def test_failure_hook_only_exports_allowlisted_constant_codes(tmp_path,monkeypatch,capsys,error,expected):
    import sys
    root,pin=setup(tmp_path,monkeypatch)
    tree=ast.parse(python('Consume private archive offline'))
    nodes=[node for node in tree.body if isinstance(node,(ast.Assign,ast.FunctionDef)) and (isinstance(node,ast.FunctionDef) and node.name=='safe_failure' or isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id in {'codes','stage'} for target in node.targets))]
    namespace={'root':root,'json':json}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'safe-errors','exec'),namespace)
    namespace['safe_failure'](type(error),error,None)
    failure=json.loads((root/'failure.json').read_text())
    assert failure['code']==expected
    execute('Report safe intake diagnostics')
    printed=capsys.readouterr().out
    assert expected in printed
    assert 'private-key' not in printed and 'private-path' not in printed


@pytest.mark.parametrize('extra',[{'token':'do-not-print'},{'decompressed_bytes':'licensed-value'},{'decompressed_bytes':True},{'decompressed_bytes':512_000_002}])
def test_size_diagnostic_reporter_refuses_untyped_or_extra_payload_fields(tmp_path,monkeypatch,capsys,extra):
    root,pin=setup(tmp_path,monkeypatch)
    doc=dict(encrypted_bytes=100,compressed_bytes=72,decompressed_bytes=1000,baseline_intake_limit_bytes=32_000_000,decompressed_size_exact=True,diagnostic_limit_reached=False,baseline_intake_limit_exceeded=False)
    (root/'checkpoint-bounds.json').write_text(json.dumps({**doc,**extra}))
    with pytest.raises(ValueError): execute('Report safe intake diagnostics')
    assert capsys.readouterr().out==''


def test_valid_authenticated_checkpoint_size_diagnostic_is_counts_only(tmp_path,monkeypatch,capsys):
    root,pin=setup(tmp_path,monkeypatch)
    doc=dict(encrypted_bytes=100,compressed_bytes=72,decompressed_bytes=40_000_000,baseline_intake_limit_bytes=32_000_000,decompressed_size_exact=True,diagnostic_limit_reached=False,baseline_intake_limit_exceeded=True)
    (root/'checkpoint-bounds.json').write_text(json.dumps(doc))
    execute('Report safe intake diagnostics')
    assert json.loads(capsys.readouterr().out)==doc
