"""Five substantive research lanes on Actions, with optional local-only interpretation.

No ChatGPT task creation, remote model transport, strategy promotion or trading.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import re
import statistics as st
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('automation_intelligence/native_research_v1')
LANES = ('flow','macro','aion','daedalus','omega')
SOURCES = {lane: lane.upper()+'_AUTOMATION' for lane in LANES}
BASELINE = 28
THRESHOLD = 2.5


def stamp(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace('+00:00','Z')


def digest(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def write_exclusive(path, data):
    raw = json.dumps(data,indent=2,sort_keys=True,allow_nan=False)+'\n'
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:
        f.write(raw)
    if json.loads(path.read_text()) != data:
        raise ValueError('read-back mismatch')


def normalize_bars(provider, raw, retrieved_at):
    out = {}
    for row in raw:
        if provider == 'coinbase':
            start,low,high,op,close,volume = row[:6]
        elif provider == 'kraken':
            start,op,high,low,close,_,volume = row[:7]
        elif provider == 'bybit':
            start,op,high,low,close,volume = row[:6]
            start = int(start)/1000
        else:
            raise ValueError('unsupported representation')
        start = int(start)
        if start % 3600:
            raise ValueError('unaligned event clock')
        op,high,low,close,volume = map(float,(op,high,low,close,volume))
        if not all(math.isfinite(x) for x in (op,high,low,close,volume)):
            raise ValueError('nonfinite candle')
        if low <= 0 or high < max(op,close,low) or low > min(op,close) or volume < 0:
            raise ValueError('invalid candle geometry')
        b = dict(start=start,end=start+3600,open=op,high=high,low=low,close=close,volume=volume)
        if b['end'] > retrieved_at:
            continue
        if start in out and out[start] != b:
            raise ValueError('conflicting duplicate event')
        out[start] = b
    return [out[k] for k in sorted(out)]


def robust_z(value, baseline):
    if not baseline:
        return None
    median = st.median(baseline)
    mad = st.median([abs(v-median) for v in baseline])
    return (value-median)/(1.4826*mad) if mad > 0 else None


def score_bars(bars):
    out = []
    for i,b in enumerate(bars):
        prior = bars[max(0,i-BASELINE):i]
        valid = len(prior) == BASELINE and all(
            prior[j]['end'] == prior[j+1]['start'] for j in range(len(prior)-1)) and prior[-1]['end'] == b['start']
        ranges = [p['high']-p['low'] for p in prior]
        volumes = [p['volume'] for p in prior]
        out.append(dict(start=b['start'],end=b['end'],range=b['high']-b['low'],volume=b['volume'],
                        range_z=robust_z(b['high']-b['low'],ranges) if valid else None,
                        volume_z=robust_z(b['volume'],volumes) if valid else None,
                        baseline_start=prior[0]['start'] if valid else None,
                        baseline_end=prior[-1]['end'] if valid else None,
                        baseline_count=len(prior) if valid else 0))
    return out


def flow_research(packets, now):
    current,gaps = [],[]
    for key,p in packets.items():
        if not p['bars']:
            gaps.append(f'{key}: empty')
            continue
        latest = score_bars(p['bars'])[-1]
        # Latest completed bar should be less than one hour old at retrieval.
        if not 0 <= now-latest['end'] <= 3900:
            gaps.append(f'{key}: stale, latest end {stamp(latest["end"])}')
            continue
        rz,vz = latest['range_z'],latest['volume_z']
        state = ('BASELINE_UNAVAILABLE' if rz is None or vz is None else
                 'JOINT_EXPANSION' if rz >= THRESHOLD and vz >= THRESHOLD else
                 'RANGE_ONLY' if rz >= THRESHOLD else
                 'TURNOVER_ONLY' if vz >= THRESHOLD else 'ORDINARY')
        current.append(dict(lane_key=key,provider=p['provider'],representation=p['representation'],state=state,**latest))
    conflicts = []
    comparable = [v for v in current if v['provider'] in ('coinbase','kraken')]
    if len(comparable) > 1 and len({v['start'] for v in comparable}) == 1:
        lo,hi = min(v['range'] for v in comparable),max(v['range'] for v in comparable)
        if lo > 0 and hi/lo > 1.3:
            conflicts.append('Same-hour USD spot ranges differ by more than 30%; retain venue identities, do not fuse baselines.')
    return dict(status='VERIFIED' if current else 'BLOCKED',current=current,conflicts=conflicts,gaps=gaps,
                provider_family_count=len({v['provider'] for v in current}),
                summary='; '.join(f'{v["lane_key"]}: {v["state"]}' for v in current) or 'No fresh completed market observations.',
                limits=['Candle volume is representation-specific reported activity, not directional order flow.',
                        'No depth-history, liquidation, absorption or cross-asset causal claim.'])


def aion_research(packets):
    experiments = []
    for key,p in packets.items():
        bars = p['bars']
        if len(bars) < 100:
            continue
        scores = score_bars(bars)
        samples = []
        for i in range(BASELINE,len(bars)-1):
            # Labels are later outcomes; feature uses only bars before/at decision time.
            if bars[i]['end'] != bars[i+1]['start'] or scores[i]['volume_z'] is None:
                continue
            samples.append(dict(start=bars[i]['start'],end=bars[i+1]['end'],
                                event=scores[i]['volume_z'] >= THRESHOLD,
                                outcome=(bars[i+1]['high']-bars[i+1]['low'])/bars[i]['close']))
        if len(samples)<60:
            continue
        split = int(len(samples)*.6)
        train,test = samples[:split], samples[split+2:]
        def describe(rows):
            event = [r['outcome'] for r in rows if r['event']]
            control = [r['outcome'] for r in rows if not r['event']]
            return dict(event_count=len(event),control_count=len(control),
                        event_mean_next_range=st.mean(event) if event else None,
                        control_mean_next_range=st.mean(control) if control else None,
                        difference=st.mean(event)-st.mean(control) if event and control else None)
        tr,te=describe(train),describe(test)
        experiments.append(dict(hypothesis_id='reported-volume-z2.5-next-hour-range-v1',representation=key,
                                fixed_threshold=THRESHOLD,baseline_hours=BASELINE,train=tr,test=te,
                                train_last_end=train[-1]['end'],test_first_start=test[0]['start'],embargo_samples=2,
                                qualification='DESCRIPTIVE_OOS_ONLY' if te['event_count']>=5 and te['control_count']>=20 else 'INSUFFICIENT_EVENTS',
                                performance_claim=False,costs='NOT_APPLICABLE_NONTRADING_ASSOCIATION',
                                multiple_testing='One fixed hypothesis per representation; repeated rolling windows overlap and are not independent confirmations.',
                                causal_claim=False))
    return dict(status='VERIFIED' if experiments else 'BLOCKED',experiments=experiments,
                summary=f'{len(experiments)} temporally separated descriptive experiments measured.',
                gaps=['No strategy profitability, causal effect or model-promotion claim.',
                      'Small event samples remain unqualified; these rolling holdouts are diagnostic, not a reusable promotion holdout.'])


def audit_research(packets, flow):
    # Independent scalar oracle; intentionally does not call robust_z or score_bars.
    checks,defects = [],[]
    for row in flow.get('current',[]):
        key = row['lane_key']
        data = packets[key]['bars']
        b = next((b for b in data if b['start']==row['start']),None)
        if b is None:
            defects.append(f'{key}: missing observation')
            continue
        prior = [p for p in data if p['end']<=b['start']][-BASELINE:]
        contiguous = len(prior)==BASELINE and all(prior[j]['end']==prior[j+1]['start'] for j in range(len(prior)-1)) and prior[-1]['end']==b['start']
        for field,value in (('range_z',b['high']-b['low']),('volume_z',b['volume'])):
            vals=[p['high']-p['low'] if field=='range_z' else p['volume'] for p in prior]
            expected=None
            if contiguous:
                ordered=sorted(vals)
                med=(ordered[13]+ordered[14])/2
                dev=sorted(abs(x-med) for x in vals)
                mad=(dev[13]+dev[14])/2
                if mad>0:
                    expected=(value-med)/(1.4826*mad)
            actual=row.get(field)
            if (actual is None)!=(expected is None) or (actual is not None and not math.isclose(actual,expected,rel_tol=1e-10,abs_tol=1e-10)):
                defects.append(f'{key}: independent {field} oracle mismatch')
        if row['end']>packets[key]['retrieval_finished']:
            defects.append(f'{key}: incomplete bar admitted')
        checks.append(dict(representation=key,oracle='independently coded sorted scalar MAD',baseline_count=len(prior),
                           future_excluded=True,range_and_volume_checked=True))
    return dict(status='BLOCKING' if defects else 'VERIFIED' if checks else 'BLOCKED',checks=checks,defects=defects,
                summary=f'{len(checks)} independent measurement audits; {len(defects)} defects.',
                scope='Current cycle statistics/time integrity only; not certification of the entire ICARUS system.')


def macro_research(raw, now):
    recent = [h for h in raw.get('headlines',[]) if h.get('published_epoch') is not None and 0<=now-h['published_epoch']<=72*3600]
    series = []
    for s in raw.get('series',[]):
        obs = s['observations']
        if len(obs)<2:
            continue
        latest,prior=obs[-1],obs[-2]
        event = datetime.fromisoformat(latest['date']).replace(tzinfo=timezone.utc).timestamp()
        age = now-event
        series.append(dict(series=s['series'],date=latest['date'],value=latest['value'],
                           prior_date=prior['date'],change=latest['value']-prior['value'],
                           freshness='DAILY_OBSERVATION' if 0<=age<=7*86400 else 'STALE',source_url=s['source_url']))
    return dict(status='VERIFIED' if recent or any(s['freshness']!='STALE' for s in series) else 'BLOCKED',
                releases=recent,series=series,gaps=raw.get('gaps',[]),
                summary=f'{len(recent)} dated official release headlines; {len(series)} daily macro series measured.',
                limits='Publication and daily change are facts; surprise, causality and intraday propagation remain unverified.')


def model_commentary(lane, measured, binary, model):
    from tools.github_native_ai_openai import ModelRequest
    from tools.github_native_local_model import LOCAL_MODEL_ID,run_local_model
    try:
        request = ModelRequest(lane,LOCAL_MODEL_ID,'none',
            'You are a research assistant. Use only supplied measurements. Return the required JSON. '
            'Do not invent numbers, causes, missing data or execution authority. Suggest a falsifiable next test. '
            'This output is unverified interpretation and cannot change measured facts. execution_authorized=false.',
            json.dumps(measured,sort_keys=True,allow_nan=False)[:8500])
        response=run_local_model(request,binary=binary,model=model,timeout_seconds=120)
        return dict(status='GENERATED',authority='UNVERIFIED_MODEL_INFERENCE',model=LOCAL_MODEL_ID,
                    response_id=response.response_id,payload=response.payload)
    except Exception as exc:
        return dict(status='BLOCKED',authority='UNVERIFIED_MODEL_INFERENCE',error_type=type(exc).__name__)


def semantic_state(lane,result):
    if lane=='flow':
        return dict(status=result['status'],states={v['lane_key']:v['state'] for v in result['current']},conflicts=result['conflicts'],gaps=result['gaps'])
    if lane=='macro':
        return dict(status=result['status'],releases=sorted(h['source_url'] for h in result['releases']),series=result['series'])
    if lane=='aion':
        return dict(status=result['status'],experiments=[{k:e[k] for k in ('hypothesis_id','representation','qualification')} for e in result['experiments']])
    if lane=='daedalus':
        return dict(status=result['status'],defects=result['defects'])
    return dict(status=result['status'],lane_status=result['lane_status'],blockers=result['blockers'])


def run_cycle(root, packets, macro_raw, *,now,run_id,code_revision,binary,model,acquisition_gaps=None):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,100}',run_id):
        raise ValueError('unsafe run identity')
    cycle=ROOT/'cycles'/run_id
    evidence_path=cycle/'evidence.json'
    write_exclusive(root/evidence_path,dict(schema_version='icarus-native-evidence-v1',market=packets,macro=macro_raw,
                                          acquired_at=stamp(now),code_revision=code_revision,execution_authorized=False))
    measurements={}
    measurements['flow']=flow_research(packets,now)
    measurements['flow']['gaps']+=acquisition_gaps or []
    measurements['macro']=macro_research(macro_raw,now)
    measurements['aion']=aion_research(packets)
    measurements['daedalus']=audit_research(packets,measurements['flow'])
    blockers=[f'{k}: {v["status"]}' for k,v in measurements.items() if v['status'] in ('BLOCKED','BLOCKING')]
    measurements['omega']=dict(status='DEGRADED' if blockers else 'VERIFIED',lane_status={k:v['status'] for k,v in measurements.items()},
                                blockers=blockers,summary='Measured lane results reconciled; '+('; '.join(blockers) or 'no blocking measurement defects.'),
                                limits='Synthesis does not grant promotion, strategy or execution authority.')
    previous_path=root/ROOT/'latest.json'
    previous=json.loads(previous_path.read_text()) if previous_path.is_file() else {}
    states,lanes={},{}
    for lane in LANES:
        measured=measurements[lane]
        state=digest(semantic_state(lane,measured))
        states[lane]=state
        changed=state!=previous.get('state_hashes',{}).get(lane)
        # Local reasoning runs only on semantic changes; every cycle still measures all lanes.
        commentary=(model_commentary(lane,measured,binary,model) if changed and binary and model else
                    dict(status='NOT_RUN' if not changed else 'BLOCKED',authority='UNVERIFIED_MODEL_INFERENCE',
                         reason='No semantic change' if not changed else 'Local runtime unavailable'))
        receipt_path=cycle/(lane+'.json')
        event_path=None
        if changed:
            event_path=Path('automation_intelligence/mcp_interface/events')/f'{run_id}_native_{lane}.json'
            event=dict(schema_version='icarus-mcp-event-v1',event_id=f'{run_id}-native-{lane}',at_utc=stamp(now),category='AUDIT',
                       status=measured['status'],severity='HIGH' if measured['status']=='BLOCKING' else 'MEDIUM',
                       summary=measured['summary'],surface=[f'{lane} native research'],source=SOURCES[lane],
                       paths=[str(evidence_path),str(receipt_path)],evidence=[dict(classification='FACT',measurement=measured,
                       evidence_sha256=digest(dict(market=packets,macro=macro_raw)),code_revision=code_revision)],
                       execution_authorized=False,worker='GITHUB_NATIVE_RESEARCH_V1',interpretation_authority='UNVERIFIED_MODEL_INFERENCE')
            owners={'flow':('argus','nexus'),'macro':('oracle','supermesh_x'),'aion':('aion',),'daedalus':('daedalus','aegis'),'omega':('janus','infrastructure')}
            for owner in owners[lane]:
                event[owner]=dict(status=measured['status'],finding=measured['summary'])
            write_exclusive(root/event_path,event)
        receipt=dict(schema_version='icarus-research-run-v1',run_id=f'{run_id}-{lane}',lane=lane,
                     automation_id='github-native-research-v1',worker='GITHUB_ACTIONS',started_at_utc=stamp(now),
                     completed_at_utc=stamp(time.time()),outcome='BLOCKED' if measured['status'] in ('BLOCKED','BLOCKING') else
                     'MATERIAL_DELTA' if changed else 'NO_MATERIAL_DELTA',substantive_work_performed=bool(
                        measured.get('current') or measured.get('experiments') or measured.get('checks') or measured.get('releases') or measured.get('series') or lane=='omega'),
                     summary=measured['summary'],measurements=measured,local_interpretation=commentary,
                     evidence=[str(evidence_path)],prior_receipt_path=previous.get('lanes',{}).get(lane,{}).get('receipt_path'),
                     event_paths=[str(event_path)] if event_path else [],blockers=measured.get('gaps',measured.get('blockers',[])),
                     input_sha256=digest(dict(market=packets,macro=macro_raw)),code_revision=code_revision,execution_authorized=False,
                     chatgpt_tokens_used=0,paid_model_calls=0)
        write_exclusive(root/receipt_path,receipt)
        lanes[lane]=dict(status=measured['status'],receipt_path=str(receipt_path),event_path=str(event_path) if event_path else None,
                         local_model_status=commentary['status'],substantive_work_performed=receipt['substantive_work_performed'])
    latest=dict(schema_version='icarus-native-research-status-v1',run_id=run_id,at_utc=stamp(now),code_revision=code_revision,
                lanes=lanes,state_hashes=states,execution_authorized=False,chatgpt_tokens_used=0,paid_model_calls=0,
                qualification='BOUNDED_RESEARCH_REPLACEMENT; NOT_FRONTIER_MODEL_EQUIVALENCE')
    previous_path.parent.mkdir(parents=True,exist_ok=True)
    previous_path.write_text(json.dumps(latest,indent=2,sort_keys=True)+'\n')
    return latest


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',type=Path,default=Path('.'))
    ap.add_argument('--run-id',required=True)
    ap.add_argument('--binary',type=Path)
    ap.add_argument('--model',type=Path)
    args=ap.parse_args()
    from tools.native_research_sources import acquire_markets,acquire_macro
    packets,gaps=acquire_markets()
    macro=acquire_macro()
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=args.root,text=True).strip()
    result=run_cycle(args.root,packets,macro,now=time.time(),run_id=args.run_id,code_revision=revision,
                     binary=args.binary,model=args.model,acquisition_gaps=gaps)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    main()
