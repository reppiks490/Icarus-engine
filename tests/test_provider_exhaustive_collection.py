import json
from pathlib import Path
from urllib.error import HTTPError
import pytest
from tools import provider_exhaustive_collection as p

def operation(path='/stocks'):
    return dict(id='twelve:get:'+path,provider='twelve',path=path,method='GET',parameters=[])

def test_missing_key_is_a_blocker_not_success(tmp_path):
    result=p.cycle(tmp_path,[operation()],{},run_id='one',request_budget=2)
    assert result['providers']['twelve']['status']=='BLOCKED_MISSING_CREDENTIAL'
    assert result['requests']==0

def test_pagination_resumes_and_accounts_for_every_discovered_asset(tmp_path):
    seen=[]
    def fetch(provider,path,params,key):
        seen.append(params.copy())
        if 'page' not in params:
            return {'status':'ok','data':[{'symbol':'AA','exchange':'X'},{'symbol':'BB','exchange':'X'}], 'meta':{'current_page':1,'total_pages':2}}
        return {'status':'ok','data':[{'symbol':'CC','exchange':'Y'}], 'meta':{'current_page':2,'total_pages':2}}
    first=p.cycle(tmp_path,[operation()],{'TWELVE_DATA_API_KEY':'fixture'},run_id='one',request_budget=1,fetch=fetch)
    assert first['catalog']['assets']==2
    second=p.cycle(tmp_path,[operation()],{'TWELVE_DATA_API_KEY':'fixture'},run_id='two',request_budget=1,fetch=fetch)
    assert seen[-1]['page']==2
    assert second['catalog']['assets']==3
    assert second['catalog']['pending_pages']==0

def test_pagination_cannot_exfiltrate_key_to_other_host():
    with pytest.raises(ValueError):
        p.next_page('massive',{'next_url':'https://attacker.example/steal?apiKey=fixture'},{})

def test_rate_limit_does_not_lose_page_or_leak_error(tmp_path):
    def fail(*a):
        raise HTTPError('https://secret.example?apikey=fixture',429,'fixture-key',{},None)
    result=p.cycle(tmp_path,[operation()],{'TWELVE_DATA_API_KEY':'fixture'},run_id='one',request_budget=5,fetch=fail)
    assert result['requests']==1
    assert result['catalog']['pending_pages']==1
    assert 'fixture' not in json.dumps(result)

def test_denied_endpoint_is_recorded_without_repeated_hammering(tmp_path):
    calls=[]
    def deny(*a):
        calls.append(1)
        return {'status':'error','code':403,'message':'fixture-secret'}
    one=p.cycle(tmp_path,[operation()],{'TWELVE_DATA_API_KEY':'fixture'},run_id='one',request_budget=5,fetch=deny)
    two=p.cycle(tmp_path,[operation()],{'TWELVE_DATA_API_KEY':'fixture'},run_id='two',request_budget=5,fetch=deny)
    assert len(calls)==1
    assert two['catalog']['denied_operations']==1
    assert 'fixture-secret' not in json.dumps(one)

def test_databento_is_never_admitted(tmp_path):
    with pytest.raises(ValueError):
        p.cycle(tmp_path,[dict(operation(),provider='databento',id='databento:get:/x')],{},run_id='one')

def test_asset_endpoint_expands_across_entire_discovered_catalog(tmp_path):
    calls=[]
    ops=[operation(),dict(operation('/time_series'),parameters=[dict(name='symbol',location='query',required=True,example=None)])]
    def fetch(provider,path,params,key):
        calls.append((path,params.copy()))
        if path=='/stocks':return {'status':'ok','data':[{'symbol':'AA'},{'symbol':'BB'},{'symbol':'CC'}]}
        return {'status':'ok','values':[{'datetime':'2026-10-06','close':'100'},{'datetime':'2026-10-05','close':'99'}]}
    result=p.cycle(tmp_path,ops,{'TWELVE_DATA_API_KEY':'fixture'},run_id='one',request_budget=8,fetch=fetch)
    symbols={params['symbol'] for path,params in calls if path=='/time_series'}
    assert symbols=={'AA','BB','CC'}
    assert result['catalog']['asset_datasets_collected']==3

def test_non_read_operation_and_unresolved_parameter_remain_visible(tmp_path):
    ops=[dict(operation('/trade'),method='POST'),dict(operation('/x/{unknown}'),parameters=[dict(name='unknown',location='path',required=True,example=None)])]
    result=p.cycle(tmp_path,ops,{'TWELVE_DATA_API_KEY':'fixture'},run_id='one')
    assert result['requests']==0
    assert result['catalog']['unresolved_operations']==2

def test_full_vendor_payload_is_authenticated_encrypted_with_existing_provider_key(tmp_path):
    pytest.importorskip('cryptography')
    from tools.provider_archive import decrypt
    data={'data':[{'symbol':'AA','licensed_price':123.456}]}
    status=p.archive(tmp_path,'run','twelve','1-0',data,{},'fixture')
    assert status=='ENCRYPTED_AES256_GCM'
    file=next(tmp_path.rglob('*.enc'))
    assert b'licensed_price' not in file.read_bytes()
    assert decrypt(file.read_bytes(),'twelve','run','1-0',{'TWELVE_DATA_API_KEY':'fixture'})==data
    from cryptography.exceptions import InvalidTag
    with pytest.raises(InvalidTag):
        decrypt(file.read_bytes(),'twelve','wrong-run','1-0',{'TWELVE_DATA_API_KEY':'fixture'})


def test_encrypted_checkpoint_recovers_after_cache_eviction(tmp_path):
    import shutil
    def fetch(*args):return {'data':[{'symbol':'AA'},{'symbol':'BB'}], 'meta':{'current_page':1,'total_pages':2}}
    env={'TWELVE_DATA_API_KEY':'fixture'}
    first=p.cycle(tmp_path,[operation()],env,run_id='one',request_budget=1,fetch=fetch)
    assert first['checkpoint_status']=='ENCRYPTED_AES256_GCM'
    shutil.rmtree(tmp_path/'.provider_collection_cache')
    seen=[]
    def finish(provider,path,params,key):
        seen.append(params);return {'data':[{'symbol':'CC'}]}
    second=p.cycle(tmp_path,[operation()],env,run_id='two',request_budget=1,fetch=finish)
    assert seen[0]['page']==2
    assert second['catalog']['assets']==3

def test_research_features_are_order_independent_and_reject_nan():
    records=[{'close':'10'},{'close':'20'},{'close':'nan'}]
    assert p.research_features(records)==p.research_features(list(reversed(records)))
    assert p.research_features(records)['close']==dict(samples=2,mean=15,minimum=10,maximum=20,standard_deviation=5)


def test_verified_operations_are_exact_current_substantive_successes(tmp_path):
    ops=[operation('/filled'),operation('/empty'),operation('/denied'),operation('/unattempted')]
    seen=[]
    def fetch(provider,path,params,key):
        seen.append(path)
        if path=='/filled':
            return {'data':[{'close':123.456,'licensed_marker':'not-public'}],
                    'operation':'twelve:get:/unattempted'}
        if path=='/empty':return {'status':'ok','data':[]}
        raise HTTPError('https://api.twelvedata.com/denied',403,'fixture-secret',{},None)
    result=p.cycle(tmp_path,ops,{'TWELVE_DATA_API_KEY':'fixture'},run_id='operation-proof',request_budget=3,fetch=fetch)
    entry=result['providers']['twelve']
    assert seen==['/filled','/empty','/denied']
    assert entry['verified_operations']==['twelve:get:/filled']
    assert entry['substantive_work_performed'] is True
    assert entry['blocked'][0]['operation']=='twelve:get:/denied'
    assert 'not-public' not in json.dumps(result) and 'fixture-secret' not in json.dumps(result)
    assert result['execution_authorized'] is False and result['raw_payloads_public'] is False
    latest=json.loads((tmp_path/p.ROOT/'latest'/'twelve.json').read_text())
    assert latest['providers']['twelve']['verified_operations']==entry['verified_operations']


@pytest.mark.parametrize('data',[
    {}, {'status':'ok'}, {'data':[]}, {'data':[{}]}, {'data':[{'close':None}]},
    {'data':['']}, {'data':{'status':'ok'}}, {'data':[{'symbol':'  '}]},
    {'data':[{'close':float('nan')}]}, {'data':[{'close':float('inf')}]},
])
def test_http_success_without_substantive_rows_verifies_no_operation(tmp_path,data):
    result=p.cycle(tmp_path,[operation()],{'TWELVE_DATA_API_KEY':'fixture'},run_id='empty-proof',
                   request_budget=1,fetch=lambda *args:data)
    assert result['providers']['twelve']['verified_operations']==[]


def test_verified_operations_are_sorted_unique_and_do_not_reuse_prior_receipts(tmp_path):
    ops=[operation('/z'),operation('/a')]
    def fetch(provider,path,params,key):
        data={'data':[{'close':0}]}
        if path=='/z' and 'page' not in params:
            data['meta']={'current_page':1,'total_pages':2}
        return data
    first=p.cycle(tmp_path,ops,{'TWELVE_DATA_API_KEY':'fixture'},run_id='sorted-proof',request_budget=3,fetch=fetch)
    assert first['providers']['twelve']['verified_operations']==['twelve:get:/a','twelve:get:/z']
    second=p.cycle(tmp_path,ops,{'TWELVE_DATA_API_KEY':'fixture'},run_id='no-ready-proof',request_budget=1,
                   fetch=lambda *args:pytest.fail('completed jobs must remain idle'))
    assert second['providers']['twelve']['status']=='NO_READY_JOBS'
    assert second['providers']['twelve']['verified_operations']==[]


def test_later_operation_denial_prevents_qualification_despite_prior_page_success(tmp_path):
    def fetch(provider,path,params,key):
        if 'page' not in params:
            return {'data':[{'close':10}], 'meta':{'current_page':1,'total_pages':2}}
        return {'status':'error','code':403,'message':'fixture-secret'}
    result=p.cycle(tmp_path,[operation()],{'TWELVE_DATA_API_KEY':'fixture'},run_id='mixed-proof',request_budget=2,fetch=fetch)
    entry=result['providers']['twelve']
    assert entry['collected_rows']==1
    assert entry['substantive_work_performed'] is True
    assert entry['blocked'][0]['operation']==operation()['id']
    assert entry['verified_operations']==[]


def test_missing_credentials_and_non_read_operations_verify_nothing(tmp_path):
    missing=p.cycle(tmp_path,[operation()],{},run_id='missing-proof',request_budget=1)
    assert missing['providers']['twelve']['verified_operations']==[]
    assert missing['providers']['twelve']['substantive_work_performed'] is False
    nonread=p.cycle(tmp_path/'nonread',[dict(operation('/orders'),method='POST')],{'TWELVE_DATA_API_KEY':'fixture'},
                    run_id='nonread-proof',request_budget=1,fetch=lambda *args:pytest.fail('no non-GET requests'))
    assert nonread['providers']['twelve']['verified_operations']==[]
    assert nonread['requests']==0


@pytest.mark.parametrize('value',[
    {'payload':[]}, [None], {'payload':{'empty':{},'missing':None,'blank':'  '}},
    {'payload':[float('nan'), {'missing':None}, float('inf')]},
])
def test_nested_empty_or_nonfinite_content_does_not_verify_operation(tmp_path,value):
    result=p.cycle(tmp_path,[operation()],{'TWELVE_DATA_API_KEY':'fixture'},run_id='nested-empty',
                   request_budget=1,fetch=lambda *args:{'data':[{'nested':value}]})
    assert result['providers']['twelve']['verified_operations']==[]


@pytest.mark.parametrize('value',[{'payload':[0]}, {'payload':[False]}, {'payload':{'flag':True}}])
def test_populated_nested_zero_and_boolean_leaves_verify_operation(tmp_path,value):
    result=p.cycle(tmp_path,[operation()],{'TWELVE_DATA_API_KEY':'fixture'},run_id='nested-value',
                   request_budget=1,fetch=lambda *args:{'data':[{'nested':value}]})
    assert result['providers']['twelve']['verified_operations']==[operation()['id']]


def test_content_beyond_depth_bound_is_unverified(tmp_path):
    value=0
    for _ in range(100):value={'nested':value}
    result=p.cycle(tmp_path,[operation()],{'TWELVE_DATA_API_KEY':'fixture'},run_id='nested-depth',
                   request_budget=1,fetch=lambda *args:{'data':[value]})
    assert result['providers']['twelve']['verified_operations']==[]
