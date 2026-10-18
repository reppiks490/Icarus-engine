"""Synthetic historical-evidence and shared-writer regression cases."""
import json
import multiprocessing as mp
from pathlib import Path
import pytest
from cl_lab import trial_ledger as tl
from tests_cl.test_frontier import _fake_sources


def _record(key='one', digest='x'):
    return dict(trial_id=key, source='synthetic', source_path='synthetic', row_sha256=digest)


def test_unrecoverable_historical_evaluations_block_without_writing(tmp_path):
    cl = _fake_sources(tmp_path)
    (cl / 'history' / 'older.json').write_text(json.dumps(dict(run_id='older', candidates=600,
        assets={'MNQ': dict(status='EVALUATED', diagnostics=dict(candidates=600))})))
    ledger = tmp_path / 'ledger.jsonl'
    out = tl.import_historical(tmp_path, ledger)
    assert out['status'] == 'BLOCKED'
    assert 'older' in ' '.join(out['blockers'])
    assert not ledger.exists()


def test_current_and_archived_runs_are_distinct_idempotent_trials(tmp_path):
    cl = _fake_sources(tmp_path)
    # A retained archive carries the actual rows; an aggregate is not reconstructed as invented rows.
    current = [dict(json.loads(line), run_id='current') for line in (cl / 'candidates_latest.jsonl').read_text().splitlines()]
    (cl / 'candidates_latest.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in current))
    (cl / 'latest.json').write_text(json.dumps(dict(run_id='current', candidates=492,
        assets={'MNQ': dict(status='EVALUATED', diagnostics=dict(candidates=492))})))
    for p in (cl / 'history').glob('*.json'): p.unlink()
    (cl / 'history' / 'old.json').write_text(json.dumps(dict(run_id='old', candidates=492,
        assets={'MNQ': dict(status='EVALUATED', diagnostics=dict(candidates=492))})))
    old = [dict(r, run_id='old', t=-2.) for r in current]
    (cl / 'history' / 'old.candidates.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in old))
    ledger = tmp_path / 'ledger.jsonl'
    out = tl.import_historical(tmp_path, ledger)
    assert out['status'] == 'OK'
    assert tl.snapshot(ledger)['by_source']['cl-lab'] == 984
    assert tl.import_historical(tmp_path, ledger)['added'] == 0


def test_duplicate_explorer_rows_cannot_satisfy_minimum_count(tmp_path):
    cl = _fake_sources(tmp_path)
    row = json.dumps(dict(asset='MNQ', id='same')) + '\n'
    (cl / 'explore_ledger.jsonl').write_text(row * 2160)
    assert tl.import_historical(tmp_path, tmp_path/'ledger.jsonl')['status'] == 'BLOCKED'


def test_conflicting_identity_is_rejected_without_partial_append(tmp_path):
    ledger = tmp_path / 'ledger.jsonl'
    tl.append(ledger, [_record()])
    before = ledger.read_bytes()
    with pytest.raises(tl.SourceError, match='conflict'):
        tl.append(ledger, [_record('new'), _record(digest='different')])
    assert ledger.read_bytes() == before


def _append_worker(path, started, done):
    started.set()
    tl.append(path, [_record()])
    done.set()


def test_append_serializes_across_processes(tmp_path):
    fcntl = pytest.importorskip('fcntl')
    ledger = tmp_path / 'ledger.jsonl'
    lock = Path(str(ledger) + '.lock')
    ctx = mp.get_context('spawn')
    started, done = ctx.Event(), ctx.Event()
    with lock.open('a+b') as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        worker = ctx.Process(target=_append_worker, args=(ledger, started, done))
        worker.start()
        try:
            assert started.wait(5)
            assert not done.wait(.2), 'append ignored the ledger lock'
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
            worker.join(5)
            if worker.is_alive(): worker.terminate(); worker.join()
    assert worker.exitcode == 0
    assert tl.append(ledger, [_record()]) == 0
    assert tl.snapshot(ledger)['total'] == 1


def test_import_keeps_trial_identity_when_latest_moves_to_archive(tmp_path):
    cl = _fake_sources(tmp_path)
    ledger = tmp_path / 'ledger.jsonl'
    assert tl.import_historical(tmp_path, ledger)['status'] == 'OK'
    rows = [json.loads(line) for line in (cl/'candidates_latest.jsonl').read_text().splitlines()]
    (cl/'history'/'cl-lab-1.candidates.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    summary = json.loads((cl/'latest.json').read_text())
    summary['run_id'] = 'cl-lab-2'
    (cl/'latest.json').write_text(json.dumps(summary))
    (cl/'candidates_latest.jsonl').write_text(''.join(json.dumps(dict(r,run_id='cl-lab-2'))+'\n' for r in rows))
    out = tl.import_historical(tmp_path, ledger)
    assert out['status'] == 'OK', out
    assert out['added'] == 492
    assert tl.snapshot(ledger)['by_source']['cl-lab'] == 984


def test_rule_declaration_mismatch_cannot_hide_omitted_candidates(tmp_path):
    cl = _fake_sources(tmp_path)
    for path in [cl/'latest.json',cl/'history'/'cl-lab-1.json']:
        summary=json.loads(path.read_text());summary['candidates']=600;path.write_text(json.dumps(summary))
    assert tl.import_historical(tmp_path,tmp_path/'ledger.jsonl')['status']=='BLOCKED'


def test_historical_boos_version_requires_actual_candidate_archive(tmp_path):
    cl = _fake_sources(tmp_path)
    p=cl/'history'/'cl-lab-1.json';summary=json.loads(p.read_text())
    summary['backward_oos']=dict(status='EVALUATED',fingerprint='older-boos',records=1)
    p.write_text(json.dumps(summary));(cl/'latest.json').write_text(json.dumps(summary))
    out=tl.import_historical(tmp_path,tmp_path/'ledger.jsonl')
    assert out['status']=='BLOCKED'
    assert 'older-boos' in ' '.join(out['blockers'])


def test_unversioned_historical_pulse_is_blocked(tmp_path):
    cl = _fake_sources(tmp_path)
    p=cl/'history'/'cl-lab-1.json';summary=json.loads(p.read_text())
    summary['assets']['MNQ']['pulse']=dict(variants={'A':dict(t=1.)})
    p.write_text(json.dumps(summary));(cl/'latest.json').write_text(json.dumps(summary))
    out=tl.import_historical(tmp_path,tmp_path/'ledger.jsonl')
    assert out['status']=='BLOCKED'
    assert 'pulse' in ' '.join(out['blockers'])


def test_depth_trials_bind_input_version(tmp_path):
    cl=_fake_sources(tmp_path);ledger=tmp_path/'ledger.jsonl'
    assert tl.import_historical(tmp_path,ledger)['status']=='OK'
    path=cl/'depth_d1_latest.json';source=json.loads(path.read_text());source['fingerprint']='next-input'
    path.write_text(json.dumps(source))
    out=tl.import_historical(tmp_path,ledger)
    assert out['status']=='OK'
    assert out['added']==1
    assert tl.snapshot(ledger)['by_source']['depth-d1']==2


def test_invalid_json_source_shape_is_blocked(tmp_path):
    cl=_fake_sources(tmp_path);(cl/'pulse_latest.json').write_text('[]')
    assert tl.import_historical(tmp_path,tmp_path/'ledger.jsonl')['status']=='BLOCKED'


def test_missing_history_directory_is_blocked(tmp_path):
    cl=_fake_sources(tmp_path)
    for path in (cl/'history').iterdir(): path.unlink()
    (cl/'history').rmdir()
    assert tl.import_historical(tmp_path,tmp_path/'ledger.jsonl')['status']=='BLOCKED'


def test_retained_boos_and_versioned_pulse_history_are_imported(tmp_path):
    cl=_fake_sources(tmp_path)
    p=cl/'history'/'cl-lab-1.json';summary=json.loads(p.read_text())
    summary['backward_oos']=dict(status='EVALUATED',fingerprint='older-boos',records=1)
    summary['assets']['MNQ']['pulse']=dict(fingerprint='older-pulse',variants={'A':dict(t=1.)})
    p.write_text(json.dumps(summary));(cl/'latest.json').write_text(json.dumps(summary))
    folder=cl/'history'/'boos';folder.mkdir()
    (folder/'older-boos.json').write_text(json.dumps(dict(fingerprint='older-boos',
        candidate_rows=[dict(family='cl-g1',id='old-candidate')],records=1)))
    ledger=tmp_path/'ledger.jsonl';out=tl.import_historical(tmp_path,ledger)
    assert out['status']=='OK',out
    counts=tl.snapshot(ledger)['by_source']
    assert counts['cl-boos1']==2 and counts['pulse']==3
    assert tl.import_historical(tmp_path,ledger)['added']==0


def test_unversioned_explorer_overlap_is_ambiguous_not_cross_run_deduplication(tmp_path):
    cl=_fake_sources(tmp_path)
    path=cl/'candidates_latest.jsonl';rows=[json.loads(line) for line in path.read_text().splitlines()]
    rows[0]['id']='x0'
    path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    out=tl.import_historical(tmp_path,tmp_path/'ledger.jsonl')
    assert out['status']=='BLOCKED'
    assert 'unversioned' in ' '.join(out['blockers'])
