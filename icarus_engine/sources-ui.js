/* Public-source observations. Collection only runs after a button click. */
let sourcesLoading = false, sourceWatchLoaded = false, sourcesLatest = {};
const sourceNames = {cftc:'CFTC commitments of traders',bls:'BLS CPI',
  'federal-reserve':'Federal Reserve releases',bea:'BEA releases',sec:'SEC company filings',coinbase:'Coinbase BTC-USD trades',
  'yahoo-dxy':'DXY / asset return correlations'};
function sourcesHtml(assets) {
  sourceWatchLoaded=false;
  const options=assets.map(a=>`<option value="${esc(a.symbol)}">${esc(a.symbol)}</option>`).join('');
  return `<section class="card c12"><h2>Financial &amp; data <span class="sub">Source-backed public observations</span></h2>
    <p class="small muted">Collect on demand or enable bounded background refresh below. CFTC positions, macro releases, company filings and spot BTC trades are research evidence; they do not place orders or supply a licensed futures tick feed.</p>
    <div id="sourcesStatus" role="status" class="small muted">Loading saved source status…</div></section>
    <section class="card c7"><h2>Public collection</h2><div id="sourcesCards" class="tiles" style="grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr));overflow-wrap:anywhere"></div>
    <div class="toolbar"><label>Map SEC facts to asset <select id="sourceAsset"><option value="">No mapping</option>${options}</select></label>
    <label>SEC CIK <input id="sourceCik" inputmode="numeric" maxlength="10" placeholder="Numeric CIK"></label>
    <label>BTC seconds <input id="sourceSeconds" type="number" min="1" max="3600" value="1"></label></div>
    <p class="small muted">SEC needs the server's real contact identity. Map a company only when it is relevant to that asset; a filing is not the asset's own market data. Coinbase seconds must stay fixed for an existing stream.</p>
    <pre id="sourceCollectResult" class="log" style="max-height:170px">No collection requested.</pre></section>
    <section class="card c5"><h2>Saved observations</h2><div class="toolbar"><label>Kind <select id="sourceKind"><option value="asset">COT &amp; macro</option><option value="companies">Companies</option><option value="trades">BTC trades</option></select></label>
    <label>Asset <select id="sourceFilterAsset"><option value="">All</option>${options}</select></label><button id="sourceRefresh">Refresh records</button></div>
    <div id="sourceRecords" class="scroll" style="max-height:610px;overflow-wrap:anywhere">Loading saved records…</div></section>
    <section class="card c12"><h2>BTC-USD seconds &amp; footprint</h2><div id="sourceStream" class="scroll" style="max-height:380px;overflow-wrap:anywhere">No trade stream loaded.</div></section>
    <section class="card c12"><h2>Background source refresh</h2><p class="small muted">Public requests only. Configure each source's cadence and options, including an exact CIK for SEC. Missing credentials or sequence gaps remain visible. Model analysis has separate Research controls.</p>
    <pre id="sourceWatchStatus" class="log" style="max-height:180px">Loading…</pre><details><summary>Collection schedule</summary><textarea id="sourceWatchConfig" rows="14" style="width:100%;background:var(--surface-2);color:var(--ink)"></textarea>
    <p><button id="sourceWatchSave" disabled>Save schedule</button> <button id="sourceWatchEnable" disabled>Enable refresh</button> <button id="sourceWatchDisable" disabled>Disable refresh</button></p></details></section>`;
}
function sourceLink(url,label) {
  try {const parsed=new URL(url);if(parsed.protocol==='https:')
    return `<a href="${esc(parsed.href)}" target="_blank" rel="noopener noreferrer">${esc(label||parsed.hostname)}</a>`;}
  catch (_) {} return esc(label||'Source URL unavailable');
}
function sourceTime(value) {return value?esc(value):'unknown';}
function sourceQuantity(value) {return Number.isFinite(value)?value.toLocaleString('en-US',{maximumFractionDigits:8}):'unknown';}
function sourceRecord(r) {
  const title=r.kind==='company'?(r.data?.name||r.instrument_id):r.kind==='cot'?`${r.asset_ids?.join(', ')||'CFTC'} · ${r.report_family||'COT'}`:
    r.kind==='news'?(r.data?.title||r.source):`${r.source} · ${r.report_family||r.instrument_id}`;
  const details=r.kind==='correlation'?`<p class="small">${esc(r.data?.asset_vendor_ticker)} / DX-Y.NYB · ${esc(r.data?.pairs)} aligned return pairs · ${esc(r.data?.direction)} association. ${esc(r.data?.reason||'')}</p><p class="small muted">Hourly vendor history; gaps are not filled. Correlation does not establish predictive lead. ${esc((r.data?.caveats||[]).join(' '))}</p>`:
    r.kind==='company'&&r.data?.filings?`<p class="small">Recent filings: ${r.data.filings.slice(0,5).map(f=>`${esc(f.form||'filing')} ${esc(f.filingDate||'')}`).join(' · ')}</p>`:'';
  return `<div class="tile" style="margin-bottom:8px"><b>${esc(title)}</b> <span class="chip">${esc(r.source)}</span>
    <div class="small muted">${sourceLink(r.source_url,'Official record')} · ${esc(r.instrument_id)} · ${esc((r.asset_ids||[]).join(', ')||'no asset mapping')}</div>
    <div class="small">Observed ${sourceTime(r.observed_at)} · Published ${r.published_at?sourceTime(r.published_at):'unknown'} · First receipt ${sourceTime(r.available_at)}</div>
    <div class="small muted">Timing ${esc(r.timing_basis||'unknown')} · ${esc((r.quality_flags||[]).join(', ')||'no quality flags')} · revision ${esc((r.revision_id||'').slice(0,12))}</div>
    ${r.values&&Object.keys(r.values).length?`<p class="small">${Object.entries(r.values).map(([k,v])=>`${esc(k)} ${esc(v)} ${esc(r.units?.[k]||'')}`).join(' · ')}</p>`:''}${details}</div>`;
}
function sourceFootprint(bar) {
  const levels=Object.entries(bar.footprint||{}).sort((a,b)=>Number(b[0])-Number(a[0])).slice(0,40);
  return `<div class="tile" style="margin-bottom:8px"><b>${bar.active?'Active partial bucket':'Completed second bar'}</b>
    <div class="small">${esc(new Date(bar.start_ns/1e6).toISOString())} · O/H/L/C ${[bar.open_ticks,bar.high_ticks,bar.low_ticks,bar.close_ticks].map(v=>esc(v==null?'—':(v/100).toFixed(2))).join(' / ')} · ${esc(bar.trades||0)} trades · volume ${esc(sourceQuantity(bar.volume||0))}</div>
    <div class="small muted">Available ${bar.available_at_ns?esc(new Date(bar.available_at_ns/1e6).toISOString()):'only after completion'} · Aggressor ${bar.aggressor_complete===false?'partly unknown':'recorded'}</div>
    ${levels.length?`<div class="scroll"><table><thead><tr><th>Price</th><th>Buy</th><th>Sell</th><th>Unknown</th></tr></thead><tbody>${levels.map(([price,v])=>`<tr><td>${esc((Number(price)/100).toFixed(2))}</td><td>${esc(sourceQuantity(v.buy||0))}</td><td>${esc(sourceQuantity(v.sell||0))}</td><td>${esc(sourceQuantity(v.unknown||0))}</td></tr>`).join('')}</tbody></table></div>`:''}</div>`;
}
async function loadSources() {
  if(sourcesLoading||view!=='sources') return;
  sourcesLoading=true;
  try {
    const status=await researchGet('/api/research/sources');
    if(view!=='sources') return;
    sourcesLatest=status.sources||{};
    $('#sourcesStatus').textContent=`SEC contact identity ${status.sec_identity_configured?'configured':'not configured'} · ${status.note||''}`;
    $('#sourcesCards').innerHTML=Object.entries(sourceNames).map(([source,name])=>{
      const s=status.sources?.[source]||{};
      return `<div class="tile"><b>${esc(name)}</b><div class="small muted">${esc(s.status||'not_collected')} · ${s.last_success_at?`last success ${esc(s.last_success_at)}`:'no successful collection'}</div>
        ${s.error?`<div class="small neg">${esc(s.error)}</div>`:''}<button class="sm" data-collect="${esc(source)}">Collect ${esc(source)}</button></div>`;
    }).join('');
    $('#sourcesCards').querySelectorAll('[data-collect]').forEach(button=>button.onclick=()=>collectSource(button));
    await loadSourceRecords();
    await loadSourceWatch();
  } catch(e) {if($('#sourcesStatus')) $('#sourcesStatus').textContent='Financial data unavailable: '+e.message;}
  finally {sourcesLoading=false;}
}
async function loadSourceRecords() {
  if(view!=='sources') return;
  const kind=$('#sourceKind').value,asset=$('#sourceFilterAsset').value,cik=$('#sourceCik').value.trim();
  const query=new URLSearchParams({kind,limit:'100'});
  if(asset&&kind!=='trades') query.set('asset',asset);
  if(kind==='companies'&&cik) query.set('cik',cik);
  try {
    const data=await researchGet('/api/research/records?'+query);
    if(view!=='sources'||$('#sourceKind').value!==kind) return;
    const rows=kind==='asset'?(data.records||[]).filter(r=>r.kind!=='company'):(data.records||[]);
    $('#sourceRecords').innerHTML=rows.map(r=>kind==='trades'?`<div class="tile" style="margin-bottom:6px">Trade ${esc(r.event?.sequence)} · ${esc(r.trade?.time)} · ${esc(r.trade?.price)} · ${esc(r.trade?.size)} · aggressor ${esc(r.event?.aggressor||'unknown')} · ${sourceLink(r.source_url,'Coinbase receipt')}</div>`:sourceRecord(r)).join('')||'<p class="empty">No saved records match this filter.</p>';
    if(kind==='trades') {
      const stream=data.stream;
      $('#sourceStream').innerHTML=stream?`<p class="small">${esc(stream.instrument)} · ${esc(stream.seconds)}s buckets · ${stream.sequence_continuity_checked===true?'saved batches checked for continuity':'continuity unknown'} · latest collection ${esc(sourcesLatest.coinbase?.status||'unknown')} · ${esc(sourcesLatest.coinbase?.error||'')} · active bucket ${stream.active_bucket_is_partial?'partial':'none'} · last receipt ${stream.last_success_received_ns?esc(new Date(stream.last_success_received_ns/1e6).toISOString()):'unknown'}</p>
        ${(stream.completed_bars||[]).slice(-10).reverse().map(sourceFootprint).join('')}${stream.active_bucket?sourceFootprint({...stream.active_bucket,active:true}):''}`:'<p class="empty">No Coinbase trade stream collected.</p>';
    } else $('#sourceStream').textContent='Select BTC trades to inspect completed seconds and the partial active bucket.';
  } catch(e) {if($('#sourceRecords')) $('#sourceRecords').textContent='Records unavailable: '+e.message;}
}
async function collectSource(button) {
  const source=button.dataset.collect,options={};
  try {
    if(source==='sec') {
      const cik=$('#sourceCik').value.trim();if(!/^[0-9]{1,10}$/.test(cik)||Number(cik)===0) throw new Error('Enter a numeric SEC CIK.');
      options.cik=cik;if($('#sourceAsset').value) options.assets=[$('#sourceAsset').value];
    } else if(source==='coinbase') {
      const seconds=Number($('#sourceSeconds').value);if(!Number.isInteger(seconds)||seconds<1||seconds>3600) throw new Error('BTC seconds must be 1 to 3600.');
      options.seconds=seconds;
    } else if(source==='cftc'&&$('#sourceAsset').value) {
      if($('#sourceAsset').value==='BTC') throw new Error('CFTC has a mapped BTCF futures contract, not spot BTC.');
      options.assets=[$('#sourceAsset').value];
    }
    else if(['bls','federal-reserve','bea','yahoo-dxy'].includes(source)&&$('#sourceAsset').value) options.assets=[$('#sourceAsset').value];
    button.disabled=true;
    const result=await admin('/admin/research/collect',{source,options});
    if(result&&view==='sources'&&$('#sourceCollectResult')) {$('#sourceCollectResult').textContent=JSON.stringify(result,null,2);await loadSources();}
  } catch(e) {toast(e.message,true);} finally {if(button.isConnected) button.disabled=false;}
}
function wireSources() {
  $('#sourceKind').onchange=loadSourceRecords;
  $('#sourceFilterAsset').onchange=loadSourceRecords;
  $('#sourceRefresh').onclick=loadSources;
  const configure=async(partial)=>{
    try {const result=await admin('/admin/research/source-watch',partial);if(result&&view==='sources'){sourceWatchLoaded=false;await loadSourceWatch();}}
    catch(e){toast(e.message,true);}
  };
  $('#sourceWatchSave').onclick=()=>{try{configure(JSON.parse($('#sourceWatchConfig').value));}catch(e){toast(e.message,true);}};
  $('#sourceWatchEnable').onclick=()=>configure({enabled:true});
  $('#sourceWatchDisable').onclick=()=>configure({enabled:false});
  loadSources();
}

async function loadSourceWatch() {
  try {
    const status=await researchGet('/api/research/source-watch');
    if(view!=='sources') return;
    $('#sourceWatchStatus').textContent=JSON.stringify({running:status.running,enabled:status.config.enabled,collections:status.collections},null,2);
    if(!sourceWatchLoaded){
      $('#sourceWatchConfig').value=JSON.stringify(status.config,null,2);sourceWatchLoaded=true;
      ['sourceWatchSave','sourceWatchEnable','sourceWatchDisable'].forEach(id=>$('#'+id).disabled=false);
    }
  } catch(e){if($('#sourceWatchStatus')) $('#sourceWatchStatus').textContent='Source refresh unavailable: '+e.message;}
}
