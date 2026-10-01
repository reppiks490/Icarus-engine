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

  function breakdownHtml(a) {
    const b = a?.trade_breakdown;
    if (!b) return "";
    const dir = b.direction || {}, hold = b.holding_bars || {}, hrs = b.entry_hour_ct || {};
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
      </details>`;
  }

  function jobHtml(asset) {
    const d = jobs[key(asset,"determinism")], r = jobs[key(asset,"robustness")],
          rb = jobs[key(asset,"regression-baseline")], rc = jobs[key(asset,"regression-check")];
    let out = "";
    if (d) {
      if (d.status === "running") out += '<div class="small muted">Replay determinism audit running…</div>';
      else if (d.status === "error") out += `<div class="small neg">Determinism audit: ${esc(d.error || "error")}</div>`;
      else if (d.result) out += `<div class="small ${d.result.equal ? "pos" : "neg"}">Replay determinism: <b>${d.result.equal ? "MATCH" : "DIVERGENCE"}</b> · ${esc((d.result.first_digest || "").slice(0,12))} / ${esc((d.result.second_digest || "").slice(0,12))}</div>`;
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
      else if (x.diff) out += `<div class="small ${x.diff.digest_equal ? "pos" : "neg"}">Regression check: <b>${x.diff.digest_equal ? "MATCH" : "CHANGED"}</b> · trades +${x.diff.trades_added || 0}/-${x.diff.trades_removed || 0} · Δ net ${nfmt(x.diff.metrics_delta?.net_profit)}</div>`;
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
      path="/admin/research/regression"; body={asset,mode:kind.endsWith("baseline")?"baseline":"check"}; prefix="/api/research/regression/";
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
    host.innerHTML=`
      <div class="row" style="gap:6px;flex-wrap:wrap">
        <button class="sm" data-assurance-job="determinism">Replay determinism audit</button>
        <button class="sm" data-assurance-job="robustness">±10% robustness scan</button>
        <button class="sm" data-assurance-job="regression-baseline">Save regression baseline</button>
        <button class="sm" data-assurance-job="regression-check">Compare to baseline</button>
      </div>
      <div class="small muted" style="margin:6px 0 10px">Research-only controls. They run isolated replays and never activate parameters, submit orders, or authorize execution.</div>
      ${jobHtml(asset)}
      ${breakdownHtml(a)}`;
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