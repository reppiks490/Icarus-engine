"""Bounded public acquisition. No accounts, trading endpoints or paid inference."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import os
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime

MARKETS = {
    'coinbase_spot': ('coinbase', 'BTC-USD spot', 'https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=3600'),
    'kraken_spot': ('kraken', 'BTC-USD spot', 'https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=60'),
    'bybit_spot': ('bybit', 'BTCUSDT spot', 'https://api.bybit.com/v5/market/kline?category=spot&symbol=BTCUSDT&interval=60&limit=1000'),
    'bybit_linear': ('bybit', 'BTCUSDT linear', 'https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=60&limit=1000'),
}
FEEDS = {
    'FED': 'https://www.federalreserve.gov/feeds/press_all.xml',
    'ECB': 'https://www.ecb.europa.eu/rss/press.html',
    'BLS': 'https://www.bls.gov/feed/bls_latest.rss',
}


def fetch(url, timeout=15):
    start = time.time()
    req = urllib.request.Request(url, headers={'User-Agent': 'ICARUS-native-research/1.0', 'Accept': '*/*'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(4_000_001)
    if len(raw) > 4_000_000:
        raise ValueError('source payload exceeds budget')
    return raw, start, time.time()


def acquire_markets():
    from tools.native_research import normalize_bars
    packets, gaps = {}, []
    def one(item):
        key, (provider, representation, url) = item
        try:
            raw, start, end = fetch(url)
            data = json.loads(raw)
            if provider == 'kraken':
                if data.get('error'):
                    raise ValueError('Kraken returned provider error')
                data = next(v for k,v in data['result'].items() if k != 'last')
            if provider == 'bybit':
                if data.get('retCode') != 0:
                    raise ValueError('Bybit returned provider error')
                data = data['result']['list']
            bars = normalize_bars(provider, data, end)
            if not bars:
                raise ValueError('no completed valid observations')
            return key, dict(provider=provider, representation=representation, source_url=url,
                             bars=bars, retrieval_started=start, retrieval_finished=end,
                             raw_sha256=hashlib.sha256(raw).hexdigest()), None
        except Exception as exc:
            # Do not expose provider response bodies or credential-bearing URLs.
            return key, None, f'{key}: acquisition failed ({type(exc).__name__})'
    with ThreadPoolExecutor(max_workers=4) as pool:
        for key, packet, gap in pool.map(one, MARKETS.items()):
            if packet is not None:
                packets[key] = packet
            if gap:
                gaps.append(gap)
    # Provider-app entitlements are not magically transferred into an Actions runner.
    gaps += ['Direct NQ/MNQ, GC/MGC, SI, DXY and volatility indices not acquired by this public worker.',
             'Twelve Data and Massive connector credentials not exported; no entitlement inferred.',
             'No historical trade signs, depth sequence, liquidations, OI, funding or basis collected.']
    return packets, gaps


def parse_feed(raw, source, url, start, end):
    tree = ET.fromstring(raw)
    out = []
    for item in tree.findall('.//item')[:20]:
        title = (item.findtext('title') or '').strip()
        link = (item.findtext('link') or url).strip()
        date = item.findtext('pubDate')
        stamp = None
        if date:
            try:
                dt = parsedate_to_datetime(date)
                if dt.tzinfo is not None:
                    stamp = dt.timestamp()
            except (ValueError, TypeError):
                pass
        if title:
            out.append(dict(source=source, title=title, source_url=link,
                            published_epoch=stamp, retrieval_started=start, retrieval_finished=end))
    if not out:
        raise ValueError('empty or unsupported feed')
    return out


def acquire_macro():
    result = dict(headlines=[], series=[], gaps=[])
    for source,url in FEEDS.items():
        try:
            raw,start,end = fetch(url)
            result['headlines'].extend(parse_feed(raw,source,url,start,end))
        except Exception as exc:
            result['gaps'].append(f'{source}: release feed unavailable ({type(exc).__name__})')
    for series in ('DGS10','DGS2','DTWEXBGS'):
        # Federal Reserve Economic Data public CSV: daily observations, not intraday evidence.
        url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}'
        try:
            raw,start,end = fetch(url)
            rows = list(csv.DictReader(io.StringIO(raw.decode())))
            good = [r for r in rows if r.get(series) not in (None, '.', '')][-60:]
            values = [dict(date=r.get('DATE') or r.get('observation_date'),value=float(r[series])) for r in good]
            if not values:
                raise ValueError('empty series')
            result['series'].append(dict(source='FRED', series=series, source_url=url,
                                         observations=values, retrieval_started=start, retrieval_finished=end,
                                         raw_sha256=hashlib.sha256(raw).hexdigest()))
        except Exception as exc:
            result['gaps'].append(f'FRED {series}: unavailable ({type(exc).__name__})')
    result['gaps'] += ['Release titles establish publication, not macro surprise or causal impact.',
                       'DGS10/DGS2/DTWEXBGS are daily series; no synchronous intraday macro inference.',
                       'No consensus estimates acquired; economic surprise remains unknown.']
    return result
