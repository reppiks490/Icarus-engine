import gzip
import hashlib
import json
from pathlib import Path

from cl_lab.data_fabric.streaming import RawCaptureSocket, StreamBatchWriter, run_uw_stream_capture


def _unframe(data: bytes):
    out = []
    i = 0
    while i < len(data):
        n = int.from_bytes(data[i:i+8], "big")
        i += 8
        out.append(data[i:i+n])
        i += n
    return out


def test_raw_capture_socket_excludes_join_ack_but_preserves_data_bytes():
    class Sock:
        def __init__(self):
            self.values = iter([
                json.dumps({"status": "ok", "channel": "market_tide"}),
                '{"channel":"market_tide","value":1}',
                "not-json",
            ])
        def send(self, value):
            self.sent = value
        def recv(self):
            return next(self.values)
        def close(self):
            pass

    raw = []
    valid = []
    sock = RawCaptureSocket(Sock(), on_raw=raw.append, on_valid_raw=valid.append)
    sock.send("join")
    assert json.loads(sock.recv())["status"] == "ok"
    assert sock.recv().endswith("}")
    assert sock.recv() == "not-json"
    assert raw == [b'{"channel":"market_tide","value":1}', b"not-json"]
    assert valid == [b'{"channel":"market_tide","value":1}']


def test_stream_batch_writer_persists_exact_bronze_and_point_in_time_silver(tmp_path, monkeypatch):
    monkeypatch.setenv("ICARUS_DATA_FABRIC_FORCE_JSONL", "1")
    writer = StreamBatchWriter(tmp_path, retrieval_time="2026-10-06T20:00:00Z")
    raw = b'{"channel":"market_tide","time":"2026-10-06T19:59:59Z","value":1}'
    malformed = b"not-json"
    writer.capture_raw(raw)
    writer.capture_valid_raw(raw)
    writer.capture_raw(malformed)
    writer.flush_parsed([{"channel":"market_tide","time":"2026-10-06T19:59:59Z","value":1}])
    writer.finalize()

    bronze = list((tmp_path / "bronze" / "unusual_whales" / "websocket_raw").rglob("*.gz"))
    assert len(bronze) == 1
    assert _unframe(gzip.decompress(bronze[0].read_bytes())) == [raw, malformed]

    silver = list((tmp_path / "silver" / "unusual_whales" / "ws_market_tide").rglob("*.jsonl.gz"))
    assert len(silver) == 1
    row = json.loads(gzip.decompress(silver[0].read_bytes()).decode().strip())
    assert row["payload"]["value"] == 1
    assert row["raw_content_hash"] == hashlib.sha256(raw).hexdigest()
    assert row["availability_time"] == "2026-10-06T20:00:00Z"


def test_bounded_stream_capture_uses_injected_socket_and_never_persists_token(tmp_path, monkeypatch):
    monkeypatch.setenv("ICARUS_DATA_FABRIC_FORCE_JSONL", "1")

    class Sock:
        def __init__(self):
            self.values = iter([
                json.dumps({"status": "ok", "channel": "market_tide"}),
                json.dumps({"channel": "market_tide", "timestamp": "2026-10-06T20:00:00Z", "value": 1}),
            ])
        def send(self, value):
            pass
        def recv(self):
            return next(self.values)
        def close(self):
            pass

    result = run_uw_stream_capture(
        api_token="super-secret-token",
        channels=["market_tide"],
        output_root=tmp_path,
        max_messages=1,
        max_seconds=30,
        socket_factory=lambda: Sock(),
        now="2026-10-06T20:00:01Z",
    )
    assert result["status"] == "ok"
    assert result["summary"]["messages"] == 1
    text = (tmp_path / "manifests" / "uw_stream_latest.json").read_text()
    assert "super-secret-token" not in text
    assert "market_tide" in text
