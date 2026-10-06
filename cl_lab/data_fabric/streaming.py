from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote

from .acquisition import source_times
from .contracts import Observation
from .storage import write_bronze, write_manifest, write_silver
from cl_lab.providers.unusual_whales import BufferedStreamCollector, WEBSOCKET_URL


def _utc_iso(value: Any = None) -> str:
    if value is None:
        dt = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("stream timestamp must include timezone")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _raw_bytes(raw: Any) -> bytes:
    if isinstance(raw, bytes):
        return raw
    if isinstance(raw, str):
        return raw.encode("utf-8")
    return json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _channel_name(value: Any) -> str:
    text = str(value or "unknown")
    safe = "".join(ch if ch.isalnum() else "_" for ch in text).strip("_")
    return safe or "unknown"


def _entity(record: dict[str, Any]) -> str | None:
    for key in ("ticker", "symbol", "pair", "security", "identifier"):
        value = record.get(key)
        if value not in (None, "") and not isinstance(value, (dict, list)):
            return str(value)
    return None


class RawCaptureSocket:
    """Socket proxy that preserves exact non-handshake message bytes.

    `BufferedStreamCollector` performs the provider join handshake synchronously: each
    send is immediately followed by one acknowledgement recv. We use that invariant to
    exclude handshake frames from Bronze while retaining every subsequent wire message,
    including malformed payloads that the parser rejects.
    """

    def __init__(
        self,
        socket: Any,
        *,
        on_raw: Callable[[bytes], None],
        on_valid_raw: Callable[[bytes], None],
    ):
        self.socket = socket
        self.on_raw = on_raw
        self.on_valid_raw = on_valid_raw
        self.pending_acks = 0

    def send(self, value: Any):
        self.pending_acks += 1
        return self.socket.send(value)

    def recv(self):
        raw = self.socket.recv()
        if self.pending_acks:
            self.pending_acks -= 1
            return raw
        data = _raw_bytes(raw)
        self.on_raw(data)
        try:
            item = json.loads(data.decode("utf-8"))
        except Exception:
            return raw
        if isinstance(item, dict) and not ("status" in item and len(item) <= 3):
            self.on_valid_raw(data)
        return raw

    def close(self):
        return self.socket.close()


class StreamBatchWriter:
    """Batch exact websocket bytes to Bronze and normalized observations to Silver."""

    def __init__(self, output_root: str | Path, *, retrieval_time: str):
        self.output_root = Path(output_root)
        self.retrieval_time = _utc_iso(retrieval_time)
        self.raw_messages: list[bytes] = []
        self.valid_raw: deque[bytes] = deque()
        self.raw_batches = 0
        self.silver_rows = 0

    def capture_raw(self, raw: bytes) -> None:
        self.raw_messages.append(bytes(raw))

    def capture_valid_raw(self, raw: bytes) -> None:
        self.valid_raw.append(bytes(raw))

    def _flush_raw(self) -> None:
        if not self.raw_messages:
            return
        framed = b"".join(len(raw).to_bytes(8, "big") + raw for raw in self.raw_messages)
        write_bronze(
            self.output_root,
            "unusual_whales",
            "websocket_raw",
            framed,
            self.retrieval_time,
        )
        self.raw_batches += 1
        self.raw_messages.clear()

    def flush_parsed(self, batch: list[dict[str, Any]]) -> None:
        groups: dict[str, list[dict[str, Any]]] = {}
        group_times: dict[str, str] = {}
        for item in batch:
            raw = self.valid_raw.popleft() if self.valid_raw else json.dumps(
                item, sort_keys=True, separators=(",", ":"), default=str
            ).encode("utf-8")
            event_time, publication_time, availability_time = source_times(item, self.retrieval_time)
            channel = str(item.get("channel") or "unknown")
            dataset = f"ws_{_channel_name(channel)}"
            obs = Observation.build(
                provider="unusual_whales",
                dataset=dataset,
                endpoint=f"websocket:{channel}",
                entity=_entity(item),
                event_time=event_time,
                publication_time=publication_time,
                availability_time=availability_time,
                retrieval_time=self.retrieval_time,
                revision=None,
                latency_class="live_stream",
                quality_state="raw_normalized",
                license_class="provider-restricted",
                payload=item,
                raw_bytes=raw,
            ).as_dict()
            groups.setdefault(dataset, []).append(obs)
            group_times.setdefault(dataset, event_time or self.retrieval_time)
            self.silver_rows += 1
        for dataset, rows in groups.items():
            write_silver(
                self.output_root,
                "unusual_whales",
                dataset,
                rows,
                group_times[dataset],
            )
        self._flush_raw()

    def finalize(self) -> None:
        self._flush_raw()


def _production_socket_factory(api_token: str) -> Callable[[], Any]:
    token = quote(api_token, safe="")
    url = WEBSOCKET_URL.format(token=token)

    def factory():
        import websocket  # type: ignore

        return websocket.create_connection(url, timeout=30)

    return factory


def run_uw_stream_capture(
    *,
    api_token: str,
    channels: Iterable[str],
    output_root: str | Path,
    max_messages: int | None = 10000,
    max_seconds: float | None = 900.0,
    socket_factory: Callable[[], Any] | None = None,
    buffer_size: int = 500,
    flush_interval_seconds: float = 10.0,
    max_reconnects: int = 5,
    now: Any = None,
) -> dict[str, Any]:
    secret = str(api_token or "").strip()
    if not secret:
        result = {
            "schema": "icarus.external_data_fabric.uw_stream/1",
            "generated_at": _utc_iso(now),
            "status": "unconfigured",
            "credential_env": "UNUSUAL_WHALES_API_TOKEN",
            "authority": "RESEARCH",
            "execution_authorized": False,
        }
        write_manifest(Path(output_root) / "manifests" / "uw_stream_latest.json", result)
        return result

    channel_tuple = tuple(dict.fromkeys(str(ch).strip() for ch in channels if str(ch).strip()))
    if not channel_tuple:
        raise ValueError("at least one websocket channel is required")
    retrieval_time = _utc_iso(now)
    writer = StreamBatchWriter(output_root, retrieval_time=retrieval_time)
    base_factory = socket_factory or _production_socket_factory(secret)

    def wrapped_factory():
        return RawCaptureSocket(
            base_factory(),
            on_raw=writer.capture_raw,
            on_valid_raw=writer.capture_valid_raw,
        )

    collector = BufferedStreamCollector(
        socket_factory=wrapped_factory,
        channels=channel_tuple,
        flush_callback=writer.flush_parsed,
        buffer_size=buffer_size,
        flush_interval_seconds=flush_interval_seconds,
        max_reconnects=max_reconnects,
        max_messages=max_messages,
        max_seconds=max_seconds,
    )
    try:
        summary = collector.run()
        status = "ok"
    finally:
        writer.finalize()

    result = {
        "schema": "icarus.external_data_fabric.uw_stream/1",
        "generated_at": retrieval_time,
        "status": status,
        "authority": "RESEARCH",
        "execution_authorized": False,
        "channels": list(channel_tuple),
        "bounds": {"max_messages": max_messages, "max_seconds": max_seconds},
        "summary": summary,
        "storage": {"raw_batches": writer.raw_batches, "silver_rows": writer.silver_rows},
    }
    write_manifest(Path(output_root) / "manifests" / "uw_stream_latest.json", result)
    return result
