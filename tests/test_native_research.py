"""Independent controls: future mutation, known MAD vector, corrupt bar, missing data."""
import copy
from pathlib import Path

import pytest


def module():
    from tools import native_research as nr
    return nr


def bars(n=100):
    return [dict(start=i*3600, end=(i+1)*3600, open=100., high=101.+i%3,
                 low=99., close=100., volume=10.+i%5) for i in range(n)]


def test_known_mad_vector():
    nr = module()
    assert nr.robust_z(10, [1, 2, 3, 4, 5]) == pytest.approx(7/1.4826)
    assert nr.robust_z(100, [1]*28) is None


def test_future_mutation_cannot_change_past():
    nr = module()
    data = bars()
    first = nr.score_bars(data)
    mutated = copy.deepcopy(data)
    for b in mutated[60:]:
        b['volume'] *= 10000
        b['high'] += 9999
    assert nr.score_bars(mutated)[:60] == first[:60]
    assert nr.score_bars(data[:60]) == first[:60]


def test_gap_is_not_a_contiguous_baseline():
    nr = module()
    data = bars(60)
    del data[45]
    assert nr.score_bars(data)[-1]['range_z'] is None


def test_incomplete_and_future_bar_excluded():
    nr = module()
    raw = [[0, 99, 102, 100, 101, 10], [3600, 90, 110, 100, 100, 20]]
    result = nr.normalize_bars('coinbase', raw, 4000)
    assert len(result) == 1 and result[0]['end'] == 3600


def test_invalid_prices_and_conflicting_duplicates_fail_closed():
    nr = module()
    with pytest.raises(ValueError):
        nr.normalize_bars('coinbase', [[0, 105, 100, 101, 102, 10]], 7200)
    with pytest.raises(ValueError):
        nr.normalize_bars('coinbase', [[0, 99, 101, 100, 100, 10], [0, 99, 102, 100, 100, 10]], 7200)


def test_stale_data_not_current_flow():
    nr = module()
    packets = {'venue': dict(provider='coinbase', representation='BTC-USD spot',
                              bars=bars(60), retrieval_started=400000, retrieval_finished=400001)}
    result = nr.flow_research(packets, 400001)
    assert result['status'] == 'BLOCKED'
    assert result['current'] == []


def test_no_data_never_counts_as_research_success():
    nr = module()
    result = nr.aion_research({})
    assert result['status'] == 'BLOCKED'
    assert result['experiments'] == []


def test_empirical_split_and_insufficient_events_are_explicit():
    nr = module()
    result = nr.aion_research({'venue': {'bars': bars(150), 'provider': 'coinbase'}})
    exp = result['experiments'][0]
    assert exp['train_last_end'] < exp['test_first_start']
    assert exp['qualification'] == 'INSUFFICIENT_EVENTS'
    assert exp['performance_claim'] is False


def test_independent_audit_detects_future_corruption():
    nr = module()
    packets = {'venue': dict(provider='coinbase', representation='BTC-USD spot',
                             bars=bars(60), retrieval_started=220000, retrieval_finished=220001)}
    scored = nr.score_bars(packets['venue']['bars'])
    flow = dict(current=[dict(lane_key='venue', **scored[-1])])
    assert nr.audit_research(packets, flow)['status'] == 'VERIFIED'
    flow['current'][0]['range_z'] = 999
    assert nr.audit_research(packets, flow)['status'] == 'BLOCKING'


def test_immutable_write_and_no_nan(tmp_path):
    nr = module()
    p = tmp_path/'one.json'
    nr.write_exclusive(p, {'x': 1})
    with pytest.raises(FileExistsError):
        nr.write_exclusive(p, {'x': 2})
    with pytest.raises(ValueError):
        nr.write_exclusive(tmp_path/'bad.json', {'x': float('nan')})


def test_model_failure_does_not_become_verified_evidence(tmp_path):
    nr = module()
    result = nr.model_commentary('flow', {'summary': 'measured fact'}, Path('missing'), Path('missing'))
    assert result['status'] == 'BLOCKED'
    assert result['authority'] == 'UNVERIFIED_MODEL_INFERENCE'


def test_all_five_receipts_created_and_ui_envelopes_valid(tmp_path):
    nr = module()
    packet = dict(provider='coinbase', representation='BTC-USD spot', bars=bars(150),
                  retrieval_started=540001, retrieval_finished=540002, source_url='https://api.exchange.coinbase.com', raw_sha256='a'*64)
    result = nr.run_cycle(tmp_path, {'venue': packet}, {'headlines': [], 'series': [], 'gaps': ['offline']},
                          now=540002, run_id='fixture', code_revision='fixed', binary=None, model=None)
    assert set(result['lanes']) == {'flow', 'macro', 'aion', 'daedalus', 'omega'}
    for lane in result['lanes']:
        assert (tmp_path/result['lanes'][lane]['receipt_path']).is_file()
    required = {'event_id','at_utc','category','status','severity','summary','surface','source','paths','evidence','execution_authorized'}
    for path in (tmp_path/'automation_intelligence/mcp_interface/events').glob('*.json'):
        import json
        event = json.loads(path.read_text())
        assert required <= event.keys()
        assert event['execution_authorized'] is False


def test_run_id_cannot_escape_evidence_namespace(tmp_path):
    nr=module()
    with pytest.raises(ValueError):
        nr.run_cycle(tmp_path,{}, {},now=0,run_id='../escape',code_revision='fixed',binary=None,model=None)


def test_failed_local_generation_retried_on_unchanged_measurements(tmp_path,monkeypatch):
    nr=module()
    responses=iter([dict(status='BLOCKED',authority='UNVERIFIED_MODEL_INFERENCE')]*5 +
                   [dict(status='GENERATED',authority='UNVERIFIED_MODEL_INFERENCE')]*5)
    monkeypatch.setattr(nr,'model_commentary',lambda *args: next(responses))
    nr.run_cycle(tmp_path,{}, {'headlines':[],'series':[],'gaps':[]},now=0,run_id='one',code_revision='fixed',binary=Path('binary'),model=Path('model'))
    second=nr.run_cycle(tmp_path,{}, {'headlines':[],'series':[],'gaps':[]},now=1,run_id='two',code_revision='fixed',binary=Path('binary'),model=Path('model'))
    assert all(v['local_model_status']=='GENERATED' for v in second['lanes'].values())


def test_model_prompt_is_bounded_and_requests_next_test(monkeypatch,tmp_path):
    nr=module()
    import tools.github_native_local_model as lm
    from tools.github_native_ai_openai import ModelResponse
    observed={}
    def fake(request,**kwargs):
        observed['request']=request
        observed['kwargs']=kwargs
        return ModelResponse('local-test','completed',{'lane':'aion','summary':'Next test: collect more outcomes.','net_new_delta':'MEASURED_DELTA','data_gaps':[],'conflicts':[],'execution_authorized':False})
    monkeypatch.setattr(lm,'run_local_model',fake)
    nr.model_commentary('aion',{'summary':'measured','experiments':[{'representation':'venue','test':{'event_count':3,'control_count':90,'difference':.01},'qualification':'INSUFFICIENT_EVENTS','notes':'x'*5000}]*4},Path('bin'),Path('model'))
    assert len(observed['request'].input_text)<3000
    assert 'next test' in observed['request'].instructions.lower()
    assert observed['kwargs']['max_output_tokens']==384


def test_transport_failure_is_diagnosed_without_raw_model_text(monkeypatch):
    nr=module()
    import tools.github_native_local_model as lm
    from tools.github_native_ai_openai import TransportError
    def fail(*args,**kwargs):
        raise TransportError('local model runtime timed out')
    monkeypatch.setattr(lm,'run_local_model',fail)
    result=nr.model_commentary('aion',{'summary':'x'},Path('bin'),Path('model'))
    assert result['failure_code']=='TIMEOUT'


def test_local_model_cannot_invent_facts_or_conflicts(monkeypatch):
    nr=module()
    import tools.github_native_local_model as lm
    from tools.github_native_ai_openai import ModelResponse
    seen={}
    def fake(request,**kwargs):
        seen.update(kwargs)
        return ModelResponse('bad','completed',{'lane':'daedalus','summary':'Missing calibration for sensor X.','net_new_delta':'MEASURED_DELTA','data_gaps':['sensor X'],'conflicts':[],'execution_authorized':False})
    monkeypatch.setattr(lm,'run_local_model',fake)
    result=nr.model_commentary('daedalus',{'status':'VERIFIED','summary':'2 independent audits; no defects.','checks':[{},{}],'defects':[]},Path('bin'),Path('model'))
    assert result['status']=='BLOCKED'
    assert result['failure_code']=='UNGROUNDED_INTERPRETATION'
    schema=seen['output_schema']
    assert schema['properties']['summary']['enum']
    assert schema['properties']['conflicts']['maxItems']==0
