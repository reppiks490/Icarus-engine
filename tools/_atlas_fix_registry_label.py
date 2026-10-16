from pathlib import Path

path = Path('icarus_engine/dashboard.html')
text = path.read_text(encoding='utf-8')
old = '<div class="small muted" style="margin-top:8px">First-class registry contracts are shown below. Futures use their own tick/multiplier and delayed research feed identity; unknown symbols retain the legacy Coinbase spot fallback.</div>'
new = '<div class="small muted" style="margin-top:8px">Registry: first-class contracts are shown below. Futures use their own tick/multiplier and delayed research feed identity; unknown symbols retain the legacy Coinbase spot fallback.</div>'
if text.count(old) != 1:
    raise SystemExit(f'expected one registry description match, found {text.count(old)}')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
print('registry label compatibility patch applied')
