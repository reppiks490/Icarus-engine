"""Resumable, catalog-led non-Databento acquisition with explicit incomplete coverage.

No broker mutations, purchases, remote AI, credential logs or public raw payloads.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import math
import os
import re
import sqlite3
import time
import urllib.request
import urllib.error
import zlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit, parse_qsl, quote

def write_exclusive(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(data,indent=2,sort_keys=True,allow_nan=False)+'\n'
    with path.open('x',encoding='utf-8') as file:file.write(raw)
    if json.loads(path.read_text())!=data:raise ValueError('immutable read-back mismatch')

PROVIDERS={
 'massive':dict(base='https://api.massive.com',keys=['MASSIVE_API_KEY','POLYGON_API_KEY'],auth='bearer'),
 'twelve':dict(base='https://api.twelvedata.com',keys=['TWELVE_DATA_API_KEY','TWELVEDATA_API_KEY','TWELVE_API_KEY'],auth='twelve'),
 'fmp':dict(base='https://financialmodelingprep.com/stable',keys=['FMP_API_KEY'],auth='fmp'),
 'eodhd':dict(base='https://eodhd.com/api',keys=['EODHD_API_TOKEN','EODHD_API_KEY'],auth='eod'),
 'tiingo':dict(base='https://api.tiingo.com',keys=['TIINGO_API_TOKEN','TIINGO_API_KEY'],auth='token'),
 'intrinio':dict(base='https://api-v2.intrinio.com',keys=['INTRINIO_API_KEY','INTRINIO_API_TOKEN'],auth='intrinio'),
 'quiver':dict(base='https://api.quiverquant.com',keys=['QUIVER_API_KEY','QUIVER_API_TOKEN','QUIVER_QUANT_API_KEY'],auth='token'),
 'fred':dict(base='https://api.stlouisfed.org/fred',keys=['FRED_API_KEY'],auth='fred'),
 'alpaca':dict(base='https://data.alpaca.markets',keys=['ALPACA_API_KEY'],auth='alpaca'),
 'tickstream':dict(base='https://api.tick-stream.xyz/v1',keys=['TICKSTREAM_API_KEY','TICK_STREAM_API_KEY'],auth='bearer'),
 'bybit':dict(base='https://api.bybit.com',keys=[],auth='public'),
}
ROOT=Path('automation_intelligence/provider_collection_v1')
SECRET=re.compile(r'(api.?key|token|password|secret|authorization)',re.I)
ASSET_NAMES={'underlying','symbol','symbols','ticker','tickers','identifier','stocksticker','forexticker','cryptoticker','indicesticker','optionticker','security_id','series_id','release_id','source_id','category_id','exchangecode','exchange_code','exchange','exchangecode'}
CATALOG_PATHS={'/symbols','/v2/assets','/stocks','/forex_pairs','/cryptocurrencies','/etfs','/funds','/bonds','/commodities','/securities','/companies','/exchanges','/exchanges-list','/exchange-list','/stock-list','/etf-list','/cryptocurrency-list','/forex-list','/index-list','/v3/reference/tickers','/v3/reference/options/contracts','/v5/market/instruments-info','/sources','/releases','/tiingo/crypto','/tiingo/fx','/tiingo/fundamentals/meta','/tiingo/daily'}

class ProviderFailure(Exception):
    def __init__(self,code):self.code=code

def request(provider,path,params,key):
    spec=PROVIDERS[provider]
    if not path.startswith('/') or '://' in path or '..' in path or SECRET.search(path):
        raise ValueError('unsafe path')
    params={k:v for k,v in params.items() if v is not None and not SECRET.search(k)}
    headers={'User-Agent':'ICARUS-catalog-acquisition/1','Accept':'application/json'}
    auth=spec['auth']
    if auth=='bearer':headers['Authorization']='Bearer '+key
    elif auth=='twelve':headers['Authorization']='apikey '+key
    elif auth=='fmp':headers['apikey']=key
    elif auth=='eod':params.update(api_token=key,fmt='json')
    elif auth=='token':headers['Authorization']='Token '+key
    elif auth=='intrinio':params['api_key']=key
    elif auth=='fred':params.update(api_key=key,file_type='json')
    elif auth=='alpaca':
        headers.update({'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':os.environ.get('ALPACA_SECRET_KEY','')})
    base='https://paper-api.alpaca.markets' if provider=='alpaca' and path=='/v2/assets' else spec['base']
    url=base+path+'?'+urlencode(params,doseq=True)
    # Redirects must never carry provider credentials to another authority.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):raise ProviderFailure('REDIRECT_BLOCKED')
    with urllib.request.build_opener(NoRedirect).open(urllib.request.Request(url,headers=headers),timeout=20) as response:
        raw=response.read(20_000_001)
    if len(raw)>20_000_000:raise ProviderFailure('PAYLOAD_LIMIT_INCOMPLETE')
    return json.loads(raw)

def next_page(provider,data,current):
    if not isinstance(data,dict):return None
    if data.get('next_url'):
        url=urlsplit(data['next_url'])
        base=urlsplit(PROVIDERS[provider]['base'])
        if url.scheme!='https' or url.netloc!=base.netloc or url.username or url.password:
            raise ValueError('unsafe pagination authority')
        return dict(path=url.path,params={k:v for k,v in parse_qsl(url.query) if not SECRET.search(k)})
    token=data.get('next_page') or data.get('next_page_token') or data.get('nextPageToken')
    if token:return dict(params={**current,'next_page' if provider=='intrinio' else 'page_token':token})
    if provider=='bybit' and isinstance(data.get('result'),dict) and data['result'].get('nextPageCursor'):
        return dict(params={**current,'cursor':data['result']['nextPageCursor']})
    meta=data.get('meta',{})
    if isinstance(meta,dict) and meta.get('current_page') and meta.get('total_pages') and int(meta['current_page'])<int(meta['total_pages']):
        return dict(params={**current,'page':int(meta['current_page'])+1})
    if provider=='fred' and data.get('count') is not None:
        offset=int(data.get('offset',current.get('offset',0)))
        limit=int(data.get('limit',1000))
        if offset+limit<int(data['count']):return dict(params={**current,'offset':offset+limit})
    if provider in ('fmp','twelve') and 'page' in current and current.get('limit') and len(rows(data))==int(current['limit']):
        return dict(params={**current,'page':int(current['page'])+1})
    return None

def check_response(data):
    if isinstance(data,dict):
        code=data.get('code') or data.get('error_code') or data.get('retCode')
        if data.get('status') in ('error','ERROR','NOT_AUTHORIZED') or data.get('error') or data.get('Error Message') or data.get('error_message') or code not in (None,0,'0',200,'200'):
            if str(code) in ('401','403','402','429'):raise ProviderFailure(str(code))
            message=str(data.get('message') or data.get('error') or data.get('Error Message') or '')
            if re.search(r'quota|rate.limit|credits.*exhaust',message,re.I):raise ProviderFailure('429')
            if re.search(r'invalid.*key|unauthenticated|unauthorized.*key',message,re.I):raise ProviderFailure('401')
            if re.search(r'premium|upgrade|subscription|permission|forbidden|access denied',message,re.I):raise ProviderFailure('403')
            raise ProviderFailure('PROVIDER_ERROR')
    if not isinstance(data,(dict,list)):raise ProviderFailure('UNSUPPORTED_RESPONSE_FORMAT')

def rows(data):
    if isinstance(data,list):return [r if isinstance(r,dict) else {'symbol':r} for r in data if isinstance(r,(dict,str))]
    if isinstance(data,dict):
        for name in ('symbols','results','data','values','list','securities','companies','exchanges','releases','sources','categories','seriess','observations','stock_prices','options','trades','quotes','news'):
            if isinstance(data.get(name),list):return [r if isinstance(r,dict) else {'symbol':r} for r in data[name] if isinstance(r,(dict,str))]
        if isinstance(data.get('result'),dict):return rows(data['result'])
    return []

def bind(op,asset=None):
    path=op['path'];params={};unresolved=[]
    for p in op.get('parameters',[]):
        name=p['name'];value=p.get('example')
        if SECRET.search(name):continue
        if name.lower() in ASSET_NAMES and asset:
            value=asset.get('identifier') if name.lower() in ('series_id','release_id','source_id','category_id','security_id') else asset.get('symbol')
            if op['provider']=='eodhd' and name.lower() in ('ticker','symbol') and asset.get('exchange') and '.' not in str(value):
                value=str(value)+'.'+asset['exchange']
        elif name.lower() in ('exchange','exchange_code') and asset:
            value=asset.get('exchange') or value
        elif name=='interval' and op.get('provider')!='bybit':value='1day'
        elif name in ('limit','page_size','outputsize'):value=1000 if op['path'] in CATALOG_PATHS else 100
        elif name=='format':value='JSON'
        elif name in ('date','from','to','start_date','end_date'):
            # Catalog example dates prove shape, not fresh requested coverage.
            value=value
        if value is None:
            if p.get('required'):unresolved.append(name)
            continue
        if isinstance(value,(dict,list)) or isinstance(value,str) and len(value)>400:
            unresolved.append(name);continue
        if p.get('location')=='path':path=path.replace('{'+name+'}',quote(str(value),safe=':.-'))
        elif p.get('required') or name in ('limit','page_size','outputsize','interval'):
            params[name]=value
    if '{' in path or '}' in path:unresolved.append('path binding')
    if op['id'].startswith('twelve:') and any(p['name']=='symbol' for p in op.get('parameters',[])) and asset:
        params['symbol']=asset['symbol']
        if asset.get('exchange'):params['exchange']=asset['exchange']
    return path,params,unresolved

def database(root):
    directory=root/'.provider_collection_cache';directory.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(directory/'coverage.sqlite')
    db.executescript('''
      CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY,provider TEXT,descriptor TEXT,status TEXT);
      CREATE TABLE IF NOT EXISTS assets(id INTEGER PRIMARY KEY,provider TEXT,identity TEXT,descriptor TEXT,UNIQUE(provider,identity));
      CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY,operation TEXT,asset INTEGER DEFAULT 0,path TEXT,params TEXT,status TEXT,last_attempt REAL DEFAULT 0,pages INTEGER DEFAULT 0,UNIQUE(operation,asset));
      CREATE TABLE IF NOT EXISTS receipts(job INTEGER,at REAL,sha TEXT,rows INTEGER);
    ''')
    columns={row[1] for row in db.execute('PRAGMA table_info(jobs)')}
    for column in ('initial_path','initial_params'):
        if column not in columns:db.execute('ALTER TABLE jobs ADD COLUMN '+column+' TEXT')
    db.execute('UPDATE jobs SET initial_path=path,initial_params=params WHERE initial_path IS NULL')
    db.commit()
    return db

def compatible(op,asset):
    tags=' '.join(op.get('tags',[])).lower()
    market=asset.get('market','unknown').lower()
    if op.get('provider')=='bybit':
        category=next((p.get('example') for p in op.get('parameters',[]) if p['name']=='category'),None)
        return category==market
    names={p['name'].lower() for p in op.get('parameters',[])}
    for name,kind in [('series_id','series'),('release_id','release'),('source_id','source'),('category_id','category')]:
        if name in names:return asset.get('entity_kind')==kind
    if names & {'exchangecode','exchange_code'}:return asset.get('entity_kind')=='exchange'
    if asset.get('entity_kind') in ('exchange','release','source','series','category'):return False
    if 'options' in tags:return market=='options'
    if 'crypto' in tags:return market in ('crypto','cryptocurrencies','unknown')
    if 'fx:' in tags or 'forex' in tags:return market in ('fx','forex','forex_pairs','unknown')
    if 'indices:' in tags:return market in ('indices','unknown')
    if 'stocks:' in tags or 'fundamental' in tags:return market in ('stocks','stock','etf','etfs','unknown')
    return True

def seed(db,operations):
    for op in operations:
        provider=op.get('provider') or op['id'].split(':',1)[0]
        if provider not in PROVIDERS:raise ValueError('provider is not admitted')
        op={**op,'provider':provider}
        asset_mode=any(p['name'].lower() in ASSET_NAMES for p in op.get('parameters',[])) and (op['path'] not in CATALOG_PATHS or any(p.get('required') and p['name'].lower() in ASSET_NAMES for p in op.get('parameters',[])))
        path,params,missing=bind(op)
        status='NON_READ_OPERATION' if op['method']!='GET' else 'ASSET_TEMPLATE' if asset_mode else 'PARAMETER_BINDING_BLOCKED' if missing else 'QUEUED'
        db.execute('INSERT INTO operations VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET descriptor=excluded.descriptor',(op['id'],provider,json.dumps(op),status))
        if status=='QUEUED':db.execute('INSERT OR IGNORE INTO jobs(operation,path,params,status) VALUES(?,?,?,?)',(op['id'],path,json.dumps(params),'PENDING'))
    db.commit()

def discover_assets(db,provider,op,data):
    if op['path'] not in CATALOG_PATHS and not any(s in op['path'] for s in ('exchange-symbol-list','/release/series','/source/releases','/category/children','/category/series')):return
    for row in rows(data):
        symbol=row.get('symbol') or row.get('ticker') or row.get('Code') or row.get('code')
        identifier=row.get('id') if provider=='fred' or op['path'] in ('/securities','/companies') else None
        if not symbol and not identifier:continue
        symbol=str(symbol or identifier)
        if len(symbol)>150 or SECRET.search(symbol):continue
        kind=('series' if 'series' in op['path'] else 'release' if 'releases' in op['path'] else 'source' if 'sources' in op['path'] else 'category') if provider=='fred' else 'exchange' if 'exchange' in op['path'] and 'symbol-list' not in op['path'] else 'instrument'
        asset=dict(symbol=symbol,exchange=str(row.get('exchange') or row.get('mic_code') or row.get('Exchange') or ''),entity_kind=kind,
                   identifier=str(identifier or symbol),market=str(row.get('market') or next((p.get('example') for p in op.get('parameters',[]) if p['name']=='category'),None) or op['path'].strip('/').split('/')[-1]),source_operation=op['id'])
        identity=json.dumps({k:v for k,v in asset.items() if k!='source_operation'},sort_keys=True)
        db.execute('INSERT OR IGNORE INTO assets(provider,identity,descriptor) VALUES(?,?,?)',(provider,identity,json.dumps(asset)))

def next_asset_job(db,provider):
    # Lazy expansion preserves every discovered identity without a huge in-memory cross product.
    templates=db.execute("SELECT id,descriptor FROM operations WHERE provider=? AND status='ASSET_TEMPLATE' ORDER BY (SELECT count(*) FROM jobs WHERE operation=operations.id),id",(provider,)).fetchall()
    for op_id,raw in templates:
        op=json.loads(raw)
        for aid,descriptor in db.execute('SELECT id,descriptor FROM assets WHERE provider=? AND id NOT IN (SELECT asset FROM jobs WHERE operation=?) ORDER BY id',(provider,op_id)):
            asset=json.loads(descriptor)
            if not compatible(op,asset):continue
            path,params,missing=bind(op,asset)
            if missing:continue
            db.execute('INSERT OR IGNORE INTO jobs(operation,asset,path,params,status) VALUES(?,?,?,?,?)',(op_id,aid,path,json.dumps(params),'PENDING'))
            db.execute('UPDATE jobs SET initial_path=path,initial_params=params WHERE initial_path IS NULL');db.commit();return

def archive(root,run_id,provider,job,data,env,provider_key=''):
    encoded=env.get('ICARUS_DATA_ARCHIVE_KEY','').strip()
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives import hashes
        if encoded:key=base64.b64decode(encoded,validate=True)
        elif provider_key:key=HKDF(algorithm=hashes.SHA256(),length=32,salt=b'icarus-provider-archive-v1',info=provider.encode()).derive(provider_key.encode())
        else:return 'NOT_RETAINED_ARCHIVE_KEY_MISSING'
        if len(key)!=32:return 'NOT_RETAINED_ARCHIVE_KEY_INVALID'
        nonce=os.urandom(12)
        payload=zlib.compress(json.dumps(data,separators=(',',':')).encode())
        directory=root/'.provider_collection_archives'/run_id/provider
        directory.mkdir(parents=True,exist_ok=True)
        aad=f'{run_id}:{provider}:{job}'.encode()
        (directory/(str(job)+'.enc')).write_bytes(nonce+AESGCM(key).encrypt(nonce,payload,aad))
        return 'ENCRYPTED_AES256_GCM'
    except (ValueError,ImportError):return 'NOT_RETAINED_ARCHIVE_UNAVAILABLE'

def research_features(records):
    # Order-independent descriptive research features; no fabricated chronology or forecasts.
    features={}
    for field in ('close','price','value','volume','open_interest'):
        values=[]
        for row in records:
            try:
                value=float(row.get(field))
                if math.isfinite(value):values.append(value)
            except (TypeError,ValueError):pass
        if len(values)>=2:
            mean=sum(values)/len(values)
            features[field]=dict(samples=len(values),mean=mean,minimum=min(values),maximum=max(values),standard_deviation=math.sqrt(sum((v-mean)**2 for v in values)/len(values)))
    return features

def coverage(db):
    count=lambda sql:db.execute(sql).fetchone()[0]
    return dict(operations=count('SELECT count(*) FROM operations'),assets=count('SELECT count(*) FROM assets'),
        pending_pages=count("SELECT count(*) FROM jobs WHERE status='PENDING'"),
        denied_operations=count("SELECT count(DISTINCT operation) FROM jobs WHERE status='DENIED' AND asset=0"),
        unresolved_operations=count("SELECT count(*) FROM operations WHERE status IN ('NON_READ_OPERATION','PARAMETER_BINDING_BLOCKED')"),
        asset_datasets_collected=count("SELECT count(*) FROM jobs WHERE asset<>0 AND status='COLLECTED'"),
        collected_operations=count("SELECT count(DISTINCT operation) FROM jobs WHERE status='COLLECTED'"),
        asset_templates=count("SELECT count(*) FROM operations WHERE status='ASSET_TEMPLATE'"),
        qualification='INCOMPLETE_UNTIL_EVERY_OPERATION_ASSET_PAGE_TIME_RANGE_AND_TRANSPORT_IS_VERIFIED')

def cycle(root,operations,env,*,run_id,request_budget=20,fetch=request,delay_seconds=0):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,100}',run_id):raise ValueError('unsafe run ID')
    if not 1<=request_budget<=200:raise ValueError('invalid provider request ceiling')
    selected={op.get('provider',op['id'].split(':',1)[0]) for op in operations}
    if len(selected)==1:
        provider=next(iter(selected)); checkpoint=root/ROOT/'checkpoints'/(provider+'.enc')
        if checkpoint.exists() and not (root/'.provider_collection_cache/coverage.sqlite').exists():
            try:
                from tools.provider_archive import decrypt
                saved=decrypt(checkpoint.read_bytes(),provider,'checkpoint',provider,env)
                directory=root/'.provider_collection_cache';directory.mkdir(parents=True,exist_ok=True)
                (directory/'coverage.sqlite').write_bytes(base64.b64decode(saved['sqlite']))
            except Exception:pass # Key rotation or damaged checkpoint is visible through fresh catalog counts.
    db=database(root);seed(db,operations)
    db.execute('UPDATE jobs SET initial_path=path,initial_params=params WHERE initial_path IS NULL');db.commit()
    # Refresh daily and retry denied endpoints weekly; never erase the historical attempt receipts.
    db.execute("UPDATE jobs SET status='PENDING',path=initial_path,params=initial_params,pages=0 WHERE status IN ('COLLECTED','FAILED') AND last_attempt<?",(time.time()-86400,))
    db.execute("UPDATE jobs SET status='PENDING' WHERE status='DENIED' AND last_attempt<?",(time.time()-7*86400,))
    db.commit()
    result=dict(schema_version='icarus-provider-collection-cycle-v1',run_id=run_id,started_at_utc=datetime.now(timezone.utc).isoformat(),
                providers={},requests=0,execution_authorized=False,chatgpt_tokens_used=0,paid_model_calls=0,
                databento_excluded=True,raw_payloads_public=False)
    for provider in sorted({(op.get('provider') or op['id'].split(':',1)[0]) for op in operations}):
        spec=PROVIDERS[provider];key=next((env.get(k,'').strip() for k in spec['keys'] if env.get(k,'').strip()),'')
        entry=dict(status='PENDING',credential_present=bool(key),requests=0,collected_pages=0,collected_rows=0,blocked=[],archive_status=[],research_features=[],
                   endpoint_count=db.execute('SELECT count(*) FROM operations WHERE provider=?',(provider,)).fetchone()[0])
        result['providers'][provider]=entry
        if spec['keys'] and not key:
            entry['status']='BLOCKED_MISSING_CREDENTIAL';continue
        if provider=='alpaca' and not env.get('ALPACA_SECRET_KEY'):
            entry['status']='BLOCKED_MISSING_CREDENTIAL';continue
        for attempt in range(request_budget):
            if attempt%2==1:next_asset_job(db,provider)
            job=db.execute("SELECT j.id,j.operation,j.path,j.params,j.asset,o.descriptor FROM jobs j JOIN operations o ON j.operation=o.id WHERE o.provider=? AND j.status='PENDING' ORDER BY CASE WHEN j.asset=0 AND j.path IN ("+','.join('?' for _ in CATALOG_PATHS)+") THEN 0 ELSE 1 END,j.last_attempt,j.id LIMIT 1",(provider,*CATALOG_PATHS)).fetchone()
            if job is None:
                next_asset_job(db,provider)
                job=db.execute("SELECT j.id,j.operation,j.path,j.params,j.asset,o.descriptor FROM jobs j JOIN operations o ON j.operation=o.id WHERE o.provider=? AND j.status='PENDING' ORDER BY j.id LIMIT 1",(provider,)).fetchone()
            if job is None:break
            jid,opid,path,param_raw,aid,descriptor=job;params=json.loads(param_raw);op=json.loads(descriptor)
            entry['requests']+=1;result['requests']+=1
            db.execute('UPDATE jobs SET last_attempt=? WHERE id=?',(time.time(),jid));db.commit()
            try:
                data=fetch(provider,path,params,key);check_response(data)
                continuation=next_page(provider,data,params)
                discover_assets(db,provider,op,data)
                sha=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                prior=db.execute('SELECT sha FROM receipts WHERE job=? ORDER BY at DESC LIMIT 1',(jid,)).fetchone()
                page_count=db.execute('SELECT pages FROM jobs WHERE id=?',(jid,)).fetchone()[0]
                if continuation and page_count and prior and prior[0]==sha:raise ProviderFailure('PAGINATION_REPEAT_INCOMPLETE')
                db.execute('INSERT INTO receipts VALUES(?,?,?,?)',(jid,time.time(),sha,len(rows(data))))
                entry['archive_status'].append(archive(root,run_id,provider,str(jid)+'-'+str(attempt),data,env,key))
                if continuation:
                    next_path=continuation.get('path',path);next_params=continuation['params']
                    if next_path==path and next_params==params:raise ProviderFailure('PAGINATION_DID_NOT_ADVANCE')
                    db.execute("UPDATE jobs SET path=?,params=?,pages=pages+1 WHERE id=?",(next_path,json.dumps(next_params),jid))
                else:db.execute("UPDATE jobs SET status='COLLECTED',pages=pages+1 WHERE id=?",(jid,))
                entry['collected_pages']+=1
                entry['collected_rows']+=len(rows(data))
                feature=research_features(rows(data))
                if feature:entry['research_features'].append(dict(operation=opid,features=feature))
            except Exception as exc:
                code=str(exc.code) if isinstance(exc,(urllib.error.HTTPError,ProviderFailure)) else type(exc).__name__
                entry['blocked'].append(dict(operation=opid,asset_specific=bool(aid),failure_code=code))
                if code in ('401','429'):
                    entry['status']='BLOCKED_AUTHENTICATION' if code=='401' else 'QUOTA_OR_RATE_LIMIT_PAUSED'
                    db.commit();break
                db.execute("UPDATE jobs SET status=? WHERE id=?",('DENIED' if code in ('402','403') else 'FAILED',jid))
            db.commit()
            if delay_seconds and attempt+1<request_budget:time.sleep(delay_seconds)
        if entry['status']=='PENDING':entry['status']='COLLECTED_PARTIAL' if entry['collected_pages'] else 'BLOCKED' if entry['blocked'] else 'NO_READY_JOBS'
        entry['archive_status']=sorted(set(entry['archive_status']))
        entry['substantive_work_performed']=bool(entry['collected_rows'])
    result['catalog']=coverage(db)
    result['completed_at_utc']=datetime.now(timezone.utc).isoformat()
    if len(selected)==1:
        provider=next(iter(selected)); key=next((env.get(k,'').strip() for k in PROVIDERS[provider]['keys'] if env.get(k,'').strip()),'')
        if key or env.get('ICARUS_DATA_ARCHIVE_KEY'):
            checkpoint_status=archive(root,'checkpoint',provider,provider,{'sqlite':base64.b64encode(db.serialize()).decode()},env,key)
            if checkpoint_status=='ENCRYPTED_AES256_GCM':
                directory=root/ROOT/'checkpoints';directory.mkdir(parents=True,exist_ok=True)
                (directory/(provider+'.enc')).write_bytes((root/'.provider_collection_archives/checkpoint'/provider/(provider+'.enc')).read_bytes())
            result['checkpoint_status']=checkpoint_status
    db.close()
    receipt=ROOT/'cycles'/run_id/'receipt.json';write_exclusive(root/receipt,result)
    latest_dir=root/ROOT/'latest';latest_dir.mkdir(parents=True,exist_ok=True)
    for provider in result['providers']:
        (latest_dir/(provider+'.json')).write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    event=dict(schema_version='icarus-mcp-event-v1',event_id=run_id+'-provider-coverage',at_utc=result['completed_at_utc'],
        category='AUDIT',source='MACRO_AUTOMATION',status='DEGRADED',severity='MEDIUM',surface=['Provider entitlement and collection coverage'],
        summary=f'Provider catalog acquisition: {result["requests"]} requests; full coverage remains explicitly incomplete.',
        paths=[str(receipt)],evidence=[dict(classification='FACT',provider_status={k:v['status'] for k,v in result['providers'].items()},catalog=result['catalog'])],
        supermesh_x=dict(status='DEGRADED',finding='Endpoint/asset queues and authentication, entitlement, pagination and archive gaps recorded.'),
        execution_authorized=False)
    write_exclusive(root/'automation_intelligence/mcp_interface/events'/('provider-coverage-'+run_id+'.json'),event)
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path('.'))
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--request-budget',type=int,default=20)
    parser.add_argument('--delay-seconds',type=float,default=13)
    parser.add_argument('--provider',choices=sorted(PROVIDERS))
    args=parser.parse_args()
    catalog=json.loads((args.root/'config/provider_endpoint_catalog.json').read_text())
    operations=[op for op in catalog['operations'] if not args.provider or op.get('provider',op['id'].split(':',1)[0])==args.provider]
    repo=os.environ.get('GITHUB_REPOSITORY','')
    preferred='reppiks490/Icarus' if args.provider=='intrinio' else 'reppiks490/Icarus-engine'
    own_key=next((os.environ.get(k,'').strip() for k in PROVIDERS[args.provider]['keys'] if os.environ.get(k,'').strip()),'') if args.provider else ''
    if args.provider and repo and repo!=preferred and (own_key or not PROVIDERS[args.provider]['keys']):
        # Secondary repo takes over only on a fresh explicit missing/authentication owner failure.
        try:
            url=f'https://raw.githubusercontent.com/{preferred}/main/{ROOT}/latest/{args.provider}.json'
            with urllib.request.urlopen(url,timeout=15) as response:previous=json.load(response)
            at=datetime.fromisoformat(previous['completed_at_utc'])
            entry=previous['providers'][args.provider]
            may_failover=(datetime.now(timezone.utc)-at).total_seconds()<21600 and entry['status'] in ('BLOCKED_MISSING_CREDENTIAL','BLOCKED_AUTHENTICATION')
        except Exception:may_failover=False
        if not may_failover:
            status=dict(schema_version='icarus-provider-owner-standby-v1',run_id=args.run_id,provider=args.provider,
                credential_present=bool(own_key),preferred_repository=preferred,status='STANDBY_PREFERRED_OWNER',
                execution_authorized=False,chatgpt_tokens_used=0,paid_model_calls=0,databento_excluded=True)
            receipt=ROOT/'cycles'/args.run_id/'receipt.json';write_exclusive(args.root/receipt,status)
            latest=args.root/ROOT/'latest';latest.mkdir(parents=True,exist_ok=True)
            (latest/(args.provider+'.json')).write_text(json.dumps(status,indent=2)+'\n')
            event=dict(schema_version='icarus-mcp-event-v1',event_id=args.run_id+'-provider-standby',at_utc=datetime.now(timezone.utc).isoformat(),category='AUDIT',source='MACRO_AUTOMATION',status='DEGRADED',severity='LOW',surface=['Provider ownership'],summary='Secondary provider collector defers to preferred repository; no duplicate API requests.',paths=[str(receipt)],evidence=[dict(classification='FACT',preferred_repository=preferred,credential_present=bool(own_key))],execution_authorized=False)
            write_exclusive(args.root/'automation_intelligence/mcp_interface/events'/('provider-coverage-'+args.run_id+'.json'),event)
            print(json.dumps(status));return
    result=cycle(args.root,operations,os.environ,run_id=args.run_id,request_budget=args.request_budget,delay_seconds=args.delay_seconds)
    print(json.dumps(dict(providers={k:v['status'] for k,v in result['providers'].items()},requests=result['requests'],coverage=result['catalog'])))

if __name__=='__main__':main()
