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

  function completionHtml(a) {
    const g=a?.assurance_completion;
    if (!g) return "";
    const cls=g.status==="READY"?"pos":g.status==="BLOCKED"?"neg":"muted";
    const rows=(g.checks||[]).map(x=>`<tr><td>${esc(x.name||"")}</td><td class="${x.status==="BLOCK"?"neg":x.status==="PASS"?"pos":"muted"}">${esc(x.status||"")}</td><td><code>${esc(JSON.stringify(Object.fromEntries(Object.entries(x).filter(([k])=>!["name","status","execution_authorized"].includes(k)))))}</code></td></tr>`).join("");
    return `<details class="group" open><summary>Assurance completion gate <span class="cnt ${cls}">${esc(g.status||"—")}</span></summary>
      <div class="small ${cls}"><b>${esc(g.status||"—")}</b> · ${esc(g.meaning||"RESEARCH_ASSURANCE_READINESS_ONLY")} · trading permission: ${esc(g.trading_permission||"UNCHANGED")}</div>
      <div class="small muted">Hard blocks: ${esc((g.hard_blocks||[]).join(", ")||"none")} · warnings: ${esc((g.warnings||[]).join(", ")||"none")}</div>
      <div class="small muted">History source: ${esc(g.source_quality?.class||"UNKNOWN")}${g.source_quality?.proxy_warning?" · compatible price proxy, not exact contract history":""}</div>
      <div class="scroll"><table><thead><tr><th>Evidence surface</th><th>Status</th><th>Details</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="small muted">This gate is observational. READY does not authorize trading, deployment, parameter activation, or order submission.</div>
    </details>`;
  }

  function recoveryHtml(a) {
    const r=a?.restart_recovery;
    if (!r) return "";
    const bad=r.status==="DIVERGENCE" || r.status==="REFERENCE_BAR_MISSING";
    const diff=r.check?.differences || {};
    return `<details class="group" ${bad?'open':''}><summary>Restart replay recovery <span class="cnt ${bad?'neg':''}">${esc(r.status||'—')}</span></summary>
      <div class="small ${bad?'neg':'muted'}">Method: ${esc(r.recovery_method||'—')} · executable state restore: ${r.state_restore_enabled?'enabled':'disabled'}</div>
      ${Object.keys(diff).length?`<div class="scroll"><table><thead><tr><th>Surface</th><th>Expected</th><th>Reconstructed</th></tr></thead><tbody>${Object.entries(diff).map(([k,v])=>`<tr><td>${esc(k)}</td><td><code>${esc(JSON.stringify(v.expected))}</code></td><td><code>${esc(JSON.stringify(v.observed))}</code></td></tr>`).join('')}</tbody></table></div>`:''}
      <div class="small muted">ICARUS reconstructs state from persisted market observations and checks the prior decision/position/pending snapshot. It does not deserialize executable order objects.</div>
    </details>`;
  }

  function executionStressHtml(a) {
    const e=a?.execution_stress_v2;
    if (!e || !(e.scenarios||[]).length) return "";
    const rows=e.scenarios.map(x => `<tr><td>${esc(x.name)}</td><td>${Math.round((x.fill_ratio||0)*100)}%</td><td>${x.extra_slippage_ticks??0}t</td><td>${x.latency_adverse_ticks??0}t</td><td>${nfmt(x.extra_commission_per_contract)}</td><td>${money(x.netprofit)}</td><td>${money(x.delta_vs_observed)}</td></tr>`).join("");
    return `<details class="group"><summary>Execution sensitivity v2 <span class="cnt">${e.scenarios.length}</span></summary>
      <div class="scroll"><table><thead><tr><th>Scenario</th><th>Fill ratio</th><th>Slip</th><th>Latency</th><th>Extra fee</th><th>Net P&L</th><th>Δ observed</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="small muted">${esc(e.model||'Research sensitivity only.')} · Closed-trade sensitivity only; this does not simulate or place fills.</div>
    </details>`;
  }

  function voteAttributionHtml(a) {
    const d=a?.decision_trace, groups=d?.by_vote_cooccurrence || {};
    const rows=Object.entries(groups).sort((x,y)=>(y[1]?.pieces||0)-(x[1]?.pieces||0)).map(([name,x]) =>
      `<tr><td>${esc(name)}</td><td>${x.pieces??0}</td><td>${pct(x.win_rate)}</td><td>${money(x.net_profit)}</td><td>${nfmt(x.avg_weight)}</td><td>${nfmt(x.avg_bars)}</td></tr>`).join("");
    if (!rows) return "";
    return `<details class="group"><summary>Signal-family co-occurrence attribution <span class="cnt">${Object.keys(groups).length}</span></summary>
      <div class="scroll"><table><thead><tr><th>Vote/component</th><th>Pieces</th><th>Win rate</th><th>Net P&L</th><th>Avg weight</th><th>Avg bars</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="small muted">${esc(d.attribution_caveat||'Co-occurrence only; overlapping components are not independent causal P&L.')}</div>
    </details>`;
  }

  function integrityHtml(a) {
    const t=a?.timeframe_integrity;
    if (!t) return "";
    const bad=(t.checks||[]).filter(x=>x.future_bucket);
    return `<details class="group"><summary>Multi-timeframe temporal integrity <span class="cnt">${esc(t.status||'—')}</span></summary>
      <div class="small ${t.violations?'neg':'pos'}">${t.violations||0} future-bucket violation(s) · rule: ${esc(t.rule||'')}</div>
      <div class="scroll"><table><thead><tr><th>TF</th><th>Completed bucket</th><th>Current bucket</th><th>Bars</th><th>Status</th></tr></thead><tbody>${(t.checks||[]).map(x=>`<tr><td>${x.tf_minutes}m</td><td>${x.last_completed==null?'—':dtm(x.last_completed)}</td><td>${dtm(x.current_bucket)}</td><td>${x.bars??'—'}</td><td class="${x.future_bucket?'neg':'pos'}">${x.future_bucket?'FUTURE':'OK'}</td></tr>`).join('')}</tbody></table></div>
      ${bad.length?'<div class="small neg">Temporal leakage evidence detected; research outputs should be treated as invalid until resolved.</div>':'<div class="small muted">This is an observational no-lookahead check; it does not alter strategy state.</div>'}
    </details>`;
  }

  function historyShardHtml(a) {
    const used=a?.warmup_shards || [], ignored=a?.warmup_ignored_session_shards || [], stitch=a?.warmup_stitch || null, priv=a?.warmup_private_history || null;
    if (!used.length && !ignored.length && !stitch && !priv) return "";
    const status=stitch?.status || (stitch?.conflicts===0 ? "STITCHED" : "—");
    const privateLine=priv?`<div class="small pos"><b>Private exact source:</b> ${esc(priv.classification||'EXACT_OPERATOR_HISTORY')} · ${esc(priv.display_name||'validated export')} · SHA-256 ${esc((priv.sha256||'').slice(0,16))}… · ${Number(priv.rows||0).toLocaleString()} rows · ${priv.first_ts?dtm(priv.first_ts):'—'} → ${priv.last_ts?dtm(priv.last_ts):'—'}</div>`:'';
    return `<details class="group"><summary>Historical shard provenance <span class="cnt">${used.length} used</span></summary>
      <div class="small"><b>Session:</b> ${esc(a.session_mode||'—')} · <b>status:</b> ${esc(status)} · <b>overlaps:</b> ${stitch?.overlaps??0} · <b>conflicts:</b> ${stitch?.conflicts??0}</div>
      ${privateLine}
      <div class="small muted" style="margin-top:5px"><b>Used:</b> ${used.length?used.map(esc).join(' · '):'none'}<br><b>Ignored session-mismatch:</b> ${ignored.length?ignored.map(esc).join(' · '):'none'}</div>
      <div class="small muted">Raw licensed files remain outside Git. RTH and ETH labelled shards are never silently combined. Conflicting OHLC overlaps are refused rather than arbitrarily selected.</div>
    </details>`;
  }

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
    const cf=a?.counterfactuals, es=a?.execution_stress, ph=a?.provider_health, re=a?.replay_equivalence, cache=a?.persistent_bar_cache;
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
    if (cache) {
      const rr=cache.revisions||{}, rows=(a?.bar_cache_revisions||[]).map(x=>`<tr><td>${x.sub_minutes}m</td><td>${new Date(x.ts*1000).toLocaleString()}</td><td>${x.price_changed?'price':''}${x.price_changed&&x.volume_changed?' + ':''}${x.volume_changed?'volume':''}</td><td>${nfmt(x.old_close)} → ${nfmt(x.new_close)}</td><td>${esc(x.old_source||'—')} → ${esc(x.new_source||'—')}</td></tr>`).join("");
      out += `<details class="group"><summary>Persistent bar cache <span class="cnt">${rr.total??0} revision(s)</span></summary><div class="small muted">Cache stores market observations only, never strategy/order/position state. Price revisions: ${rr.price??0} · volume revisions: ${rr.volume??0}.</div>${rows?`<div class="scroll"><table><thead><tr><th>TF</th><th>Bar</th><th>Changed</th><th>Close</th><th>Source</th></tr></thead><tbody>${rows}</tbody></table></div>`:''}</details>`;
    }
    if (re?.last_divergence) {
      out += `<details class="group" open><summary>Replay equivalence divergence</summary><div class="small neg">At ${esc(re.last_divergence.ts)} · expected ${esc((re.last_divergence.expected||'').slice(0,16))} · observed ${esc((re.last_divergence.observed||'').slice(0,16))}</div><div class="small muted">Evidence only. Executable strategy/order state is never restored from this ledger.</div></details>`;
    }
    return out;
  }

  function jobHtml(asset) {
    const d = jobs[key(asset,"determinism")], p = jobs[key(asset,"live-replay-parity")], r = jobs[key(asset,"robustness")], rm = jobs[key(asset,"robustness-map")], wf = jobs[key(asset,"walkforward")],
          rb = jobs[key(asset,"regression-baseline")], rc = jobs[key(asset,"regression-check")], ch = jobs[key(asset,"continuous-history")];
    let out = "";
    if (d) {
      if (d.status === "running") out += '<div class="small muted">Replay determinism audit running…</div>';
      else if (d.status === "error") out += `<div class="small neg">Determinism audit: ${esc(d.error || "error")}</div>`;
      else if (d.result) {
        const fd=d.result.first_divergence;
        out += `<div class="small ${d.result.equal ? "pos" : "neg"}">Replay determinism: <b>${d.result.equal ? "MATCH" : "DIVERGENCE"}</b> · ${esc((d.result.first_digest || "").slice(0,12))} / ${esc((d.result.second_digest || "").slice(0,12))}${fd?' · first '+esc(fd.surface)+' @ '+esc(fd.index??'object'):''}</div>`;
      }
    }
    if (p) {
      if (p.status === "running") out += '<div class="small muted">Live/replay parity audit running…</div>';
      else if (p.status === "error") out += `<div class="small neg">Live/replay parity: ${esc(p.error || "error")}</div>`;
      else if (p.result) {
        const ok=p.result.status==="MATCH";
        out += `<div class="small ${ok?"pos":p.result.status==="NO_REFERENCE"?"muted":"neg"}">Live/replay parity: <b>${esc(p.result.status)}</b> · live ${esc((p.result.reference?.digest||"—").slice(0,12))} / replay ${esc((p.result.replay?.digest||"—").slice(0,12))}</div>`;
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
    if (rm) {
      if (rm.status === "running") out += `<div class="small muted">Robustness map running · ${rm.progress||0}/${rm.total||"?"}</div>`;
      else if (rm.status === "error") out += `<div class="small neg">Robustness map: ${esc(rm.error||"error")}</div>`;
      else if (rm.result) {
        const rr=rm.result, steps=rr.steps||0, cells=rr.cells||[];
        const xs=[...new Set(cells.map(x=>x.x_value))], ys=[...new Set(cells.map(x=>x.y_value))];
        const rows=ys.map(y=>`<tr><th>${nfmt(y)}</th>${xs.map(x=>{const z=cells.find(q=>q.x_value===x&&q.y_value===y);return `<td class="tnum" title="${z?.error?esc(z.error):''}">${z?.metrics?money(z.metrics.net_profit):'err'}</td>`;}).join('')}</tr>`).join('');
        out += `<details class="group"><summary>Parameter neighborhood map · ${esc(rr.x_field)} × ${esc(rr.y_field)} <span class="cnt">${steps}×${steps}</span></summary>
          <div class="small muted">Cells show net P&L only as a descriptive surface. No optimum/winner is selected or activated.</div>
          <div class="scroll"><table><thead><tr><th>${esc(rr.y_field)} ↓ / ${esc(rr.x_field)} →</th>${xs.map(x=>`<th>${nfmt(x)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div></details>`;
      }
    }
    if (wf) {
      if (wf.status === "running") out += `<div class="small muted">Walk-forward audit running · ${wf.progress||0}/${wf.total||"?"}</div>`;
      else if (wf.status === "error") out += `<div class="small neg">Walk-forward audit: ${esc(wf.error||"error")}</div>`;
      else if (wf.result) {
        const rr=wf.result, rows=(rr.folds||[]).map(x=>`<tr><td>${x.fold}</td><td>${money(x.train?.net_profit)}</td><td>${money(x.test?.net_profit)}</td><td>${nfmt(x.test?.profit_factor)}</td><td>${money(x.test?.max_drawdown)}</td><td>${nfmt(x.test?.total_trades)}</td></tr>`).join('');
        out += `<details class="group"><summary>Rolling walk-forward · baseline configuration <span class="cnt">${rr.folds?.length||0} folds</span></summary>
          <div class="scroll"><table><thead><tr><th>Fold</th><th>Train net</th><th>OOS net</th><th>OOS PF</th><th>OOS max DD</th><th>OOS trades</th></tr></thead><tbody>${rows}</tbody></table></div>
          <div class="small muted">Positive OOS folds ${rr.stability?.test_net_positive_folds??0}/${rr.folds?.length||0} · OOS net range ${money(rr.stability?.test_net_min)} to ${money(rr.stability?.test_net_max)}. ${esc(rr.note||'')}</div>
        </details>`;
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
    if (ch) {
      if (ch.status === "running") out += '<div class="small muted">Continuous futures history build running…</div>';
      else if (ch.status === "error") out += `<div class="small neg">Continuous history build: ${esc(ch.error || "error")}</div>`;
      else if (ch.result) out += `<div class="small pos">Continuous history build complete · raw ${esc(ch.result.raw_path||"")} · adjusted ${esc(ch.result.adjusted_path||"")} · rolls ${ch.result.meta?.roll_diagnostics?.length??0}</div>`;
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
    } else if (kind === "live-replay-parity") {
      path="/admin/research/live-replay-parity"; body={asset}; prefix="/api/research/live-replay-parity/";
    } else if (kind === "continuous-history") {
      path="/admin/research/continuous-history"; body={asset}; prefix="/api/research/continuous-history/";
    } else if (kind === "walkforward") {
      path="/admin/research/walkforward"; body={asset,folds:5,train_fraction:0.50}; prefix="/api/research/walkforward/";
    } else if (kind === "robustness-map") {
      path="/admin/research/robustness-map"; body={asset,x_field:"shock_z_thresh",y_field:"pe_thresh",fraction:0.10,steps:5}; prefix="/api/research/robustness-map/";
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
        <button class="sm" data-assurance-job="live-replay-parity">Live ↔ replay parity</button>
        <button class="sm" data-assurance-job="robustness">±10% robustness scan</button>
        <button class="sm" data-assurance-job="robustness-map">2D robustness map</button>
        <button class="sm" data-assurance-job="walkforward">Rolling walk-forward audit</button>
        <button class="sm" data-assurance-job="regression-baseline">Save regression baseline</button>
        <button class="sm" data-assurance-job="regression-check">Compare to baseline</button>
        ${a.continuous_archive?.configured?`<button class="sm" data-assurance-job="continuous-history">Build continuous futures research archive</button>`:''}
      </div>
      <div class="small muted" style="margin:6px 0 10px">Research-only controls. They run isolated replays and never activate parameters, submit orders, or authorize execution. Saving a regression baseline always requires explicit confirmation.</div>
      <div class="small"><b>Warm-up depth:</b> ${Number(a.warmup_loaded_bars??0).toLocaleString()} loaded / ${Number(a.warmup_target_bars??0).toLocaleString()} target · ${a.warmup_quality_gate?.status||"UNKNOWN"}</div>
      ${a.kind==="futures"?`<div class="small muted">Continuous archive input: ${a.continuous_archive?.configured?"configured ("+(a.continuous_archive?.contract_files?.length||0)+" contracts)":"not configured"} · expected under ${esc(a.continuous_archive?.root||"history/contracts/<SYMBOL>")}.</div>`:""}
      ${completionHtml(a)}
      ${jobHtml(asset)}
      ${recoveryHtml(a)}
      ${integrityHtml(a)}
      ${voteAttributionHtml(a)}
      ${executionStressHtml(a)}
      ${historyShardHtml(a)}
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