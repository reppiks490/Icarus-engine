"""Regression cases for false parity caused by NaN and infinity."""

import math
from decimal import Decimal

import pytest

from icarus_engine.assurance import compare_series


@pytest.mark.parametrize(
    "reference,candidate",
    [
        ([float("nan")], [123]),
        ([123], [float("nan")]),
        ([float("nan")], [float("nan")]),
        ([float("inf")], [float("inf")]),
        ([float("-inf")], [float("-inf")]),
        ([float("inf")], [float("-inf")]),
        ([1], [float("inf")]),
        ([float("-inf")], [1]),
        (["NaN"], ["nan"]),
        (["inf"], ["Infinity"]),
        ([Decimal("NaN")], [Decimal("NaN")]),
        ([Decimal("Infinity")], [Decimal("Infinity")]),
    ],
)
def test_nonfinite_observations_cannot_establish_parity(reference, candidate):
    result = compare_series(reference, candidate)
    assert result["equal"] is False
    assert result["first_divergence"] == 0
    assert result["max_abs_error"] == math.inf
    assert result["reference_len"] == result["candidate_len"] == 1


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_inside_mixed_series_is_the_first_divergence(nonfinite):
    result = compare_series(["opening", 2, nonfinite, "close"], ["opening", 2, nonfinite, "close"])
    assert result["equal"] is False
    assert result["first_divergence"] == 2
    assert result["max_abs_error"] == math.inf


def test_later_nonfinite_value_preserves_an_earlier_finite_divergence():
    result = compare_series([1, float("nan")], [2, 3])
    assert result["equal"] is False
    assert result["first_divergence"] == 0
    assert result["max_abs_error"] == math.inf


@pytest.mark.parametrize("tolerance", [float("nan"), float("inf"), float("-inf"), -1, -1e-12, "nan", None, "invalid"])
@pytest.mark.parametrize("reference,candidate", [([1], [2]), ([], [])])
def test_invalid_tolerance_fails_before_any_parity_decision(tolerance, reference, candidate):
    with pytest.raises(ValueError, match="finite nonnegative"):
        compare_series(reference, candidate, tol=tolerance)


@pytest.mark.parametrize(
    "reference,candidate,tolerance,equal,first,error",
    [
        ([1, 2, 3], [1, 2, 3], 0, True, None, 0.0),
        ([1, 2], [1, 2.25], 0.25, True, None, 0.25),
        ([1, 2], [1, 2.25], 0.24, False, 1, 0.25),
        (["1.25"], [1.25], 0, True, None, 0.0),
        ([None, "opening"], [None, "opening"], 0, True, None, 0.0),
        (["opening", "close"], ["opening", "halt"], 0, False, 1, math.inf),
        ([1, 2], [1], 0, False, 1, 0.0),
        ([1], [1, 2], 0, False, 1, 0.0),
        ([], [], 0, True, None, 0.0),
        ([], [1], 0, False, 0, 0.0),
    ],
)
def test_finite_nonnumeric_and_length_contracts(reference, candidate, tolerance, equal, first, error):
    result = compare_series(reference, candidate, tol=tolerance)
    assert result == {
        "equal": equal,
        "first_divergence": first,
        "max_abs_error": error,
        "reference_len": len(reference),
        "candidate_len": len(candidate),
    }
