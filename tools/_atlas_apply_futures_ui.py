from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one guarded match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


server = Path("icarus_engine/server.py")
helper_marker = "\nCOMMANDS = [\n"
helper = '''\n\ndef asset_registry_payload(running=()):
    """Public registry metadata used by the dashboard and automation clients.

    This describes configured contract identity/economics and feed capability.
    It does not imply current provider reachability or live execution authority.
    """
    return {
        "registry": [
            {
                "symbol": s.symbol,
                "name": s.name,
                "feed": s.feed,
                "ticker": s.ticker,
                "feed_mode": s.feed_mode,
                "calendar": s.calendar,
                "session": s.session,
                "group": s.group,
                "mintick": s.mintick,
                "multiplier": s.multiplier,
                "kind": s.kind,
                "exchange": s.exchange,
                "asset_class": s.asset_class,
                "micro_of": s.micro_of,
                "tv_symbol": s.tv_symbol,
            }
            for s in REGISTRY.values()
        ],
        "running": list(running),
    }

COMMANDS = [
'''
replace_once(server, helper_marker, helper)

old_endpoint = '''            if p.path == "/api/assets":
                return self._json(200, {"registry": [{"symbol": s.symbol, "name": s.name, "feed": s.feed, "calendar": s.calendar, "mintick": s.mintick, "multiplier": s.multiplier, "kind": s.kind} for s in REGISTRY.values()],
                                        "running": list(port.order)})
'''
new_endpoint = '''            if p.path == "/api/assets":
                return self._json(200, asset_registry_payload(port.order))
'''
replace_once(server, old_endpoint, new_endpoint)
replace_once(
    server,
    '    {"id": "add-asset", "label": "Add asset", "desc": "Start a new asset (NQ ES YM GC SI PL PA BTCF MBT BTC ETH SOL …).", "scope": "all", "danger": False},\n',
    '    {"id": "add-asset", "label": "Add asset", "desc": "Start any first-class asset from the runtime registry with its own contract economics.", "scope": "all", "danger": False},\n',
)


dashboard = Path("icarus_engine/dashboard.html")
old_ui = '''    <div class="row"><input id="addSym" type="text" placeholder="symbol (NQ, ES, GC, BTC…)" style="width:170px"><input id="addTf" type="text" placeholder="tf (20)" style="width:80px"><select id="addPreset"><option value="">preset: engine default</option>${PRESETS.map(p=>`<option value="${esc(p.name)}">${esc(p.name)}</option>`).join('')}</select><button class="primary sm" id="addBtn">Add</button></div>
    <div class="small muted" style="margin-top:6px">Registry: ${REGISTRY.map(r=>`<code>${r.symbol}</code>`).join(' ')} — anything else is treated as a Coinbase spot pair.</div></section>
'''
new_ui = '''    <div class="row"><input id="addSym" list="addAssetRegistry" type="text" placeholder="registered symbol (MNQ, MCL, 6E…)" style="width:210px"><datalist id="addAssetRegistry">${REGISTRY.map(r=>`<option value="${esc(r.symbol)}">${esc(r.exchange||'')} ${esc(r.name||'')}</option>`).join('')}</datalist><input id="addTf" type="text" placeholder="tf (20)" style="width:80px"><select id="addPreset"><option value="">preset: engine default</option>${PRESETS.map(p=>`<option value="${esc(p.name)}">${esc(p.name)}</option>`).join('')}</select><button class="primary sm" id="addBtn">Add</button></div>
    <div class="small muted" style="margin-top:8px">First-class registry contracts are shown below. Futures use their own tick/multiplier and delayed research feed identity; unknown symbols retain the legacy Coinbase spot fallback.</div>
    <div class="scroll" style="max-height:270px;margin-top:8px"><table><thead><tr><th>Symbol</th><th>Exchange</th><th>Class</th><th>Micro parent</th><th>Tick</th><th>$/point</th><th>Feed</th></tr></thead><tbody>${REGISTRY.map(r=>`<tr><td><code>${esc(r.symbol)}</code></td><td>${esc(r.exchange||'—')}</td><td>${esc(r.asset_class||r.kind||'—')}</td><td>${esc(r.micro_of||'—')}</td><td class="tnum">${px(r.mintick)}</td><td class="tnum">${px(r.multiplier)}</td><td>${esc(r.feed_mode||r.feed||'—')}</td></tr>`).join('')}</tbody></table></div></section>
'''
replace_once(dashboard, old_ui, new_ui)

print("guarded futures API/UI patch applied")
