"""Locked paper-runtime adapter for durable activation overlays.

Replay happens in an isolated journal/emulator. Adoption preserves the actual
paper emulator and its accounting; no historical position or fill is imported.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from copy import deepcopy
from dataclasses import asdict
import hashlib
import math
from pathlib import Path

from .activation import ActivationError, ActivationStore
from .advisory import canonical_hash
from .assets import AssetSpec
from .emulator import Emulator
from .runtime import AssetRunner, Journal, RunnerConfig, preset_path, validate_values
from .strategy.inputs import Inputs


_MISSING = object()
_TRANSFER = ("cfg", "spec", "inputs_base", "inputs", "pts_scale", "mintick", "cal", "chart_minutes",
             "strat", "htf_tfs", "chains", "chart_agg", "ha", "_real_ohlc_warned", "bar_index",
             "bars", "overlays", "state", "_activation_version_id", "_activation_owner_cfg",
             "_activation_quarantine")


def _owner_manifest(port, runner):
    # Overlay changes are inputs/sources only. All original scale/spec/runtime
    # settings and source-file bytes remain part of the restart guard.
    cfg = asdict(runner.cfg)
    original = getattr(runner, "_activation_owner_cfg", cfg)
    cfg["inputs"], cfg["sources"] = original["inputs"], original["sources"]
    # Receipt time can advance on restart even when the actual scale/configuration
    # is identical. The durable profile restores the prior timestamp only after
    # this owner manifest and exact scale checks pass. It is not an input setting.
    cfg["scale_known_at"] = None
    root = Path(port.base_dir)
    files = {root / "inputs.json", root / f"inputs.{runner.symbol}.json"}
    files.update(root.glob("inputs.*.json"))
    for name in (port.preset, runner.spec.preset, runner.cfg.preset):
        if name:
            files.add(Path(preset_path(port.base_dir, name)))
    hashes = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
              for path in sorted(files)}
    return {"runner_config": cfg, "files": hashes,
            "portfolio": {"profile": port.profile, "preset": port.preset, "warmup_bars": port.warmup_bars,
                          "pts_ref_symbol": port.pts_ref_symbol}}


class ActivationRuntime:
    """Callbacks are local-only and execute under portfolio/sorted runner locks.

    verify_artifact(artifact) returns the current qualified, approved export.
    fingerprint(asset, candidate) returns the workspace's scoped frozen tuple
    (frozen_port, dataset_hash, baseline_hash, baseline_config).
    """
    def __init__(self, port, verify_artifact=None, fingerprint=None):
        self.port, self.verify_artifact, self.fingerprint = port, verify_artifact, fingerprint

    @contextmanager
    def boundary(self, asset):
        with self.port._lock, ExitStack() as stack:
            for symbol in sorted(self.port.runners):
                stack.enter_context(self.port.runners[symbol].lock)
            runner = self.port.runners.get(asset)
            if runner is None or runner._removed:
                raise ActivationError("activation asset is not running")
            yield _Boundary(self, runner)


class _Boundary:
    def __init__(self, adapter, runner):
        self.adapter, self.port, self.runner = adapter, adapter.port, runner
        self.saved = {}

    def _ready(self):
        r = self.runner
        if type(r.em) is not Emulator:
            raise ActivationError("activation supports the local paper emulator only")
        r.ensure_configurable(allow_overlay=True)
        if r.last_error or r.feed_error or r.runtime_error:
            raise ActivationError("runner has unresolved feed/runtime errors")
        if r.em._exits:
            raise ActivationError("pending protective orders must be reconciled before activation")
        if not r.subbars or r.strat is None:
            raise ActivationError("activation requires a warmed cached strategy")
        if r.spec.fill_on != "real":
            raise ActivationError("activation requires real-price paper fills")

    def validate(self, version):
        self._ready()
        if version is None:
            return
        if self.adapter.verify_artifact is None or self.adapter.fingerprint is None:
            raise ActivationError("local qualification verification is not configured")
        artifact = version["artifact"]
        current = self.adapter.verify_artifact(deepcopy(artifact))
        if current is None or canonical_hash(current) != canonical_hash(artifact):
            raise ActivationError("current approved qualified export differs from activation version")
        candidate = artifact["candidate"]
        if candidate["asset"] != self.runner.symbol:
            raise ActivationError("candidate asset mismatch")
        _, dataset, baseline, _ = self.adapter.fingerprint(self.runner.symbol, candidate)
        if (dataset, baseline) != (candidate["dataset_hash"], candidate["baseline_hash"]):
            raise ActivationError("current history/configuration differs from approved candidate")
        values = {**self.runner.inputs_base.to_dict(), **candidate["inputs"]}
        validate_values(values)
        self.runner.ensure_cached_timeframes(Inputs(**values))

    def snapshot(self):
        r = self.runner
        owner = _owner_manifest(self.port, r)
        profile = {"schema_version": 1, "asset": r.symbol, "base_inputs": r.inputs_base.to_dict(),
                   "cfg": asdict(r.cfg), "sources": deepcopy(r.cfg.sources), "pts_scale": r.pts_scale,
                   "mintick": r.mintick, "owner_config": owner, "owner_config_hash": canonical_hash(owner),
                   "active_version_id": getattr(r, "_activation_version_id", None)}
        self.saved[canonical_hash(profile)] = {name: getattr(r, name, _MISSING) for name in _TRANSFER}
        return profile

    def apply(self, version):
        profile = self.snapshot()
        patch = version["artifact"]["candidate"]["inputs"]
        profile["base_inputs"].update(patch)
        profile["cfg"]["inputs"] = deepcopy(profile["base_inputs"])
        profile["active_version_id"] = version["version_id"]
        profile["sources"] = list(profile["sources"] or []) + ["activation:" + version["version_id"]]
        profile["cfg"]["sources"] = profile["sources"]
        self._adopt(profile)

    def restore(self, profile):
        saved = self.saved.get(canonical_hash(profile))
        if saved is not None:
            # Failed application/commit: restore exact references and cfg points,
            # without replaying or touching any actual accounting/event state.
            for name, value in saved.items():
                if value is _MISSING:
                    self.runner.__dict__.pop(name, None)
                else:
                    setattr(self.runner, name, value)
            return
        self._adopt(profile)

    def _adopt(self, profile):
        self._ready()
        r = self.runner
        if (profile.get("schema_version") != 1 or profile.get("asset") != r.symbol
                or canonical_hash(profile.get("owner_config")) != profile.get("owner_config_hash")
                or canonical_hash(_owner_manifest(self.port, r)) != profile["owner_config_hash"]):
            raise ActivationError("owner configuration changed; overlay requires review")
        values = deepcopy(profile["base_inputs"])
        if set(values) != set(Inputs().to_dict()):
            raise ActivationError("overlay must contain the complete base input configuration")
        validate_values(values)
        inputs = Inputs(**values)
        r.ensure_cached_timeframes(inputs)
        cfg_values = deepcopy(profile["cfg"])
        if cfg_values["inputs"] != values or cfg_values["sources"] != profile["sources"]:
            raise ActivationError("overlay inputs/sources disagree with runner configuration")
        spec = AssetSpec(**cfg_values.pop("spec"))
        cfg_values["inputs"] = inputs
        target_cfg = RunnerConfig(spec=spec, **cfg_values)
        if asdict(spec) != asdict(r.spec):
            raise ActivationError("overlay cannot change instrument, capital or execution costs")
        if profile["mintick"] != r.mintick or profile["pts_scale"] != r.pts_scale:
            raise ActivationError("overlay scale/tick differs from the current verified source")
        shadow_cfg = deepcopy(target_cfg)
        shadow_cfg.fixed_pts_scale, shadow_cfg.mintick = profile["pts_scale"], profile["mintick"]
        journal = Journal(":memory:")
        try:
            shadow = AssetRunner(shadow_cfg, journal)
            shadow.subbars, shadow.deep = list(r.subbars), deepcopy(r.deep)
            shadow.T_w, shadow.warm = r.T_w, True
            shadow.pts_scale = profile["pts_scale"]
            shadow.rewarm(inputs, profile["sources"])
            # A timed flush can close the final incomplete cached bucket. Repeat
            # only closures already observed by the real runner, never wall time.
            for minute, chain in shadow.chains.items():
                original = r.chains.get(minute)
                if original and chain.agg.forming is not None and chain.agg.bucket == original.last_completed:
                    chain.on_completed_bar(chain.agg._close())
            if shadow.chart_agg.forming is not None and r.bars and shadow.chart_agg.bucket == r.bars[-1].ts:
                shadow._on_chart_bar(shadow.chart_agg._close(), live=False)
            if shadow.bar_index != r.bar_index or [b.ts for b in shadow.bars] != [b.ts for b in r.bars]:
                raise ActivationError("cached replay cannot reproduce the current closed-bar boundary")
            if (shadow.strat is None or shadow.em.open or shadow.em._pending_entries
                    or shadow.em._pending_closes or shadow.em._exits):
                raise ActivationError("candidate shadow replay has open positions or pending orders")
            if canonical_hash(_owner_manifest(self.port, r)) != profile["owner_config_hash"]:
                raise ActivationError("owner configuration changed during shadow replay")
            shadow.strat.em = r.em
            shadow.strat._prev_closed = len(r.em.closed)
            shadow.strat._p_netprofit = r.em.netprofit
            previous_pnl = r.strat._p_netprofit
            pending_realized = r.em.netprofit - previous_pnl if math.isfinite(previous_pnl) else 0.0
            shadow.strat.daily_pnl = r.strat.daily_pnl + pending_realized
            shadow.strat.bars_since_stop = r.strat.bars_since_stop
            # Manual fills can arrive after the last strategy bar. Preserve the
            # actual stop gate even when its closed-trade cursor is unprocessed.
            if any(t.entry_id in ("Long", "Short") and t.exit_comment in ("L_SL", "S_SL")
                   for t in r.em.closed[r.strat._prev_closed:]):
                shadow.strat.bars_since_stop = 0
            shadow.state["bars_since_stop"] = shadow.strat.bars_since_stop
            shadow.state["daily_pnl"] = shadow.strat.daily_pnl
            shadow.strat.paused = r.paused
            owner_cfg = deepcopy(profile["owner_config"]["runner_config"])
            for name in _TRANSFER:
                if name.startswith("_activation_") or name == "cfg":
                    continue
                setattr(r, name, getattr(shadow, name))
            r.cfg, r.spec = target_cfg, target_cfg.spec
            r._activation_owner_cfg = owner_cfg
            r._activation_version_id = profile["active_version_id"]
            r._activation_quarantine = None
        finally:
            journal.con.close()

    def quarantine(self, reason):
        self.runner._activation_quarantine = str(reason)
        self.runner.set_paused(True)
        self.runner.journal.log("ERROR", f"[{self.runner.symbol}] activation quarantined: {reason}")


def load_startup_overlay(port, runner):
    """Load an existing intact paper overlay after warmup, before first poll.

    Original owner files/configuration must still match. A blocked or incomplete
    durable operation remains quarantined for explicit recovery; startup does not
    register, approve or create a new activation.
    """
    root = Path(port.base_dir) / "research" / "activation"
    if not (root / "activation.sqlite3").exists():
        return False
    adapter = ActivationRuntime(port)
    try:
        store = ActivationStore(root)
        # Keep the durable writer lock through adoption; reading active_profile
        # and then locking the runtime would allow a concurrent newer activation
        # to be overwritten by this stale startup snapshot.
        with store._exclusive():
            with store._connect() as con:
                if store._pending(con, runner.symbol):
                    raise ActivationError("interrupted activation requires explicit recovery")
                active = store._read(con.execute("SELECT * FROM activation_active WHERE asset=?", (runner.symbol,)).fetchone())
                if active is None:
                    return False
                version = store._read(con.execute("SELECT * FROM activation_versions WHERE version_id=?", (active["version_id"],)).fetchone())
            profile = active["profile"]
            if (not version or profile.get("active_version_id") != version["version_id"]
                    or version["asset"] != runner.symbol
                    or any(profile["base_inputs"].get(k) != v for k, v in version["artifact"]["candidate"]["inputs"].items())):
                raise ActivationError("active overlay does not match its approved version")
            with adapter.boundary(runner.symbol) as boundary:
                boundary.restore(profile)
        return True
    except Exception as ex:
        with adapter.boundary(runner.symbol) as boundary:
            boundary.quarantine(f"startup overlay blocked: {type(ex).__name__}: {ex}")
        return False
