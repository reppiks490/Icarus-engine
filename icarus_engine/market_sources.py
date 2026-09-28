"""Bounded public official-source collectors, separate from the paper runtime.

No credentials are invented, publication dates are never inferred from report
periods, and REST trades do not authorize trading or change engine candles.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET

from .advisory import _asset, _iso
from .microstructure import TradeAggregator, TradeEvent


CFTC_CONTRACTS = {
    "NQ": ("gpe5-46if", "209742", "tff-futures-only"),
    "ES": ("gpe5-46if", "13874A", "tff-futures-only"),
    "YM": ("gpe5-46if", "124603", "tff-futures-only"),
    "BTCF": ("gpe5-46if", "133741", "tff-futures-only"),
    "GC": ("72hh-3qpy", "088691", "disaggregated-futures-only"),
    "SI": ("72hh-3qpy", "084691", "disaggregated-futures-only"),
    "PL": ("72hh-3qpy", "076651", "disaggregated-futures-only"),
    "PA": ("72hh-3qpy", "075651", "disaggregated-futures-only"),
}
ASSETS = tuple(CFTC_CONTRACTS) + ("BTC",)
RSS = {"federal-reserve": "https://www.federalreserve.gov/feeds/press_all.xml",
       "bea": "https://apps.bea.gov/rss/rss.xml"}
SOURCES = ("cftc", "bls", "federal-reserve", "bea", "sec", "coinbase", "yahoo-dxy")


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _stamp(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return _iso(dt.timestamp())


def _number(value):
    result = float(Decimal(str(value)))
    if not math.isfinite(result):
        raise ValueError("source numeric value is not finite")
    return result


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("public collector redirects are forbidden")


class MarketSources:
    def __init__(self, root, ledger):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "market-sources.sqlite3"
        self.ledger = ledger
        self._lock = threading.RLock()
        self._last_request = 0.0
        with self._db() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS source_records (
                    id TEXT PRIMARY KEY, source TEXT NOT NULL, kind TEXT NOT NULL,
                    instrument TEXT NOT NULL, received_ns INTEGER NOT NULL,
                    body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS source_status (source TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS trade_stream (instrument TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS source_trades (
                    trade_id INTEGER PRIMARY KEY, body TEXT NOT NULL, received_ns INTEGER NOT NULL);
            """)

    @contextmanager
    def _db(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    def _fetch(self, url, headers=None):
        # All URLs are constructed from fixed official hosts and validated IDs.
        if urlsplit(url).hostname not in {"publicreporting.cftc.gov", "api.bls.gov", "data.sec.gov",
                                         "www.federalreserve.gov", "www.bea.gov", "apps.bea.gov", "api.exchange.coinbase.com",
                                         "query1.finance.yahoo.com"}:
            raise ValueError("collector host is not allowlisted")
        delay = .25 - (time.monotonic() - self._last_request)
        if delay > 0:
            time.sleep(delay)
        self._last_request = time.monotonic()
        request = Request(url, headers={"User-Agent": "Icarus-public-research/1.0",
                          "Accept": "application/json, application/rss+xml, application/xml, text/xml, */*", **(headers or {})})
        with build_opener(_NoRedirect).open(request, timeout=15) as response:
            raw = response.read(16 * 1024 * 1024 + 1)
            received_ns = time.time_ns()
            if len(raw) > 16 * 1024 * 1024:
                raise ValueError("source response exceeds 16 MiB")
            return raw, {k.lower(): v for k, v in response.headers.items()}, received_ns

    def _record(self, source, kind, instrument, source_id, url, received_ns, data,
                *, assets=(), observed_at=None, published_at=None, values=None, units=None,
                report_family=None, text=None):
        revision = _hash(data)
        record = {"source": source, "kind": kind, "instrument_id": instrument,
                  "source_event_id": source_id, "revision_id": revision, "source_url": url,
                  "asset_ids": list(assets), "observed_at": observed_at, "published_at": published_at,
                  "available_at": _iso(received_ns / 1e9), "received_ns": received_ns,
                  "timing_basis": "published" if published_at else "first_observed",
                  "quality_flags": [] if published_at else ["publication_time_unknown"],
                  "data": data, "values": values or {}, "units": units or {},
                  "report_family": report_family, "text": text}
        record["id"] = _hash([source, source_id, revision])
        with self._db() as con:
            con.execute("INSERT OR IGNORE INTO source_records VALUES (?,?,?,?,?,?)",
                        (record["id"], source, kind, instrument, received_ns, _json(record)))
            # Repeated retrieval must not refresh first-known availability.
            return json.loads(con.execute("SELECT body FROM source_records WHERE id=?", (record["id"],)).fetchone()[0])

    @staticmethod
    def advisory_event(record):
        if (not record["asset_ids"] or not record["observed_at"] or record["kind"] in ("trades", "prices")
                or (record["kind"] == "correlation" and not record["values"])):
            return None
        event = {"schema_version": 1, "source": record["source"],
                 "source_event_id": record["source_event_id"], "revision_id": record["revision_id"],
                 "source_url": record["source_url"], "event_type": record["kind"],
                 "asset_ids": record["asset_ids"], "instrument_id": record["instrument_id"],
                 "observed_at": record["observed_at"], "published_at": record["published_at"],
                 "timing_basis": record["timing_basis"], "values": record["values"],
                 "units": record["units"], "quality_flags": record["quality_flags"]}
        if record["report_family"]:
            event["report_family"] = record["report_family"]
        if record["text"]:
            event["text"] = record["text"][:8000]
        return event

    def collect(self, source, options=None):
        if source not in SOURCES:
            raise ValueError("unknown public source")
        options = dict(options or {})
        with self._lock:
            report = {"source": source, "status": "error", "attempted_at": _iso(time.time()),
                      "connected": False, "records": 0, "event_ids": [], "warnings": [], "error": None}
            try:
                if source == "cftc":
                    records, details = self._cftc(options)
                elif source == "bls":
                    records, details = self._bls(options)
                elif source == "sec":
                    records, details = self._sec(options)
                elif source == "coinbase":
                    records, details = self._coinbase(options)
                elif source == "yahoo-dxy":
                    from .correlations import collect_dxy
                    records, details = collect_dxy(self, options)
                else:
                    records, details = self._rss(source, options)
                for record in records:
                    event = self.advisory_event(record)
                    if event is not None and self.ledger is not None:
                        try:
                            saved = self.ledger.ingest_event(event)
                            report["event_ids"].append(saved["event_id"])
                        except ValueError as ex:
                            report["warnings"].append(str(ex))
                report.update(status="collected", connected=True, records=len(records), details=details,
                              last_success_at=_iso(time.time()))
            except Exception as ex:
                report["error"] = f"{type(ex).__name__}: {ex}"
            with self._db() as con:
                old = con.execute("SELECT body FROM source_status WHERE source=?", (source,)).fetchone()
                if old and "last_success_at" not in report:
                    report["last_success_at"] = json.loads(old[0]).get("last_success_at")
                con.execute("INSERT INTO source_status VALUES (?,?) ON CONFLICT(source) DO UPDATE SET body=excluded.body",
                            (source, _json(report)))
            return report

    def status(self):
        with self._db() as con:
            saved = {row[0]: json.loads(row[1]) for row in con.execute("SELECT source,body FROM source_status")}
        return {"sources": {source: saved.get(source, {"source": source, "status": "not_collected", "connected": False})
                            for source in SOURCES}, "sec_identity_configured": bool(os.environ.get("SEC_USER_AGENT")),
                "execution_authorized": False, "note": "Successful public observations are not a licensed futures tick feed."}

    def records(self, kind="asset", asset=None, cik=None, limit=100):
        if kind not in ("asset", "companies", "trades") or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("invalid record kind or limit")
        if asset is not None:
            _asset(asset)
        if cik is not None:
            cik = self._cik(cik)
        with self._db() as con:
            if kind == "trades":
                rows = [json.loads(row[0]) for row in con.execute("SELECT body FROM source_trades ORDER BY trade_id DESC LIMIT ?", (limit,))]
                state = con.execute("SELECT body FROM trade_stream WHERE instrument='BTC-USD'").fetchone()
                return {"kind": kind, "records": rows, "stream": json.loads(state[0]) if state else None,
                        "execution_authorized": False}
            clause = "WHERE kind='company'" if kind == "companies" else "WHERE kind NOT IN ('trades','company','prices')"
            params = []
            if cik is not None:
                clause += " AND instrument=?"
                params.append("CIK" + cik)
            rows = con.execute("SELECT body FROM source_records " + clause + " ORDER BY received_ns DESC", params)
            records = []
            for row in rows:
                record = json.loads(row[0])
                if asset is None or asset in record["asset_ids"]:
                    records.append(record)
                    if len(records) >= limit:
                        break
        return {"kind": kind, "records": records, "execution_authorized": False}

    @staticmethod
    def _options(options, allowed):
        if set(options) - set(allowed):
            raise ValueError("unknown collector options")

    @staticmethod
    def _assets(options):
        assets = options.get("assets", list(ASSETS))
        if type(assets) is not list or not assets or len(assets) > 9 or len(set(assets)) != len(assets):
            raise ValueError("assets must be a nonempty unique bounded list")
        return [_asset(asset) for asset in assets]

    def _cftc(self, options):
        self._options(options, ("assets", "asset"))
        assets = [options["asset"]] if "asset" in options else options.get("assets", list(CFTC_CONTRACTS))
        if type(assets) is not list or not assets or len(assets) > 8 or any(a not in CFTC_CONTRACTS for a in assets):
            raise ValueError("CFTC assets must have exact futures contract mappings")
        records = []
        for asset in assets:
            dataset, code, family = CFTC_CONTRACTS[asset]
            url = f"https://publicreporting.cftc.gov/resource/{dataset}.json?" + urlencode({
                "$where": f"cftc_contract_market_code='{code}'", "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": 1})
            raw, _, received = self._fetch(url)
            rows = json.loads(raw)
            if type(rows) is not list or len(rows) != 1 or rows[0].get("cftc_contract_market_code") != code:
                raise ValueError("CFTC response does not match exact contract code")
            row = rows[0]
            fields = ("open_interest_all", "dealer_positions_long_all", "dealer_positions_short_all",
                      "asset_mgr_positions_long", "asset_mgr_positions_short", "lev_money_positions_long",
                      "lev_money_positions_short") if dataset == "gpe5-46if" else (
                      "open_interest_all", "prod_merc_positions_long", "prod_merc_positions_short",
                      "m_money_positions_long_all", "m_money_positions_short_all")
            values = {field: _number(row[field]) for field in fields}
            observed = _stamp(row["report_date_as_yyyy_mm_dd"])
            records.append(self._record("cftc", "cot", code, f"{code}:{observed[:10]}", url, received, row,
                assets=[asset], observed_at=observed, values=values,
                units={field: "contracts" for field in values}, report_family=family,
                text=row["market_and_exchange_names"]))
        return records, {"mapped_assets": assets, "publication_timestamp_known": False}

    def _bls(self, options):
        self._options(options, ("assets",))
        assets = self._assets(options)
        series = "CUUR0000SA0"
        url = f"https://api.bls.gov/publicAPI/v1/timeseries/data/{series}"
        raw, _, received = self._fetch(url)
        result = json.loads(raw)
        if result.get("status") != "REQUEST_SUCCEEDED":
            raise ValueError("BLS did not succeed")
        series_rows = result["Results"]["series"]
        if len(series_rows) != 1 or series_rows[0]["seriesID"] != series:
            raise ValueError("BLS response series mismatch")
        rows = [row for row in series_rows[0]["data"] if re.fullmatch(r"M(0[1-9]|1[0-2])", row["period"])]
        if not rows:
            raise ValueError("BLS has no monthly CPI observations")
        row = max(rows, key=lambda r: (r["year"], r["period"]))
        period = f"{row['year']}-{row['period'][1:]}"
        record = self._record("bls", "macro", series, f"{series}:{period}", url, received, row,
            assets=assets, observed_at=period + "-01T00:00:00.000000Z", values={"cpi_index": _number(row["value"])},
            units={"cpi_index": "index_1982_1984_100"}, report_family="cpi-all-urban-unadjusted",
            text="CPI-U all items, not seasonally adjusted; observation denotes the stated reference month, not release time.")
        return [record], {"series": series, "reference_month": period, "publication_timestamp_known": False}

    def _rss(self, source, options):
        self._options(options, ("assets", "limit"))
        assets = self._assets(options)
        limit = options.get("limit", 5)
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("RSS limit must be 1 to 20")
        raw, _, received = self._fetch(RSS[source])
        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise ValueError("RSS entity declarations are forbidden")
        tree = ET.fromstring(raw)
        records = []
        for item in tree.findall(".//item")[:limit]:
            title, link, pub = item.findtext("title"), item.findtext("link"), item.findtext("pubDate")
            if not title or not link or not pub:
                continue
            host = "www.federalreserve.gov" if source == "federal-reserve" else "www.bea.gov"
            if urlsplit(link).scheme != "https" or urlsplit(link).hostname != host:
                raise ValueError("RSS article is outside its official source")
            dt = parsedate_to_datetime(pub)
            if dt.tzinfo is None:
                raise ValueError("RSS publication time lacks timezone")
            published = _iso(dt.timestamp())
            if dt.timestamp() > received / 1e9:
                raise ValueError("RSS release is future dated")
            data = {"title": title, "url": link, "published_at": published,
                    "description": item.findtext("description", "")[:4000]}
            records.append(self._record(source, "news", source, hashlib.sha256(link.encode()).hexdigest(),
                link, received, data, assets=assets, observed_at=published, published_at=published,
                text=title + "\n" + data["description"]))
        if not records:
            raise ValueError("RSS contains no dated source-backed articles")
        return records, {"feed": RSS[source], "publication_timestamp_known": True}

    @staticmethod
    def _cik(value):
        if type(value) not in (str, int) or not re.fullmatch(r"[0-9]{1,10}", str(value)) or int(value) <= 0:
            raise ValueError("SEC requires a numeric CIK of at most ten digits")
        return str(value).zfill(10)

    def _sec(self, options):
        self._options(options, ("cik", "assets"))
        cik = self._cik(options.get("cik"))
        identity = os.environ.get("SEC_USER_AGENT", "")
        if len(identity) > 200 or not re.search(r"[^\s@]+@[^\s@]+\.[^\s@]+", identity) or any(c in identity for c in "\r\n"):
            raise ValueError("SEC_USER_AGENT must contain your real organization/contact email")
        assets = self._assets(options) if "assets" in options else []
        urls = [f"https://data.sec.gov/submissions/CIK{cik}.json",
                f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"]
        raw, _, received_submissions = self._fetch(urls[0], {"User-Agent": identity})
        submissions = json.loads(raw)
        raw, _, received_facts = self._fetch(urls[1], {"User-Agent": identity})
        facts = json.loads(raw)
        if int(submissions["cik"]) != int(cik) or int(facts["cik"]) != int(cik):
            raise ValueError("SEC response CIK mismatch")
        recent = submissions.get("filings", {}).get("recent", {})
        filings = [{key: recent[key][i] for key in ("accessionNumber", "filingDate", "reportDate", "form", "primaryDocument") if key in recent}
                   for i in range(min(10, len(recent.get("accessionNumber", []))))]
        records = [self._record("sec", "company", "CIK" + cik, "CIK" + cik + ":submissions", urls[0], received_submissions,
            {"cik": cik, "name": submissions["name"], "tickers": submissions.get("tickers", []),
             "sic": submissions.get("sic"), "sic_description": submissions.get("sicDescription"), "filings": filings})]
        metrics = facts.get("facts", {}).get("us-gaap", {})
        for tag in ("Assets", "Liabilities", "StockholdersEquity", "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                    "NetIncomeLoss", "OperatingIncomeLoss", "CashAndCashEquivalentsAtCarryingValue"):
            for unit, entries in metrics.get(tag, {}).get("units", {}).items():
                valid = [entry for entry in entries if entry.get("filed") and entry.get("end")]
                if not valid:
                    continue
                entry = max(valid, key=lambda row: (row["filed"], row["end"], row.get("start", "")))
                values = {tag: _number(entry["val"])}
                records.append(self._record("sec", "company", "CIK" + cik, f"CIK{cik}:{tag}:{unit}:{entry['end']}",
                    urls[1], received_facts, {"cik": cik, "name": facts.get("entityName"), "taxonomy": "us-gaap",
                    "tag": tag, "unit": unit, "fact": entry}, assets=assets,
                    observed_at=entry["end"] + "T00:00:00.000000Z", values=values, units={tag: unit},
                    report_family="sec-companyfacts", text="SEC filing date retained as a date; exact publication time is unknown."))
        return records, {"cik": cik, "name": submissions["name"], "source_urls": urls,
                         "publication_timestamp_known": False}

    def _coinbase(self, options):
        self._options(options, ("limit", "max_pages", "seconds"))
        limit, pages, seconds = options.get("limit", 1000), options.get("max_pages", 5), options.get("seconds", 1)
        if (type(limit) is not int or not 1 <= limit <= 1000 or type(pages) is not int or not 1 <= pages <= 10
                or type(seconds) is not int or not 1 <= seconds <= 3600):
            raise ValueError("invalid bounded Coinbase pagination or seconds")
        with self._db() as con:
            row = con.execute("SELECT body FROM trade_stream WHERE instrument='BTC-USD'").fetchone()
            state = json.loads(row[0]) if row else None
        if state and state["seconds"] != seconds:
            raise ValueError("seconds cannot change within a persisted trade stream")
        last_id = state["last_event"]["sequence"] if state else None
        fetched, cursor, batch_received = {}, None, 0
        for _ in range(pages):
            query = {"limit": limit}
            if cursor is not None:
                query["after"] = cursor
            url = "https://api.exchange.coinbase.com/products/BTC-USD/trades?" + urlencode(query)
            raw, headers, received = self._fetch(url)
            rows = json.loads(raw)
            if type(rows) is not list or not rows:
                raise ValueError("Coinbase returned no trades")
            batch_received = max(batch_received, received)
            for trade in rows:
                if type(trade.get("trade_id")) is not int or trade["trade_id"] < 0:
                    raise ValueError("invalid Coinbase trade id")
                old = fetched.get(trade["trade_id"])
                if old and old["trade"] != trade:
                    raise ValueError("conflicting Coinbase trade id")
                fetched.setdefault(trade["trade_id"], {"trade": trade, "received_ns": received, "source_url": url})
            if last_id is None or min(fetched) <= last_id:
                break
            next_cursor = headers.get("cb-after")
            if not next_cursor or not re.fullmatch(r"[0-9]+", next_cursor) or next_cursor == cursor:
                break
            cursor = next_cursor
        agg = TradeAggregator("coinbase-exchange", "BTC-USD", seconds=seconds, contiguous_sequence=True)
        if state:
            agg.last = TradeEvent(**state["last_event"])
            agg.bucket = state["active_bucket"]
            agg.watermark = state["watermark_ns"]
            agg.received_watermark = state["received_watermark_ns"]
        completed, new_trades = [], []
        with self._db() as con:
            # Every immutable record retains its real response receipt. A common
            # batch availability watermark permits chronological replay of pages
            # retrieved newest-first, without inventing earlier availability.
            for trade_id in sorted(fetched):
                item = fetched[trade_id]
                prior = con.execute("SELECT body FROM source_trades WHERE trade_id=?", (trade_id,)).fetchone()
                if prior and json.loads(prior[0])["trade"] != item["trade"]:
                    raise ValueError("conflicting persisted Coinbase trade id")
                if last_id is not None and trade_id <= last_id:
                    continue
                trade = item["trade"]
                price = Decimal(trade["price"]) / Decimal("0.01")
                if not price.is_finite() or price != price.to_integral_value() or trade["side"] not in ("buy", "sell"):
                    raise ValueError("Coinbase trade has invalid tick price or maker side")
                # ISO timestamps have microsecond precision; avoid float seconds.
                dt = datetime.fromisoformat(trade["time"].replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    raise ValueError("Coinbase event timestamp lacks timezone")
                epoch_delta = dt.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
                event_ns = (epoch_delta.days * 86400 + epoch_delta.seconds) * 10**9 + epoch_delta.microseconds * 1000
                if event_ns > item["received_ns"]:
                    raise ValueError("Coinbase event follows its actual response receipt")
                event = TradeEvent("coinbase-exchange", "BTC-USD", trade_id, event_ns,
                                   max(batch_received, agg.received_watermark), int(price), _number(trade["size"]),
                                   "sell" if trade["side"] == "buy" else "buy")
                completed.extend(agg.push(event))
                normalized = {**item, "event": asdict(event), "aggregation_available_at_ns": event.received_ns,
                              "event_time_ns": event_ns, "price_increment": "0.01", "authentic_trade_events": True}
                con.execute("INSERT OR IGNORE INTO source_trades VALUES (?,?,?)", (trade_id, _json(normalized), item["received_ns"]))
                new_trades.append(normalized)
            if agg.last is None:
                raise ValueError("Coinbase stream has no normalized trades")
            bars = ((state or {}).get("completed_bars", []) + completed)[-1000:]
            updated = {"instrument": "BTC-USD", "venue": "coinbase-exchange", "seconds": seconds,
                       "last_event": asdict(agg.last), "active_bucket": agg.bucket,
                       "watermark_ns": agg.watermark, "received_watermark_ns": agg.received_watermark,
                       "completed_bars": bars, "active_bucket_is_partial": agg.bucket is not None,
                       "sequence_continuity_checked": True, "sequence_field": "per-product REST trade_id",
                       "last_success_received_ns": batch_received, "price_increment": "0.01"}
            con.execute("INSERT INTO trade_stream VALUES ('BTC-USD',?) ON CONFLICT(instrument) DO UPDATE SET body=excluded.body", (_json(updated),))
        return [], {"instrument": "BTC-USD", "trades_ingested": len(new_trades), "completed_bars": len(completed),
                    "active_bucket_is_partial": True, "sequence_gap": False, "price_increment": "0.01",
                    "source": "authentic public Coinbase Exchange trades; spot BTC only"}
