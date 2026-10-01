/* Read-only MCP / Automation observability panel. No trading or repo mutations. */
let mcpLoading = false, mcpLast = null;

function mcpBadge(value) {
  const s = String(value ?? 'UNKNOWN');
  const u = s.toUpperCase();
  const cls = ['VERIFIED','SUCCESS','RUN_PERSISTED','VALID','AUTHORITATIVE'].includes(u) ? 'b' :
    ['FAILED','ERROR','BLOCKING','MISSING'].includes(u) ? 'r' : 'w';
  return `<span class="chip ${cls}">${esc(s)}</span>`;
}

function mcpWhen(value) {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? esc(value) : esc(d.toLocaleString());
}

function mcpHtml() {
  return `<section class="card c12">
    <h2>MCP / Automation Control Plane <span class="sub">Repository-native provenance bridge</span></h2>
    <p class="small muted">Read-only inside ICARUS. This panel projects durable repair, audit, evolution, run, watchdog and control-plane evidence from the local repository checkout. It does not authorize trading, merge code, or make external calls.</p>
    <div class="toolbar"><button id="mcpRefresh">Refresh evidence</button><span id="mcpStatus" class="small muted">Loading…</span></div>
    <div class="tiles" id="mcpSummary"></div>
  </section>
  <section class="card c12">
    <h2>Authoritative five-lane liveness <span class="sub">OMEGA · Macro · Flow · AION · DAEDALUS</span></h2>
    <div id="mcpV3Meta" class="small muted" style="margin-bottom:8px"></div>
    <div class="scroll"><table>
      <thead><tr><th>Lane</th><th>Schedule</th><th>Health</th><th>Latest slot</th><th>Persistence</th><th>Finalization</th><th>Origin / backend</th><th>Data gaps</th></tr></thead>
      <tbody id="mcpV3Rows"></tbody>
    </table></div>
    <details style="margin-top:10px"><summary>Persistence hardening / cutover evidence</summary><pre id="mcpHardening" class="log" style="max-height:320px"></pre></details>
  </section>
  <section class="card c7">
    <h2>MCP change ledger <span class="sub">Material repairs, audits, evolutions &amp; integrations</span></h2>
    <div id="mcpEvents"></div>
  </section>
  <section class="card c5">
    <h2>Interface contract</h2>
    <div id="mcpContract" class="small"></div>
  </section>
  <section class="card c12">
    <h2>Restored-five evidence <span class="sub">Secondary worker receipts — not the authoritative five-lane v3 plane</span></h2>
    <div class="scroll"><table>
      <thead><tr><th>Lane</th><th>Schedule</th><th>Health</th><th>Slot</th><th>Slot status</th><th>Worker receipt</th><th>Observed worker run</th></tr></thead>
      <tbody id="mcpRestoredRows"></tbody>
    </table></div>
  </section>
  <section class="card c12">
    <h2>Raw provenance snapshot</h2>
    <details><summary>Show exact API payload</summary><pre id="mcpRaw" class="log" style="max-height:520px"></pre></details>
  </section>`;
}

function mcpEventCard(e) {
  const paths = (e.paths || []).map(p => `<div class="small muted"><code>${esc(p)}</code></div>`).join('');
  const evidence = (e.evidence || []).map(p => `<div class="small muted">↳ <code>${esc(p)}</code></div>`).join('');
  return `<div class="tile" style="margin-bottom:8px;overflow-wrap:anywhere">
    <div style="display:flex;gap:7px;align-items:center;flex-wrap:wrap">
      <b>${esc(e.category || 'EVENT')}</b>${mcpBadge(e.status)}${e.severity ? `<span class="chip">${esc(e.severity)}</span>` : ''}
      <span class="small muted" style="margin-left:auto">${mcpWhen(e.at_utc)}</span>
    </div>
    <p style="margin:7px 0 5px">${esc(e.summary || 'No summary')}</p>
    <div class="small"><b>Surface:</b> ${esc(e.surface || '—')} · <b>Source:</b> ${esc(e.source || '—')} · <b>Trading authority:</b> ${e.execution_authorized ? '<span class="neg">true</span>' : '<span class="pos">false</span>'}</div>
    ${e.branch ? `<div class="small muted">Branch <code>${esc(e.branch)}</code>${e.commit ? ` · commit <code>${esc(e.commit)}</code>` : ''}</div>` : ''}
    ${paths}${evidence}
  </div>`;
}

function mcpLaneRow(l) {
  const gaps = (l.data_gaps || []).length ? (l.data_gaps || []).map(g => esc(g)).join(', ') : 'none';
  return `<tr>
    <td><b>${esc(l.title || l.name)}</b><div class="small muted">${esc(l.name)}</div></td>
    <td class="tnum">:${String(l.minute ?? '—').padStart(2,'0')}</td>
    <td>${mcpBadge(l.health)}</td>
    <td class="tnum">${mcpWhen(l.latest_slot_utc)}</td>
    <td>${mcpBadge(l.run_status || '—')}</td>
    <td>${mcpBadge(l.finalization_status || '—')}</td>
    <td><div>${esc(l.run_origin || '—')}</div><div class="small muted">${esc(l.inference_backend || '—')} · model ${esc(l.model || '—')}</div></td>
    <td class="small">${gaps}</td>
  </tr>`;
}

function mcpRestoredRow(l) {
  return `<tr>
    <td><b>${esc(l.title || l.name)}</b><div class="small muted">${esc(l.name)}</div></td>
    <td class="tnum">:${String(l.minute ?? '—').padStart(2,'0')}</td>
    <td>${mcpBadge(l.health)}</td>
    <td class="tnum">${mcpWhen(l.slot_utc)}</td>
    <td>${mcpBadge(l.slot_status || '—')}</td>
    <td>${esc(l.worker_receipt_status || '—')}</td>
    <td><div class="small">${esc(l.observed_worker_run_id || '—')}</div><div class="small muted">${esc(l.observed_worker_run_status || '')}</div></td>
  </tr>`;
}

async function loadMcp() {
  if (mcpLoading || view !== 'mcp') return;
  mcpLoading = true;
  try {
    const r = await fetch('/api/mcp/control?events=100', {cache:'no-store'});
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || data.error || `HTTP ${r.status}`);
    if (view !== 'mcp') return;
    mcpLast = data;
    const s = data.summary || {}, v3 = data.v3 || {}, restored = data.restored_five || {};
    $('#mcpStatus').textContent = `Snapshot ${mcpWhen(data.generated_at_utc)} · ${data.source_note || data.source || ''}`;
    $('#mcpSummary').innerHTML =
      `<div class="tile"><div class="k">V3 lanes verified</div><div class="v">${esc(s.v3_verified ?? 0)} / ${esc(s.v3_lanes ?? 0)}</div></div>` +
      `<div class="tile"><div class="k">Control plane</div><div class="v" style="font-size:13px;overflow-wrap:anywhere">${esc(v3.mode || '—')}</div></div>` +
      `<div class="tile"><div class="k">Inference scope</div><div class="v" style="font-size:13px">${v3.substantive_ai_inference ? 'substantive AI' : 'liveness only'}</div></div>` +
      `<div class="tile"><div class="k">Trading execution</div><div class="v ${data.trading_execution_authorized?'neg':'pos'}">${data.trading_execution_authorized ? 'AUTHORIZED' : 'DISABLED'}</div></div>` +
      `<div class="tile"><div class="k">Material MCP events</div><div class="v">${esc(s.material_events_returned ?? 0)}</div></div>`;
    $('#mcpV3Meta').innerHTML = `Control plane <code>${esc(v3.control_plane_id || 'missing')}</code> · ${mcpBadge(v3.phase || v3.mode || 'unknown')} · scope <code>${esc(v3.authoritative_scope || '—')}</code> · backend <code>${esc(v3.inference_backend || '—')}</code> · zero cost ${esc(v3.zero_cost)}`;
    $('#mcpV3Rows').innerHTML = (v3.lanes || []).map(mcpLaneRow).join('') || '<tr><td colspan="8" class="empty">No v3 lane receipts found in this checkout.</td></tr>';
    $('#mcpHardening').textContent = JSON.stringify({
      verified_branch_ci:v3.verified_branch_ci,
      persistence_hardening:v3.persistence_hardening,
      last_persistence_race_hardening:v3.last_persistence_race_hardening,
      watchdog_revalidation_requested_at_utc:v3.watchdog_revalidation_requested_at_utc,
      control_path:v3.control_path,
      acceptance_path:v3.acceptance_path
    }, null, 2);
    $('#mcpEvents').innerHTML = (data.events || []).map(mcpEventCard).join('') || '<p class="empty">No MCP interface events have been recorded yet.</p>';
    const c = data.contract || {};
    $('#mcpContract').innerHTML = c.present ? `<p>${esc(c.purpose || '')}</p>
      <p><b>Categories:</b> ${esc((c.required_categories || []).join(', '))}</p>
      <p><b>Required fields:</b> ${esc((c.required_fields || []).join(', '))}</p>
      <p><b>Event root:</b><br><code>${esc(c.event_root || '—')}</code></p>
      <p><b>API:</b> <code>${esc(c.ui_api || '—')}</code><br><b>UI:</b> ${esc(c.ui_tab || '—')}</p>
      <p class="muted">Contract file: <code>${esc(c.path || '—')}</code></p>` : '<p class="empty">MCP interface contract missing from this checkout.</p>';
    $('#mcpRestoredRows').innerHTML = (restored.lanes || []).map(mcpRestoredRow).join('') || '<tr><td colspan="7" class="empty">No restored-five receipts found.</td></tr>';
    $('#mcpRaw').textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    if ($('#mcpStatus')) $('#mcpStatus').textContent = 'MCP / Automation evidence unavailable: ' + e.message;
  } finally {
    mcpLoading = false;
  }
}

function wireMcp() {
  $('#mcpRefresh').onclick = loadMcp;
  loadMcp();
}
