/* Local research controls. External/model text is escaped; model calls require an action. */
let researchLoading = false, researchJob = null, researchWorkflow = null;
let researchEvidence = new Set(), researchQualified = false, researchAdaptationLoaded = false;
const researchRoles = ['source-auditor','regime-analyst','risk-auditor','openai-review','anthropic-review'];
function researchHtml(assets) {
  researchAdaptationLoaded = false;
  return `<section class="card c12"><h2>Research &amp; paper adaptation <span class="sub">Evidence → study → independent reviews → paper overlay</span></h2>
    <div id="researchStatus" role="status" class="muted">Loading research workspace…</div>
    <p class="small muted">Candidates must improve on the same frozen baseline, pass held-out and stressed-cost checks, and receive OpenAI advice plus Claude approval. Paper changes require a warm, flat asset without pending orders. Owner presets and input files remain separate.</p></section>
    <section class="card c7"><h2>01 / Asset study</h2>
    <div class="toolbar"><label>Asset <select id="rsAsset">${assets.map(a=>`<option>${esc(a.symbol)}</option>`).join('')}</select></label>
    <label>Trial cap <input id="rsTrials" type="number" min="1" max="1000" value="16"></label>
    <label>Seconds <input id="rsBudget" type="number" min="1" max="86400" value="120"></label></div>
    <p class="muted small">Use disjoint UTC training, validation and final holdout periods. Consumed history cannot become a fresh holdout.</p>
    <label for="rsGrid">Candidate input grid (JSON)</label><textarea id="rsGrid" rows="3" style="width:100%;background:var(--surface-2);color:var(--ink);border:1px solid var(--ring);border-radius:8px;padding:10px">{"conf_min_votes":[4,5,6]}</textarea>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-top:12px">${['train','validation','holdout'].map(n=>`<div><b>${esc(n)}</b><p><label>Start UTC <input type="datetime-local" id="rs_${n}_start" style="width:100%"></label></p><label>End UTC <input type="datetime-local" id="rs_${n}_end" style="width:100%"></label></div>`).join('')}</div>
    <p><button class="primary" id="rsRun">Run bounded study</button> <button id="rsCancel">Cancel study</button></p>
    <div class="toolbar"><label>Saved study <select id="rsStudy"><option value="">Choose a study</option></select></label><label>Study ID <input id="rsStudyId" type="text" placeholder="Saved study ID"></label><button id="rsLoadStudy">Load study</button></div>
    <pre id="researchJob" class="log" style="max-height:290px">No study selected.</pre></section>
    <section class="card c5"><h2>02 / Current evidence <span id="rsEvidenceCount" class="sub">0 selected</span></h2>
    <p class="small muted">Select the source records the reviewers should assess. Unknown publication time is shown explicitly; first receipt controls availability.</p>
    <div id="researchEvents" class="scroll" style="max-height:540px;overflow-wrap:anywhere">No evidence loaded. Collect public sources in Financial &amp; data.</div></section>
    <section class="card c7"><h2>03 / Five-stage analysis <span class="sub">Explicit provider requests</span></h2>
    <p class="small muted">Three separate OpenAI specialists assess sources, regime and risk. An OpenAI candidate review follows; Claude makes the final approval decision. Calls use configured providers and the daily budget below.</p>
    <label for="rsRationale">Research rationale</label><textarea id="rsRationale" rows="3" maxlength="8000" placeholder="Explain the hypothesis and the source evidence to assess." style="width:100%;background:var(--surface-2);color:var(--ink);border:1px solid var(--ring);border-radius:8px;padding:10px"></textarea>
    <p><label><input type="checkbox" id="rsApply"> Apply to the paper engine if all research, review and runtime gates pass</label></p>
    <p><button class="primary" id="rsAnalyse" disabled>Run five-stage analysis</button> <button id="rsAnalysisCancel">Cancel analysis</button></p>
    <div id="rsQualification" class="small muted">Select a qualified study and current evidence.</div>
    <div id="rsBudgetStatus" class="tiles"></div><p class="small muted" id="rsBudgetUnit"></p>
    <label>Workflow <select id="rsWorkflow"><option value="">Choose a workflow</option></select></label>
    <div id="rsStages" class="tiles"></div><pre id="rsWorkflowStatus" class="log" style="max-height:240px">No workflow selected.</pre></section>
    <section class="card c5"><h2>04 / Versioned paper configuration</h2>
    <div id="researchProposals" class="scroll" style="max-height:300px">No candidates loaded.</div>
    <div id="rsActive" class="small" style="overflow-wrap:anywhere"></div>
    <p><button id="rsRollback">Roll back selected asset</button> <button id="rsRecover">Recover interrupted change</button></p>
    <pre id="rsOperation" class="log" style="max-height:220px">No configuration operation requested.</pre></section>
    <section class="card c12"><h2>Automatic per-asset adaptation <span class="sub">Bounded, opt-in scheduler</span></h2>
    <p class="small muted">Enabling the scheduler permits repeated research and configured model calls within the displayed limits. Fresh source evidence is required before research starts. Every application still requires the full approval chain. Edit the configuration to set assets, cadence, fresh windows and input grids.</p>
    <div id="rsAdaptationStatus" class="small muted">Loading adaptation status…</div>
    <details class="group"><summary>Configuration</summary><div style="padding:12px"><textarea id="rsAdaptationConfig" rows="12" spellcheck="false" style="width:100%;background:var(--surface-2);color:var(--ink);border:1px solid var(--ring);padding:10px" placeholder="Configuration unavailable"></textarea>
    <p><button id="rsSaveAdaptation" disabled>Save configuration</button> <button id="rsEnableAdaptation" disabled>Enable scheduler</button> <button id="rsDisableAdaptation" disabled>Disable scheduler</button></p></div></details></section>`;
}
async function researchGet(path) {
  const response = await fetch(path, {headers:{Authorization:'Bearer '+(localStorage.getItem(tokKey)||'')}, cache:'no-store'});
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
  return body;
}
function researchId() { return 'ui_'+(globalThis.crypto?.randomUUID?.() || Date.now().toString(36)+'_'+Math.random().toString(36).slice(2)); }
function researchOptions(selector, rows, selected, label) {
  const element=$(selector); if(!element) return;
  const html='<option value="">Choose…</option>'+rows.map(row=>`<option value="${esc(row.id)}">${esc(label(row))}</option>`).join('');
  if(element.dataset.options!==html) {element.innerHTML=html;element.dataset.options=html;}
  element.value=selected||'';
}
function researchUpdateGate() {
  const run=$('#rsAnalyse'); if(!run) return;
  run.disabled=!researchQualified || researchEvidence.size===0;
  $('#rsEvidenceCount').textContent=`${researchEvidence.size} selected`;
  $('#rsQualification').textContent=researchQualified ? 'Study qualified. Select evidence and provide a rationale to request the reviews.' : 'A completed, qualified study for the selected asset is required.';
}
function researchStages(workflow) {
  const stages=workflow?.stages||[];
  return researchRoles.map(role=>{const stage=stages.find(s=>s.stage===role);return `<div class="tile"><div class="k">${esc(role)}</div><div class="v" style="font-size:14px">${esc(stage?.status||'waiting')}</div><div class="small muted">${esc(stage?.model||'')}</div>${stage?.result?.decision?`<p>${esc(stage.result.decision)}</p>`:''}${stage?.error?`<p class="neg">${esc(stage.error)}</p>`:''}</div>`;}).join('');
}
async function loadResearch() {
  if (researchLoading || view!=='research') return;
  researchLoading=true;
  try {
    const data=await researchGet('/api/research');
    if(view!=='research') return;
    const caps=data.capabilities||{},ledger=data.ledger||{},analysis=data.analysis||{};
    $('#researchStatus').textContent=`${data.mode||'Research'} · ${(data.assets||[]).length} assets · OpenAI ${ledger.providers?.openai?.configured?'configured':'not configured'} · Claude ${ledger.providers?.anthropic?.configured?'configured':'not configured'} · licensed futures ticks ${caps.licensed_tick_feed_connected?'connected':'not connected'}`;
    const asset=$('#rsAsset').value;
    const jobs=(data.jobs||[]).filter(j=>j.asset===asset);
    if(!researchJob&&jobs.length) researchJob=jobs[jobs.length-1].id;
    researchOptions('#rsStudy',jobs,researchJob,j=>`${j.id} · ${j.status}`);
    if(researchJob) {
      const job=await researchGet('/api/research/jobs/'+encodeURIComponent(researchJob));
      if(view!=='research'||$('#rsAsset').value!==asset) return;
      const r=job.result;
      researchQualified=job.asset===asset&&job.status==='complete'&&r?.research_qualified===true;
      $('#researchJob').textContent=JSON.stringify({study:job.id,asset:job.asset,status:job.status,error:job.error,
        completed_trials:r?.trials?.length||0,selected:r?.selected,holdout:r?.holdout,
        research_qualified:r?.research_qualified},null,2);
    } else {researchQualified=false;$('#researchJob').textContent='No study selected.';}
    const evidence=await researchGet('/api/research/events?asset='+encodeURIComponent(asset));
    if(view!=='research'||$('#rsAsset').value!==asset) return;
    const available=new Set((evidence.events||[]).map(e=>e.event_id));
    researchEvidence=new Set([...researchEvidence].filter(id=>available.has(id)));
    $('#researchEvents').innerHTML=(evidence.events||[]).map(e=>`<label class="tile" style="display:block;margin-bottom:8px"><input type="checkbox" data-evidence="${esc(e.event_id)}" ${researchEvidence.has(e.event_id)?'checked':''}> <b>${esc(e.source)} · ${esc(e.event_type)}</b><br><span class="small">${esc(e.instrument_id)}<br>Observed ${esc(e.observed_at)}<br>Published ${e.published_at?esc(e.published_at):'unknown (first observed)'}<br>Received ${esc(e.received_at)}<br>${esc(JSON.stringify(e.values||{}))}</span></label>`).join('')||'<p class="empty">No current evidence. Collect public sources in Financial &amp; data.</p>';
    $('#researchEvents').querySelectorAll('[data-evidence]').forEach(el=>el.onchange=()=>{el.checked?researchEvidence.add(el.dataset.evidence):researchEvidence.delete(el.dataset.evidence);researchUpdateGate();});
    researchUpdateGate();
    $('#researchProposals').innerHTML=(ledger.proposals||[]).filter(p=>p.candidate?.asset===asset).map(p=>`<div class="tile" style="margin-bottom:8px"><b>${esc(p.candidate.asset)}</b> <span class="chip">${esc(p.state)}</span><p class="small" style="overflow-wrap:anywhere">${esc(p.proposal_id)}</p><button class="sm" data-activate="${esc(p.proposal_id)}" ${p.state==='approved'?'':'disabled'}>Apply approved paper version</button></div>`).join('')||'<p class="empty">No candidates for this asset.</p>';
    $('#researchProposals').querySelectorAll('[data-activate]').forEach(button=>button.onclick=()=>researchOperation(button,'activate',{proposal_id:button.dataset.activate,operation_id:researchId()}));
    const active=(data.activation?.active||[]).find(a=>a.asset===asset);
    $('#rsActive').textContent=active?`Active ${asset} version: ${active.version_id}`:`${asset}: owner configuration; no active research overlay.`;
    $('#rsRollback').disabled=!active;
    $('#rsCancel').disabled=!jobs.some(j=>j.id===researchJob&&j.status==='running');
    const budget=analysis.budget||{};
    $('#rsBudgetStatus').innerHTML=`<div class="tile"><div class="k">Reserved calls today</div><div class="v">${esc(analysis.reserved_calls??0)} / ${esc(budget.max_daily_calls??'—')}</div></div><div class="tile"><div class="k">Reserved token bound</div><div class="v">${esc(analysis.reserved_tokens??0)} / ${esc(budget.max_daily_reserved_tokens??'—')}</div></div>`;
    $('#rsBudgetUnit').textContent=analysis.budget_unit||'';
    if(!researchWorkflow&&analysis.jobs?.length) researchWorkflow=analysis.jobs[0].id;
    researchOptions('#rsWorkflow',analysis.jobs||[],researchWorkflow,j=>`${j.id.slice(0,12)} · ${j.status}`);
    if(researchWorkflow) {
      const workflow=await researchGet('/api/research/analysis/'+encodeURIComponent(researchWorkflow));
      if(view!=='research') return;
      $('#rsStages').innerHTML=researchStages(workflow);
      $('#rsWorkflowStatus').textContent=JSON.stringify({workflow:workflow.id,status:workflow.status,error:workflow.error,
        cancelled:!!workflow.cancelled,proposal:workflow.result?.proposal_id,applied:workflow.result?.applied,
        activation:workflow.result?.activation,stages:(workflow.stages||[]).map(s=>({role:s.stage,status:s.status,decision:s.result?.decision,rationale:s.result?.rationale,error:s.error}))},null,2);
      $('#rsAnalysisCancel').disabled=!['running','queued'].includes(workflow.status);
    } else {$('#rsStages').innerHTML=researchStages(null);$('#rsAnalysisCancel').disabled=true;}
    await loadResearchAdaptation();
  } catch(e) {const el=$('#researchStatus');if(el) el.textContent='Research unavailable: '+e.message;}
  finally {researchLoading=false;}
}
async function loadResearchAdaptation() {
  try {
    const status=await researchGet('/api/research/adaptation');
    if(view!=='research') return;
    $('#rsAdaptationStatus').textContent=JSON.stringify(status,null,2);
    if(!researchAdaptationLoaded) {
      $('#rsAdaptationConfig').value=JSON.stringify(status.config||status.configuration||{},null,2);
      researchAdaptationLoaded=true;
      ['rsSaveAdaptation','rsEnableAdaptation','rsDisableAdaptation'].forEach(id=>$('#'+id).disabled=false);
    }
  } catch(e) {const el=$('#rsAdaptationStatus');if(el) el.textContent='Automatic adaptation unavailable: '+e.message;}
}
async function researchOperation(button,action,body) {
  button.disabled=true;
  try {
    const result=await admin('/admin/research/'+action,body);
    if(result&&$('#rsOperation')) $('#rsOperation').textContent=JSON.stringify(result,null,2);
    await loadResearch();
  } catch(e) {toast(e.message,true);} finally {if(button.isConnected) button.disabled=false;}
}
function wireResearch() {
  $('#rsAsset').onchange=()=>{researchJob=null;researchEvidence.clear();researchQualified=false;researchUpdateGate();loadResearch();};
  $('#rsStudy').onchange=()=>{researchJob=$('#rsStudy').value||null;researchQualified=false;researchUpdateGate();loadResearch();};
  $('#rsLoadStudy').onclick=()=>{researchJob=$('#rsStudyId').value.trim()||null;researchQualified=false;researchUpdateGate();loadResearch();};
  $('#rsWorkflow').onchange=()=>{researchWorkflow=$('#rsWorkflow').value||null;loadResearch();};
  $('#rsRun').onclick=async()=>{
    const button=$('#rsRun');button.disabled=true;
    try {
      const windows={};
      for(const name of ['train','validation','holdout']) for(const edge of ['start','end']) {
        const text=$(`#rs_${name}_${edge}`).value;
        if(!text) throw new Error('Complete all six UTC date fields.');
        const timestamp=Date.parse(text+'Z')/1000;
        if(!Number.isInteger(timestamp)) throw new Error('Invalid UTC date.');
        windows[name+'_'+edge]=timestamp;
      }
      const answer=await admin('/admin/research/studies',{asset:$('#rsAsset').value,grid:JSON.parse($('#rsGrid').value),windows,
        policy:{max_trials:Number($('#rsTrials').value),max_seconds:Number($('#rsBudget').value)}});
      if(answer) {researchJob=answer.job;await loadResearch();}
    } catch(e) {toast(e.message,true);} finally {button.disabled=false;}
  };
  $('#rsCancel').onclick=async()=>{if(researchJob) {await admin('/admin/research/cancel',{job:researchJob});await loadResearch();}};
  $('#rsAnalyse').onclick=async()=>{
    const button=$('#rsAnalyse');button.disabled=true;
    try {
      const rationale=$('#rsRationale').value.trim();
      if(!rationale) throw new Error('Provide a research rationale.');
      const answer=await admin('/admin/research/analysis',{job:researchJob,evidence_ids:[...researchEvidence],rationale,apply:$('#rsApply').checked});
      if(answer) {researchWorkflow=answer.id;await loadResearch();}
    } catch(e) {toast(e.message,true);} finally {researchUpdateGate();}
  };
  $('#rsAnalysisCancel').onclick=async()=>{if(researchWorkflow) {await admin('/admin/research/analysis/cancel',{id:researchWorkflow});await loadResearch();}};
  $('#rsRollback').onclick=()=>researchOperation($('#rsRollback'),'rollback',{asset:$('#rsAsset').value,operation_id:researchId()});
  $('#rsRecover').onclick=()=>researchOperation($('#rsRecover'),'recover',{asset:$('#rsAsset').value});
  const configure=async(config)=>{
    try {const result=await admin('/admin/research/adaptation',config);if(result) {researchAdaptationLoaded=false;await loadResearchAdaptation();}}
    catch(e) {toast(e.message,true);}
  };
  $('#rsSaveAdaptation').onclick=()=>{try {configure(JSON.parse($('#rsAdaptationConfig').value));}catch(e){toast(e.message,true);}};
  $('#rsEnableAdaptation').onclick=()=>configure({enabled:true});
  $('#rsDisableAdaptation').onclick=()=>configure({enabled:false});
  loadResearch();
}
