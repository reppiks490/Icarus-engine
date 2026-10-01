"use strict";
(() => {
  const jobs = Object.create(null);
  const key = (asset, kind) => asset + ":" + kind;
  const getAsset = () => {
    try {
      if (typeof view === "string" && view.startsWith("asset:")) return view.slice(6);
      const q = new URLSearchParams(location.search).get("asset");
      return q ? q.toUpperCase() : null;
    } catch (_) { return null; }
  };
  const getAssetData = (asset) => {
    try { return (last?.assets || []).find(a => a.symbol === asset) || null; }
    catch (_) { return null; }
  };
  const nfmt = v => (v == null || Number.isNaN(Number(v))) ? "—" : Number(v).toLocaleString(undefined,{maximumFractionDigits:2});
  const pct = v => v == null ? "—" : (Number(v) * 100).toFixed(1) + "%";
  const money = v => v == null ? "—" : (Number(v) >= 0 ? "+" : "") + Number(v).toLocaleString(undefined,{maximumFractionDigits:2});

  function cacheHtml(a) {
    const c=a?.persistent_bar_cache;
    if (!c || !(c.series||[]).length) return '<div class="small muted">Persistent bar cache: empty / not initialized.</div>';
    const rows=(c.series||[]).map(x => `<tr><td>${x.sub_minutes}m</td><td>${Number(x.bars||0).toLocaleString()}</td><td>${x.first_ts?dtm(x.first_ts):'—'}</td><td>${x.last_ts?dtm(x.last_ts):'—'}</td></tr>`).join("");
    return `<details class="group"><summary>Persistent warm-up bar cache <span class="cnt">${(c.series||[]).reduce((s,x)=>s+(x.bars||0),0).toLocaleString()}</span></summary><div class="scroll"><table><thead><tr><th>Granularity</th><th>Bars</th><th>First</th><th>Last</th></tr></thead><tbody>${rows}</tbody></table></div><div class="small muted">Market observations only; no strategy, order, position or execution state is stored.</div></details>`;
  }

  function breakdownHtml(a) {
    const b = a?.trade_breakdown;
    if (!b) return "";
    const dir = b.direction || {}, hold = b.holding_bars || {}, hrs = b.entry_hour_ct || {}, exits=b.exit_reason||{};
    const dirRows = ["long","short"].map(k => {
      const x = dir[k] || {};
      return `<tr><td>${k.toUpperCase()}</td><td>${x.n ?? 0}</td><td>${pct(x.win_rate)}</td><td>${money(x.net)}</td><td>${nfmt(x.profit_factor)}</td></tr>`;
    }).join("");
    const holdRows = Object.entries(hold).map(([k,x]) =>
      `<tr><td>${esc(k)}</td><td>${x.n ?? 0}</td><td>${pct(x.win_rate)}</td><td>${money(x.net)}</td><td>${nfmt(x.mean)}</td></tr>`).join("");
    const hourRows = Object.entries(hrs).filter(([,x]) => (x?.n || 0) > 0).map(([k,x]) =>
      `<tr><td>${esc(k)} CT</td><td>${x.n}</td><td>${pct(x.win_rate)}</td><td>${money(x.net)}</td><td>${nfmt(x.profit_factor)}</td></tr>`).join("");
    return `
      <details class="group" open><summary>Trade segmentation <span class="cnt">${b.overall?.n ?? 0}</span></summary>
        <div class="scroll"><table><thead><tr><th>Direction</th><th>Pieces</th><th>Win rate</th><th>Net P&L</th><th>Profit factor</th></tr></thead><tbody>${dirRows}</tbody></table></div>
      </details>
      <details class="group"><summary>Holding-duration segmentation</summary>
        <div class="scroll"><table><thead><tr><th>Bars</th><th>Pieces</th><th>Win rate</th><th>Net P&L</th><th>Mean P&L</th></tr></thead><tbody>${holdRows}</tbody></table></div>
      </details>
      <details class="group"><summary>Entry-hour segmentation · Chicago time</summary>
        <div class="scroll"><table><thead><tr><th>Hour</th><th>Pieces</th><th>Win rate</th><th>Net P&L</th><th>Profit factor</th></tr></thead><tbody>${hourRows || '<tr><td colspan="5" class="muted">no closed trades yet</td></tr>'}</tbody></table></div>
      </details>
      <details class="group"><summary>Exit-signal segmentation</summary>
        <div class="scroll"><table><thead><tr><th>Exit</th><th>Pieces</th><th>Win rate</th><th>Net P&L</th><th>Mean P&L</th><th>Avg run-up</th><th>Avg drawdown</th></tr></thead><tbody>${Object.entries(exits).map(([k,x])=>`<tr><td>${esc(k)}</td><td>${x.n??0}</td><td>${pct(x.win_rate)}</td><td>${money(x.net)}</td><td>${money(x.mean)}</td><td>${money(x.avg_runup)}</td><td>${money(x.avg_drawdown)}</td></tr>`).join('') || '<tr><td colspan="7" class="muted">no closed trades yet</td></tr>'}</tbody></table></div>
      </details>`;
  }

  function shadowDetailHtml(a) {
    let out="";
    const cf=a?.counterfactuals, es=a?.execution_stress, ph=a?.provider_health, re=a?.replay_equivalence;
    if (cf) {
      const rows=Object.entries(cf.horizons||{}).map(([h,x]) =>
        `<tr><td>${esc(h)} bars</td><td>${x.n??0}</td><td>${x.mean_directional_return==null?'—':(Number(x.mean_directional_return)*100).toFixed(3)+'%'}</td><td>${x.positive_rate==null?'—':(Number(x.positive_rate)*100).toFixed(1)+'%'}</td></tr>`).join("");
      out += `<details class="group"><summary>Blocked-signal counterfactuals <span class="cnt">${cf.completed??0} completed · ${cf.pending??0} pending</span></summary><div class="scroll"><table><thead><tr><th>Horizon</th><th>N</th><th>Mean directional return</th><th>Positive</th></tr></thead><tbody>${rows||'<tr><td colspan="4" class="muted">No completed counterfactuals yet</td></tr>'}</tbody></table></div></details>`;
    }
    if (es?.scenarios?.length) {
      const rows=es.scenarios.map(x=>`<tr><td>${x.extra_slippage_ticks}t</td><td>${money(x.extra_commission_per_contract)}</td><td>${money(x.netprofit)}</td><td>${money(x.delta)}</td></tr>`).join("");
      out += `<details class="group"><summary>Execution cost stress <span class="cnt">${es.trades??0} closed pieces</span></summary><div class="scroll"><table><thead><tr><th>Extra slip</th><th>Extra fee / contract / side</th><th>Stressed net</th><th>Δ vs observed</th></tr></thead><tbody>${rows}</tbody></table></div><div class="small muted">Closed-trade repricing only; this does not change emulator fills or order behavior.</div></details>`;
    }
    if (ph) {
      const rows=Object.entries(ph.providers||{}).map(([name,x])=>`<tr><td>${esc(name)}</td><td>${x.ok??0}</td><td>${x.fail??0}</td><td>${x.last_ok?new Date(x.last_ok*1000).toLocaleString():'—'}</td><td>${esc(x.last_error||'—')}</td></tr>`).join("");
      out += `<details class="group"><summary>Provider health · ${esc(ph.status||'UNKNOWN')}</summary><div class="scroll"><table><thead><tr><th>Provider</th><th>OK</th><th>Fail</th><th>Last OK</th><th>Last error</th></tr></thead><tbody>${rows}</tbody></table></div><div class="small muted">${ph.failover_configured?'Configured secondary is shown above.':'No secondary provider is configured for this feed.'}</div></details>`;
    }
    if (re?.last_divergence) {
      out += `<details class="group" open><summary>Replay equivalence divergence</summary><div class="small neg">At ${esc(re.last_divergence.ts)} · expected ${esc((re.last_divergence.expected||'').slice(0,16))} · observed ${esc((re.last_divergence.observed||'').slice(0,16))}</div><div class="small muted">Evidence only. Executable strategy/order state is never restored from this ledger.</div></details>`;
    }
    return out;
  }

  function jobHtml(asset) {
    const d = jobs[key(asset,"determinism")], r = jobs[key(asset,"robustness")],
          rb = jobs[key(asset,"regression-baseline")], rc = jobs[key(asset,"regression-check")];
    let out = "";
    if (d) {
      if (d.status === "running") out += '<div class="small muted">Replay determinism audit running…</div>';
      else if (d.status === "error") out += `<div class="small neg">Determinism audit: ${esc(d.error || "error")}</div>`;
      else if (d.result) {
        const fd=d.result.first_divergence;
        out += `<div class="small ${d.result.equal ? "pos" : "neg"}">Replay determinism: <b>${d.result.equal ? "MATCH" : "DIVERGENCE"}</b> · ${esc((d.result.first_digest || "").slice(0,12))} / ${esc((d.result.second_digest || "").slice(0,12))}${fd?' · first '+esc(fd.surface)+' @ '+esc(fd.index??'object'):''}</div>`;
      }
    }
    if (r) {
      if (r.status === "running") out += `<div class="small muted">Robustness scan running · ${r.progress || 0}/${r.total || "?"}</div>`;
      else if (r.status === "error") out += `<div class="small neg">Robustness scan: ${esc(r.error || "error")}</div>`;
      else if (r.result) {
        const rows = Object.entries(r.result.sensitivity || {}).map(([name,x]) =>
          `<tr><td>${esc(name)}</td><td>${nfmt(x.net_profit_span)}</td><td>${nfmt(x.max_drawdown_span)}</td></tr>`).join("");
        out += `<details class="group"><summary>±${Math.round((r.result.fraction || .1)*100)}% local sensitivity</summary><div class="scroll"><table><thead><tr><th>Parameter</th><th>Net P&L span</th><th>Max DD span</th></tr></thead><tbody>${rows}</tbody></table></div><div class="small muted">${esc(r.result.note || "")}</div></details>`;
      }
    }
    if (rb?.result) out += `<div class="small pos">Regression baseline: ${esc(rb.result.status || "saved")} · ${esc(rb.result.path || "")}</div>`;
    if (rc?.result) {
      const x = rc.result;
      if (x.status === "NO_BASELINE") out += '<div class="small muted">Regression check: no saved baseline yet.</div>';
      else if (x.diff) {
        const m=x.diff.metrics_delta||{};
        out += `<details class="group" ${x.diff.digest_equal?'':'open'}><summary>Regression check · <span class="${x.diff.digest_equal?'pos':'neg'}">${x.diff.digest_equal?'MATCH':'CHANGED'}</span></summary>
          <div class="scroll"><table><thead><tr><th>Bars Δ</th><th>Trades + / -</th><th>Net P&L Δ</th><th>Max DD Δ</th><th>Expectancy Δ</th><th>PF Δ</th></tr></thead><tbody><tr>
          <td>${nfmt(x.diff.bars_delta)}</td><td>+${x.diff.trades_added||0} / -${x.diff.trades_removed||0}</td><td>${money(m.net_profit)}</td><td>${money(m.max_drawdown)}</td><td>${money(m.expectancy)}</td><td>${nfmt(m.profit_factor)}</td>
          </tr></tbody></table></div>
          <div class="small muted">Baseline ${esc((x.diff.baseline_digest||'').slice(0,12))} · current ${esc((x.diff.current_digest||'').slice(0,12))} · config ${x.diff.config_equal?'same':'changed'} · source ${x.diff.source_equal?'same':'changed'}. Descriptive diff only; ICARUS does not select or activate a configuration from this result.</div>
          ${Object.keys(x.diff.config_changes||{}).length?`<div class="small muted">Config changes: ${esc(Object.keys(x.diff.config_changes).join(', '))}</div>`:''}
          ${Object.keys(x.diff.source_changes||{}).length?`<div class="small muted">Source changes: ${esc(Object.keys(x.diff.source_changes).join(', '))}</div>`:''}
        </details>`;
      }
    }
    return out;
  }

  async function poll(asset, kind, job, prefix) {
    for (let i=0;i<600;i++) {
      await new Promise(r => setTimeout(r,500));
      let j = null;
      try { j = await authed(prefix + job); } catch (_) {}
      if (!j) continue;
      jobs[key(asset,kind)] = j; inject();
      if (j.status === "done" || j.status === "error") return;
    }
  }

  async function start(asset, kind) {
    let path, body, prefix;
    if (kind === "determinism") {
      path="/admin/research/determinism"; body={asset}; prefix="/api/research/determinism/";
    } else if (kind === "robustness") {
      path="/admin/research/robustness"; body={asset,fraction:0.10}; prefix="/api/research/robustness/";
    } else if (kind === "regression-baseline" || kind === "regression-check") {
      const baseline=kind.endsWith("baseline");
      if (baseline && !confirm("Pin the current frozen replay as the explicit regression baseline for "+asset+"? This replaces the prior local baseline but does not change trading behavior.")) return;
      path="/admin/research/regression"; body={asset,mode:baseline?"baseline":"check",...(baseline?{confirm:true}:{})}; prefix="/api/research/regression/";
    } else return;
    let s = null;
    try { s = await admin(path, body, true); } catch (_) {}
    if (!s?.job) return;
    jobs[key(asset,kind)]={status:"running",job:s.job}; inject();
    poll(asset,kind,s.job,prefix);
  }

  function inject() {
    const asset=getAsset(); if (!asset) return;
    const a=getAssetData(asset); if (!a) return;
    const card=[...document.querySelectorAll("section.card")].find(x => (x.querySelector("h2")?.textContent || "").startsWith("Assurance"));
    if (!card) return;
    let host=card.querySelector(".assurance-ext");
    if (!host) { host=document.createElement("div"); host.className="assurance-ext"; host.style.marginTop="12px"; card.appendChild(host); }
    const html=`
      <div class="row" style="gap:6px;flex-wrap:wrap">
        <button class="sm" data-assurance-job="determinism">Replay determinism audit</button>
        <button class="sm" data-assurance-job="robustness">±10% robustness scan</button>
        <button class="sm" data-assurance-job="regression-baseline">Save regression baseline</button>
        <button class="sm" data-assurance-job="regression-check">Compare to baseline</button>
      </div>
      <div class="small muted" style="margin:6px 0 10px">Research-only controls. They run isolated replays and never activate parameters, submit orders, or authorize execution. Saving a regression baseline always requires explicit confirmation.</div>
      ${jobHtml(asset)}
      ${cacheHtml(a)}
      ${breakdownHtml(a)}`;
    if (host._icarusAssuranceHtml !== html) {
      host._icarusAssuranceHtml = html;
      host.innerHTML = html;
    }
  }

  document.addEventListener("click", ev => {
    const b=ev.target.closest("[data-assurance-job]"); if (!b) return;
    const asset=getAsset(); if (asset) start(asset,b.dataset.assuranceJob);
  });
  const mo=new MutationObserver(() => queueMicrotask(inject));
  mo.observe(document.documentElement,{childList:true,subtree:true});
  window.addEventListener("load",inject);
  setInterval(inject,2000);
})();