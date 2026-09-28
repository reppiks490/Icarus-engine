"""Trade-event aggregation for independently licensed tick data.

This is an offline/adapter boundary, not a connected provider or a change to the
minute-based Pine emulator. No interpolation, guessed aggressors, or fake ticks.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class TradeEvent:
    venue: str
    instrument: str
    sequence: int
    event_ns: int
    received_ns: int
    price_ticks: int
    quantity: float
    aggressor: str = "unknown"

    def __post_init__(self):
        for name in ("venue", "instrument"):
            value = getattr(self, name)
            if not isinstance(value, str) or not 1 <= len(value) <= 64 or not all(c.isalnum() or c in "._:-" for c in value):
                raise ValueError(f"invalid {name}")
        for name in ("sequence", "event_ns", "received_ns", "price_ticks"):
            value = getattr(self, name)
            # Price can be negative (some futures have traded below zero).
            if type(value) is not int or (name != "price_ticks" and value < 0):
                raise ValueError(f"{name} must be an integer")
        if self.received_ns < self.event_ns:
            raise ValueError("receipt must not precede exchange event")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, (int, float)) or not math.isfinite(self.quantity) or self.quantity <= 0:
            raise ValueError("quantity must be positive and finite")
        if self.aggressor not in ("buy", "sell", "unknown"):
            raise ValueError("aggressor must be buy, sell, or unknown")


class TradeAggregator:
    """One ordered venue/instrument stream, with seconds and volume-at-price.

    Feed adapters must normalize corrections/cancels before these immutable trade
    events. `contiguous_sequence` is appropriate only for a per-instrument sequence;
    providers with a shared sequence should supply their own loss detector.
    """

    def __init__(self, venue: str, instrument: str, *, seconds=1, contiguous_sequence=True):
        if type(seconds) is not int or not 1 <= seconds <= 3600:
            raise ValueError("seconds must be an integer in [1, 3600]")
        if type(contiguous_sequence) is not bool:
            raise ValueError("contiguous_sequence must be Boolean")
        TradeEvent(venue, instrument, 0, 0, 0, 0, 1)
        self.venue, self.instrument = venue, instrument
        self.width = seconds * 1_000_000_000
        self.contiguous_sequence = contiguous_sequence
        self.last = None
        self.bucket = None
        self.watermark = -1
        self.received_watermark = -1
        self.gap = False

    def push(self, event: TradeEvent):
        """Return zero or one completed bars. The active bar is never emitted."""
        if event.venue != self.venue or event.instrument != self.instrument:
            raise ValueError("wrong venue/instrument")
        if self.gap:
            raise ValueError("sequence gap: obtain a provider replay before continuing")
        if self.last and event.sequence == self.last.sequence:
            if event == self.last:
                return []
            self.gap = True
            raise ValueError("conflicting duplicate sequence")
        if self.last and (event.sequence < self.last.sequence or event.event_ns < self.last.event_ns
                          or event.received_ns < self.last.received_ns):
            self.gap = True
            raise ValueError("out-of-order trade stream")
        if event.event_ns < self.watermark:
            raise ValueError("late trade before completed watermark")
        if self.last and self.contiguous_sequence and event.sequence != self.last.sequence + 1:
            self.gap = True
            raise ValueError("sequence gap: aggregation halted")
        emitted = self.advance(event.event_ns, event.received_ns)
        start = event.event_ns // self.width * self.width
        if self.bucket is None:
            self.bucket = {"venue": self.venue, "instrument": self.instrument, "start_ns": start,
                           "end_ns": start + self.width, "open_ticks": event.price_ticks,
                           "high_ticks": event.price_ticks, "low_ticks": event.price_ticks,
                           "close_ticks": event.price_ticks, "volume": 0.0, "trades": 0,
                           "footprint": {}, "first_sequence": event.sequence, "last_sequence": event.sequence,
                           "last_received_ns": event.received_ns, "authentic_trade_events": True}
        b = self.bucket
        b["high_ticks"] = max(b["high_ticks"], event.price_ticks)
        b["low_ticks"] = min(b["low_ticks"], event.price_ticks)
        b["close_ticks"] = event.price_ticks
        b["volume"] += event.quantity
        b["trades"] += 1
        b["last_sequence"] = event.sequence
        b["last_received_ns"] = event.received_ns
        level = b["footprint"].setdefault(str(event.price_ticks), {"buy": 0.0, "sell": 0.0, "unknown": 0.0})
        level[event.aggressor] += event.quantity
        self.last = event
        return emitted

    def advance(self, event_watermark_ns: int, received_ns: int):
        """Close bars only at a trusted provider watermark, never local wall time.

        At end of a file, leave the final bucket incomplete unless the dataset
        supplies a verified end watermark. Empty intervals are not fabricated.
        """
        if type(event_watermark_ns) is not int or type(received_ns) is not int:
            raise ValueError("watermark/receipt must be integer nanoseconds")
        if event_watermark_ns < self.watermark or received_ns < event_watermark_ns or received_ns < self.received_watermark:
            raise ValueError("invalid watermark/receipt ordering")
        if self.gap:
            raise ValueError("cannot complete a bucket across a sequence gap")
        self.watermark = event_watermark_ns
        self.received_watermark = received_ns
        if self.bucket and self.bucket["end_ns"] <= event_watermark_ns:
            bar, self.bucket = self.bucket, None
            bar["available_at_ns"] = max(received_ns, bar["last_received_ns"])
            bar["aggressor_complete"] = all(v["unknown"] == 0 for v in bar["footprint"].values())
            return [bar]
        return []

    def status(self):
        return {"venue": self.venue, "instrument": self.instrument, "seconds": self.width // 1_000_000_000,
                "last_event": asdict(self.last) if self.last else None, "sequence_gap": self.gap,
                "active_bucket_is_partial": self.bucket is not None, "provider_connected": False,
                "sequence_continuity_checked": self.contiguous_sequence}
