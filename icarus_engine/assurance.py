"""Small deterministic assurance primitives used by replay/regression tooling."""
from __future__ import annotations
import math


def _comparison_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
    except OverflowError:
        return math.inf


def compare_series(reference, candidate, tol=1e-9):
    """Compare finite numeric observations or matching nonnumeric values.

    Nonfinite observations cannot establish parity and report infinite error.
    The tolerance must be finite and nonnegative, including for empty series.
    """
    try:
        tol = float(tol)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("tol must be a finite nonnegative number") from exc
    if not math.isfinite(tol) or tol < 0:
        raise ValueError("tol must be a finite nonnegative number")

    n = min(len(reference), len(candidate))
    first = None
    max_abs = 0.0
    for i in range(n):
        left = _comparison_number(reference[i])
        right = _comparison_number(candidate[i])
        if (left is not None and not math.isfinite(left)) or (right is not None and not math.isfinite(right)):
            d = math.inf
        elif left is None or right is None:
            d = 0.0 if reference[i] == candidate[i] else math.inf
        else:
            d = abs(left - right)
        max_abs = max(max_abs, d)
        if first is None and d > tol:
            first = i
    if first is None and len(reference) != len(candidate):
        first = n
    return {
        "equal": first is None,
        "first_divergence": first,
        "max_abs_error": max_abs,
        "reference_len": len(reference),
        "candidate_len": len(candidate),
    }


def gate_attribution(state: dict):
    keys=("entry_allowed","in_session","gate_long","gate_short","diverge_veto_l","diverge_veto_s","final_l","final_s","eff_thresh","rate_regime","shock_mult")
    return {k:state.get(k) for k in keys}
