"""Compile full provider endpoint inventories from pinned official specifications."""
import argparse
import hashlib
import html
import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
import yaml

def resolve(obj, file):
    if isinstance(obj,dict) and '$ref' in obj:
        ref=obj['$ref']
        target,_,fragment=ref.partition('#')
        path=file.parent/target if target else file
        value=yaml.safe_load(path.read_text())
        for part in fragment.strip('/').split('/') if fragment else []:
            value=value[part.replace('~1','/').replace('~0','~')]
        return resolve(value,path)
    return obj

def openapi(provider, file):
    spec=yaml.safe_load(file.read_text())
    operations=[]
    for path,item in spec['paths'].items():
        item=resolve(item,file)
        for method,op in item.items():
            if method not in ('get','post','put','patch','delete'):
                continue
            params=[]
            for parameter in item.get('parameters',[])+op.get('parameters',[]):
                p=resolve(parameter,file)
                if p.get('in') not in ('path','query') or re.search('key|token|secret|password',p['name'],re.I):
                    continue
                schema=p.get('schema',p)
                default=p.get('example',p.get('x-example',schema.get('example',schema.get('default'))))
                if default in ('~null','undefined','null',''):
                    default=None
                params.append(dict(name=p['name'],location=p['in'],required=p.get('required',False),example=default,
                                   enum=schema.get('enum'),type=schema.get('type','string')))
            operations.append(dict(id=provider+':'+method+':'+path,path=path,method=method.upper(),
                summary=op.get('summary',op.get('operationId',path))[:160],tags=op.get('tags',[]),parameters=params))
    return operations

def twelve(root):
    operations=[]
    for file in sorted((root/'docs').glob('*Api.md')):
        text=file.read_text()
        for method,path in re.findall(r'\*\*(GET|POST|PUT|DELETE|PATCH)\*\* ([^ |\n]+)',text.split('\n\n\n')[0]):
            line=next((s for s in text.splitlines() if '**'+method+'** '+path+' |' in s),'')
            match=re.search(r'\[\*\*([^*]+)\*\*\]',line)
            function=match.group(1) if match else ''
            section=text.split('## '+function+'\n',1)[-1].split('\n## ',1)[0]
            params=[]
            if '### Parameters' in section:
                table=section.split('### Parameters',1)[1].split('### Return',1)[0]
                for name,typ,description,notes in re.findall(r'\| \*\*([^*]+)\*\* \| ([^|]+) \| ([^|]*) \| ([^|]*) \|',table):
                    params.append(dict(name=name,location='query',required='[Optional]' not in notes,
                        example=None,type=typ.strip(' `')))
            operations.append(dict(id='twelve:'+method.lower()+':'+path,path=path,method=method,
                summary=line.rsplit('|',2)[-2].strip() if line else path,tags=[file.stem],parameters=params))
    return list({o['id']:o for o in operations}.values())

def fmp(file):
    text=html.unescape(file.read_text())
    urls=sorted(set(re.findall(r'https://financialmodelingprep\.com/stable/[^\s"<>\\]+',text)))
    ops={}
    for url in urls:
        parsed=urlsplit(url)
        path=parsed.path.removeprefix('/stable')
        if not re.fullmatch(r'/[A-Za-z0-9/_-]+',path):
            continue
        params=[dict(name=k,location='query',required=True,example=v,type='string') for k,v in parse_qsl(parsed.query) if k!='apikey']
        ops.setdefault(path,dict(id='fmp:get:'+path,path=path,method='GET',summary=path,tags=[],parameters=params))
    return list(ops.values())

def quiver(file):
    text=file.read_text()
    paths=set(re.findall(r'https://api.quiverquant.com([^"\'\s]+)',text))
    return [dict(id='quiver:get:'+path,path=path+('{symbol}' if path.endswith('/') else ''),method='GET',summary=path,
                 tags=['OfficialPythonSDK'],parameters=[dict(name='symbol',location='path',required=True,example=None,type='string')] if path.endswith('/') else [])
            for path in sorted(paths)]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--sources',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    source=args.sources
    specs={'massive':source/'massive-openapi.json','intrinio':source/'intrinio-openapi.json','eodhd':source/'eodhd-openapi/openapi.yaml'}
    operations=[]
    for provider,file in specs.items():
        operations.extend(openapi(provider,file))
    operations+=twelve(source/'twelvedata-node')+fmp(source/'fmp-catalog-source')+quiver(source/'quiver-python/quiverquant.py')
    supplement=Path(__file__).resolve().parents[1]/'config/provider_catalog_supplement.json'
    extra=json.loads(supplement.read_text()) if supplement.exists() else {}
    operations=list({o['id']:o for o in operations+extra.get('operations',[])}.values())
    data=dict(schema_version='icarus-provider-endpoint-catalog-v1',operations=operations,
        provenance={p:dict(file=str(f.name),sha256=hashlib.sha256(f.read_bytes()).hexdigest()) for p,f in specs.items()},
        completeness='PINNED_OFFICIAL_CATALOG_SNAPSHOT; API_DRIFT_AND_UNREPRESENTED_TRANSPORTS_REMAIN_EXPLICIT')
    data['provenance'].update(extra.get('provenance',{}))
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
    print(json.dumps({p:sum(o['id'].startswith(p+':') for o in operations) for p in ('massive','intrinio','eodhd','twelve','fmp','quiver')}))

if __name__=='__main__':
    main()
