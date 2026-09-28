"""Guards on the location premise -- the layer H-LOC put on trial.

H-LOC (docs/RESEARCH_LOG.md) claimed `_location_score` is signed backwards for
a failed-sweep continuation system, and that flipping it roughly doubles
expectancy. On real MNQ the effect it rests on does not exist: the quintile
spread flips sign between the tuning and held-out spans at every timeframe, and
no lambda chosen on the tuning span survives on the held-out one. So the
shipped premise stands, unflipped, and these tests pin it -- a future session
that wants to change the sign has to change a test that says why it is there.

They also pin the one artefact of that investigation that IS in the tree:
`Inputs.vwap_vote_lambda` in `icarus_engine/`. It is a research knob, and it
must ship neutral so the script's behaviour never changes under the user
without someone choosing it.
"""

import pytest

from icarus.config import AssetClass
from icarus.data import synthetic_for
from icarus.indicators import SessionVWAP
from icarus.signal import ConfluenceEngine
from icarus.timeframe import resample
from icarus_engine.strategy.inputs import Inputs
from tools.validate_pulse import run_pulse


def vwap_at(value: float = 100.0, sigma_target: float = 1.0) -> SessionVWAP:
    """A warmed-up VWAP centred on ``value`` with a known sigma."""
    vwap = SessionVWAP()
    for price in (value - sigma_target, value + sigma_target) * 10:
        vwap.update(price, 1.0)
    assert vwap.value == pytest.approx(value)
    assert vwap.sigma == pytest.approx(sigma_target)
    return vwap


def test_a_long_is_scored_better_at_a_discount_than_at_a_premium():
    """The shipped premise: longs want discount, shorts want premium.

    H-LOC argued this is backwards for a continuation system. Real MNQ did not
    support that, so the premise stays -- and stays explicit.
    """
    vwap = vwap_at()
    score = ConfluenceEngine._location_score
    assert score(1, 98.0, vwap) > 0.5 > score(1, 102.0, vwap)
    assert score(-1, 102.0, vwap) > 0.5 > score(-1, 98.0, vwap)


def test_deep_dislocation_rolls_the_score_back_off():
    """Beyond ~3 sigma the discount stops being an edge and becomes a trend."""
    vwap = vwap_at()
    score = ConfluenceEngine._location_score
    assert score(1, 100.0 - 2.5, vwap) > score(1, 100.0 - 6.0, vwap)


def test_no_value_area_yet_is_scored_as_no_opinion():
    assert ConfluenceEngine._location_score(1, 100.0, SessionVWAP()) == 0.5


def test_the_pulse_location_knob_ships_neutral():
    """`vwap_vote_lambda` is a research knob: default must be shipped behaviour."""
    assert Inputs().vwap_vote_lambda == 1.0


def test_the_pulse_location_knob_is_live_but_a_no_op_at_its_default():
    tape = resample(synthetic_for(AssetClass.MICRO_FUTURES, 6000, seed=11, minutes=2), "20m")
    default = run_pulse(tape, tf_minutes=20)
    explicit = run_pulse(tape, tf_minutes=20, vwap_vote_lambda=1.0)
    flipped = run_pulse(tape, tf_minutes=20, vwap_vote_lambda=-1.0)
    assert explicit == default                      # neutral at its default
    assert flipped != default                       # and not dead code
