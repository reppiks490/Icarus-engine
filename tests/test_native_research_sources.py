"""Source schema tests derived from venue documentation, not production assertions."""
import json
from pathlib import Path
import pytest
from tools.native_research import normalize_bars
from tools.native_research_sources import parse_feed


def test_kraken_volume_is_seventh_field_and_incomplete_bar_excluded():
    rows = [[0,'100','104','98','102','101','42',12], [3600,'102','105','100','103','102','9',3]]
    out = normalize_bars('kraken',rows,4000)
    assert out == [dict(start=0,end=3600,open=100.,high=104.,low=98.,close=102.,volume=42.)]


def test_bybit_milliseconds_and_descending_order():
    rows=[['3600000','102','105','100','103','9','27'],['0','100','104','98','102','42','126']]
    out=normalize_bars('bybit',rows,7201)
    assert [b['start'] for b in out] == [0,3600]
    assert out[0]['volume'] == 42


def test_feed_without_publication_clock_not_promoted_to_fresh():
    raw=b'<rss><channel><item><title>Policy</title><link>https://www.federalreserve.gov/x</link></item></channel></rss>'
    out=parse_feed(raw,'FED','https://www.federalreserve.gov',5,6)
    assert out[0]['published_epoch'] is None
    assert out[0]['retrieval_started']==5


def test_workflow_has_no_remote_model_or_chatgpt_worker():
    text=Path('.github/workflows/native-five-research.yml').read_text()
    assert 'secrets.' not in text
    assert 'openai.com' not in text
    assert 'automations' not in text
    assert 'native_research ' in text
    assert 'schedule:' in text


def test_unknown_provider_and_nan_fail_closed():
    with pytest.raises(ValueError):
        normalize_bars('fake', [[0,1,2,1,1,3]],7200)
    with pytest.raises(ValueError):
        normalize_bars('coinbase', [[0,1,float('nan'),1,1,3]],7200)
