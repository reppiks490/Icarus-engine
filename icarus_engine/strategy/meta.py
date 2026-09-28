"""Input metadata (labels, groups, types, ranges, options, tooltips) extracted from the
Pine source, so the dashboard's inputs editor and the TradingView-export importer
speak the same language as the TradingView inputs dialog.

`build_meta(pine_path)` parses `input.*(...)` declarations; the result is cached in
`pine_inputs_meta.json` next to this file so the engine does not need the Pine
source at runtime. Regenerate with:  py -3 -m icarus_engine.strategy.meta <v3_1.txt>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .inputs import Inputs

_CACHE = Path(__file__).with_name("pine_inputs_meta.json")
_RE = re.compile(r'^\s*(?:(?:bool|int|float|string)\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*input\.(float|int|bool|string|session|timeframe|symbol)\((.*)\)\s*$')


def _split_args(s: str) -> List[str]:
    out, buf, depth, q = [], "", 0, None
    for ch in s:
        if q:
            buf += ch
            if ch == q:
                q = None
            continue
        if ch in "\"'":
            q = ch; buf += ch; continue
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(buf.strip()); buf = ""
        else:
            buf += ch
    if buf.strip():
        out.append(buf.strip())
    return out


def _lit(v: str) -> Any:
    v = v.strip()
    if v in ("true", "false"):
        return v == "true"
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    try:
        return int(v) if re.fullmatch(r"-?\d+", v) else float(v)
    except ValueError:
        return v


def build_meta(pine_path: str) -> List[Dict[str, Any]]:
    src = Path(pine_path).read_text(encoding="utf-8").splitlines()
    groups: Dict[str, str] = {}
    for line in src:
        m = re.match(r'^\s*string\s+(GRP_[A-Z0-9_]+)\s*=\s*"([^"]+)"', line)
        if m:
            groups[m.group(1)] = m.group(2)
    known = Inputs().to_dict()
    meta: List[Dict[str, Any]] = []
    order = 0
    for line in src:
        line = re.sub(r'\s//(?=(?:[^"]*"[^"]*")*[^"]*$).*$', "", line)     # strip trailing // comments (outside strings)
        m = _RE.match(line)
        if not m:
            continue
        name, kind, argstr = m.group(1), m.group(2), m.group(3)
        if name not in known:
            continue                                        # display-only inputs are not ported
        args = _split_args(argstr)
        pos = [a for a in args if "=" not in a.split("(")[0] or a.startswith('"')]
        kw = {}
        for a in args:
            k, _, v = a.partition("=")
            if _ and re.fullmatch(r"[a-z_]+", k.strip()):
                kw[k.strip()] = v.strip()
        default = _lit(pos[0]) if pos else known[name]
        label = _lit(pos[1]) if len(pos) > 1 else name
        entry: Dict[str, Any] = {"name": name, "label": label, "kind": kind, "default": default, "order": order,
                                 "group": groups.get(kw.get("group", ""), kw.get("group", "").strip('"') or "Other")}
        order += 1
        for k in ("minval", "maxval", "step"):
            if k in kw:
                entry[k] = _lit(kw[k])
        if "options" in kw:
            entry["options"] = [_lit(x) for x in _split_args(kw["options"].strip("[]"))]
        if "tooltip" in kw:
            entry["tooltip"] = _lit(kw["tooltip"])
        meta.append(entry)
    # inputs the engine adds that are not in the Pine (documented)
    names = {e["name"] for e in meta}
    for name, label, group, tip, kind, options in (
        ("kf_cold_start_fix", "Kalman cold-start fix (v3.2)", "Kalman / PMA Engine",
         "Re-seed the Kalman filter (including its covariance) until every input is a number. Fixes vote #9 never firing; see PARITY.md.", "bool", None),
        ("pe_na_poison_fix", "PE na-poisoning fix (v3.3)", "Permutation Entropy",
         "TradingView: with amplitude weighting the PE bins are poisoned by na on the first bars, pe_norm is stuck at 0 and vote #10 fires on every bar. OFF reproduces that; ON skips the block until its inputs are numbers (v3.3 patch).", "bool", None),
        ("ltf_intrabar", "LTF connection intrabar (engine)", "HTF/LTF Connections",
         "Which intrabar the 2m/5m request.security(expr[1], lookahead_on) calls return: 'first' = TradingView on historical bars (your backtests), 'last' = TradingView on realtime bars.", "string", ["first", "last"]),
    ):
        if name not in names:
            e = {"name": name, "label": label, "kind": kind, "default": known[name], "order": order, "group": group, "tooltip": tip}
            if options:
                e["options"] = options
            meta.append(e); order += 1
    return meta


def load_meta() -> List[Dict[str, Any]]:
    if _CACHE.exists():
        return json.loads(_CACHE.read_text(encoding="utf-8"))
    return [{"name": k, "label": k, "kind": type(v).__name__, "default": v, "order": i, "group": "Inputs"} for i, (k, v) in enumerate(Inputs().to_dict().items())]


def label_map() -> Dict[str, str]:
    return {e["label"]: e["name"] for e in load_meta()}


# ── TradingView export → engine inputs ──
_TF_WORDS = {"minute": 1, "minutes": 1, "hour": 60, "hours": 60, "day": 1440, "days": 1440, "week": 10080, "weeks": 10080}


def tv_value(name: str, raw: Any, kind: str) -> Any:
    """Convert a value as it appears in a TradingView Strategy Tester export (or the inputs
    dialog) into the engine's representation."""
    s = str(raw).strip()
    if kind == "bool":
        return s.lower() in ("on", "true", "1", "yes")
    if kind == "session":
        m = re.match(r"(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})", s)
        if m:
            return f"{int(m.group(1)):02d}{m.group(2)}-{int(m.group(3)):02d}{m.group(4)}"
        return s
    if kind == "timeframe":
        m = re.match(r"(\d+)\s*(minute|minutes|hour|hours|day|days|week|weeks)", s, re.I)
        if m:
            mins = int(m.group(1)) * _TF_WORDS[m.group(2).lower()]
            return "W" if mins == 10080 else "D" if mins == 1440 else str(mins)
        u = s.upper()
        if u in ("D", "1D"):
            return "D"
        if u in ("W", "1W"):
            return "W"
        m = re.match(r"^(\d+)([HM])$", u)
        if m:
            return str(int(m.group(1)) * (60 if m.group(2) == "H" else 1))
        return s
    if kind == "int":
        try:
            return int(float(s.replace(",", "")))
        except ValueError:
            return raw
    if kind == "float":
        try:
            return float(s.replace(",", ""))
        except ValueError:
            return raw
    return s


def inputs_from_tv_properties(props: Dict[str, Any], only_changed: bool = True) -> Dict[str, Any]:
    """Map a TradingView 'Properties' sheet ({label: value}) onto engine input names.
    Unknown labels (chart settings, display-only inputs) are ignored."""
    meta = {e["label"]: e for e in load_meta()}
    defaults = Inputs().to_dict()
    out: Dict[str, Any] = {}
    for label, raw in props.items():
        e = meta.get(label)
        if not e:
            continue
        v = tv_value(e["name"], raw, e["kind"])
        if only_changed and v == defaults[e["name"]]:
            continue
        out[e["name"]] = v
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    meta = build_meta(sys.argv[1])
    _CACHE.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {_CACHE} ({len(meta)} inputs)")
