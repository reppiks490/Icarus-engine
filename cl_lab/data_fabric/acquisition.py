from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import os
from typing import Any, Callable, Iterable, Mapping

from .contracts import Observation, redact_text
from .storage import write_bronze, write_silver


class ProviderHttpError(RuntimeError):
    pass


@dataclass
class AcquisitionBudget:
    max_calls: int
    calls: int = 0

    def can_call(self) -> bool:
        return self.calls < max(0, int(self.max_calls))

    def consume(self) -> None:
        if not self.can_call():
            raise RuntimeError("acquisition call budget exhausted")
        self.calls += 1


def _default_requester(url: str, headers: Mapping[str, str], params: Mapping[str, Any] | None):
    import urllib.error
    import urllib.parse
    import urllib.request

    query = urllib.parse.urlencode(dict(params or {}), doseq=True)
    full = url + (("?" + query) if query else "")
    request = urllib.request.Request(
        full,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "icarus-external-acquisition/1", **dict(headers)},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return int(response.status), dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), dict(exc.headers.items()), exc.read()


def _atomic_json(path: str | Path, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False, default=str) + "\n").encode()
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    preferred = (
        "data", "results", "trades", "chains", "holdings", "institutions", "earnings",
        "analysts", "ratings", "owners", "filings", "securities", "companies", "options",
        "transactions", "events", "records",
    )
    for key in preferred:
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return [payload]


def _normalize_time(value: Any) -> tuple[str | None, bool]:
    """Return (UTC ISO, has_explicit_time_precision)."""
    if value in (None, ""):
        return None, False
    if isinstance(value, (int, float)):
        number = float(value)
        seconds = number / 1000.0 if abs(number) > 10**11 else number
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat().replace("+00:00", "Z"), True
    text = str(value).strip()
    date_only = len(text) == 10 and text[4] == "-" and text[7] == "-"
    if date_only:
        dt = datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z"), False
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None, False
    if dt.tzinfo is None:
        # Timestamp without zone is descriptive only; normalize for storage but do not
        # treat it as a safe causal availability timestamp.
        return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"), False
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), True


def source_times(record: Mapping[str, Any], retrieval_time: str) -> tuple[str | None, str | None, str]:
    event = None
    for key in (
        "executed_at", "transaction_date", "timestamp", "time", "date", "market_date",
        "report_date", "fiscal_date_ending", "event_time",
    ):
        if key in record and record.get(key) not in (None, ""):
            event, _ = _normalize_time(record.get(key))
            if event:
                break

    publication = None
    publication_has_time = False
    for key in (
        "published_at", "reported_at", "disclosure_date", "filed_at", "filing_date",
        "accepted_at", "acceptance_datetime", "publication_time",
    ):
        if key in record and record.get(key) not in (None, ""):
            publication, publication_has_time = _normalize_time(record.get(key))
            if publication:
                break

    # Conservative anti-lookahead rule: only a publication timestamp with explicit
    # clock+timezone may become availability. A date-only publication value is not
    # enough to claim the record was observable at midnight.
    availability = publication if publication and publication_has_time else retrieval_time
    return event, publication, availability


def _entity(record: Mapping[str, Any]) -> str | None:
    for key in ("ticker", "symbol", "pair", "security", "identifier", "company"):
        value = record.get(key)
        if value not in (None, "") and not isinstance(value, (dict, list)):
            return str(value)
    return None


def _status_error(provider: str, status: int, body: bytes, secrets: Iterable[str]) -> ProviderHttpError:
    preview = body[:300].decode("utf-8", "replace")
    return ProviderHttpError(redact_text(f"{provider} HTTP {status}: {preview}", secrets))


def collect_json_pages(
    *,
    provider: str,
    dataset: str,
    endpoint: str,
    url: str,
    headers: Mapping[str, str],
    params: Mapping[str, Any] | None,
    pagination: str,
    output_root: str | Path,
    requester: Callable[..., tuple[int, Mapping[str, str], bytes]] = _default_requester,
    budget: AcquisitionBudget,
    retrieval_time: str,
    license_class: str = "provider-restricted",
    checkpoint_path: str | Path | None = None,
    secrets: Iterable[str] = (),
    max_pages: int = 1000,
) -> dict[str, Any]:
    base_params = dict(params or {})
    cursor = None
    page = int(base_params.pop("page", 0) or 0)
    offset = int(base_params.pop("offset", 0) or 0)
    if checkpoint_path and Path(checkpoint_path).exists():
        try:
            cp = json.loads(Path(checkpoint_path).read_text())
            cursor = cp.get("next_cursor")
            page = int(cp.get("next_page_index", page))
            offset = int(cp.get("next_offset", offset))
        except Exception:
            pass

    calls = records_total = 0
    complete = False
    last_cursor = cursor
    next_page_index = page
    next_offset = offset

    for _ in range(max_pages):
        if not budget.can_call():
            break
        request_params = dict(base_params)
        if pagination == "next_page" and cursor:
            request_params["next_page"] = cursor
        elif pagination == "page":
            request_params["page"] = page
        elif pagination == "offset":
            request_params["offset"] = offset

        budget.consume()
        calls += 1
        status, response_headers, body = requester(url, headers, request_params)
        if not 200 <= int(status) < 300:
            raise _status_error(provider, int(status), body, secrets)

        write_bronze(output_root, provider, dataset, body, retrieval_time)
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception as exc:
            raise ProviderHttpError(f"{provider} returned invalid JSON for {dataset}") from exc
        records = extract_records(payload)
        records_total += len(records)
        normalized = []
        for record in records:
            event_time, publication_time, availability_time = source_times(record, retrieval_time)
            obs = Observation.build(
                provider=provider,
                dataset=dataset,
                endpoint=endpoint,
                entity=_entity(record),
                event_time=event_time,
                publication_time=publication_time,
                availability_time=availability_time,
                retrieval_time=retrieval_time,
                revision=None,
                latency_class="historical_api",
                quality_state="raw_normalized",
                license_class=license_class,
                payload=record,
                raw_bytes=body,
            )
            normalized.append(obs.as_dict())
        if normalized:
            partition_time = normalized[0].get("event_time") or retrieval_time
            write_silver(output_root, provider, dataset, normalized, partition_time)

        if pagination == "next_page":
            nxt = payload.get("next_page") if isinstance(payload, dict) else None
            last_cursor = None if not nxt else str(nxt)
            if not nxt:
                complete = True
                break
            cursor = str(nxt)
        elif pagination == "page":
            if not records:
                complete = True
                break
            page += 1
            next_page_index = page
        elif pagination == "offset":
            if not records:
                complete = True
                break
            step = int(request_params.get("limit") or len(records) or 1)
            offset += step
            next_offset = offset
        else:
            complete = True
            break

    checkpoint = {
        "provider": provider,
        "dataset": dataset,
        "endpoint": endpoint,
        "next_cursor": last_cursor,
        "next_page_index": next_page_index,
        "next_offset": next_offset,
        "complete": complete,
        "calls": calls,
        "records": records_total,
        "retrieval_time": retrieval_time,
    }
    if checkpoint_path:
        _atomic_json(checkpoint_path, checkpoint)
    return checkpoint


def _parse_date(value: str | date) -> date:
    return value if isinstance(value, date) and not isinstance(value, datetime) else date.fromisoformat(str(value)[:10])


def download_binary_dates(
    *,
    provider: str,
    dataset: str,
    url_template: str,
    headers: Mapping[str, str],
    start_date: str | date,
    end_date: str | date,
    output_root: str | Path,
    requester: Callable[..., tuple[int, Mapping[str, str], bytes]] = _default_requester,
    budget: AcquisitionBudget,
    retrieval_time: str,
    secrets: Iterable[str] = (),
) -> dict[str, Any]:
    day = _parse_date(start_date)
    end = _parse_date(end_date)
    dates: list[str] = []
    calls = 0
    while day <= end and budget.can_call():
        if day.weekday() < 5:
            ds = day.isoformat()
            budget.consume()
            calls += 1
            status, response_headers, body = requester(url_template.format(date=ds), headers, {})
            if not 200 <= int(status) < 300:
                # Historical calendars include holidays; 404/422 are a skipped non-session,
                # while auth/entitlement/server failures must surface.
                if int(status) in (404, 422):
                    day += timedelta(days=1)
                    continue
                raise _status_error(provider, int(status), body, secrets)
            write_bronze(output_root, provider, dataset, body, retrieval_time)
            dates.append(ds)
        day += timedelta(days=1)
    return {"provider": provider, "dataset": dataset, "calls": calls, "dates": dates, "complete": day > end}
