"""GitHub-native provider credential adapter.

This module resolves provider credentials through the canonical ICARUS
credential contract, then supplies only the legacy process-environment names
required by existing collectors. It never prints or serializes credential
values.
"""
from __future__ import annotations

import argparse
import os
from collections.abc import Mapping
from typing import Final

from icarus_engine.security.credentials import resolve_credential


# provider -> (primary canonical credential, secondary canonical credential,
#              legacy primary process names, legacy secondary process names)
_PROVIDER_BINDINGS: Final[dict[str, tuple[str | None, str | None, tuple[str, ...], tuple[str, ...]]]] = {
    "massive": ("MASSIVE_API_KEY", None, ("MASSIVE_API_KEY", "POLYGON_API_KEY"), ()),
    "twelve": (
        "TWELVEDATA_API_KEY",
        None,
        ("TWELVEDATA_API_KEY", "TWELVE_DATA_API_KEY", "TWELVE_API_KEY"),
        (),
    ),
    "fmp": ("FMP_API_KEY", None, ("FMP_API_KEY",), ()),
    "eodhd": ("EODHD_API_TOKEN", None, ("EODHD_API_TOKEN", "EODHD_API_KEY"), ()),
    "tiingo": ("TIINGO_API_TOKEN", None, ("TIINGO_API_TOKEN", "TIINGO_API_KEY"), ()),
    "intrinio": (
        "INTRINIO_API_KEY",
        None,
        ("INTRINIO_API_KEY", "INTRINIO_API_TOKEN"),
        (),
    ),
    "quiver": (
        "QUIVER_API_KEY",
        None,
        ("QUIVER_API_KEY", "QUIVER_API_TOKEN", "QUIVER_QUANT_API_KEY"),
        (),
    ),
    "fred": ("FRED_API_KEY", None, ("FRED_API_KEY",), ()),
    "alpaca": (
        "ALPACA_API_KEY",
        "ALPACA_API_SECRET",
        ("ALPACA_API_KEY",),
        ("ALPACA_API_SECRET", "ALPACA_SECRET_KEY"),
    ),
    "tickstream": (
        "TICKSTREAM_API_KEY",
        None,
        ("TICKSTREAM_API_KEY", "TICK_STREAM_API_KEY"),
        (),
    ),
    "alphavantage": ("ALPHAVANTAGE_API_KEY", None, ("ALPHAVANTAGE_API_KEY",), ()),
    "finnhub": ("FINNHUB_API_KEY", None, ("FINNHUB_API_KEY",), ()),
    "unusual_whales": ("UNUSUAL_WHALES_API_KEY", None, ("UNUSUAL_WHALES_API_KEY",), ()),
    "bybit": (None, None, (), ()),
}


def _binding(provider: str) -> tuple[str | None, str | None, tuple[str, ...], tuple[str, ...]]:
    try:
        return _PROVIDER_BINDINGS[provider]
    except KeyError as exc:
        raise KeyError(f"UNKNOWN_PROVIDER:{provider}") from exc


def provider_credential(provider: str, env: Mapping[str, str] | None = None) -> str:
    """Return the provider's primary credential without exposing it in metadata."""
    primary, _, _, _ = _binding(provider)
    if primary is None:
        return ""
    return (resolve_credential(primary, env) or "").strip()


def provider_secondary_credential(provider: str, env: Mapping[str, str] | None = None) -> str:
    """Return a secondary provider credential (for example Alpaca secret)."""
    _, secondary, _, _ = _binding(provider)
    if secondary is None:
        return ""
    return (resolve_credential(secondary, env) or "").strip()


def normalized_provider_environment(
    provider: str,
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a child-process environment with canonical + compatibility names.

    Values are copied in memory only. This function performs no logging and
    does not persist the resulting environment.
    """
    source = os.environ if env is None else env
    out = dict(source)
    primary, secondary, primary_names, secondary_names = _binding(provider)

    if primary is not None:
        value = provider_credential(provider, source)
        if value:
            out[primary] = value
            for name in primary_names:
                out[name] = value

    if secondary is not None:
        value = provider_secondary_credential(provider, source)
        if value:
            out[secondary] = value
            for name in secondary_names:
                out[name] = value

    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Execute a provider collector with canonical GitHub-native credentials."
    )
    parser.add_argument("--provider", required=True, choices=sorted(_PROVIDER_BINDINGS))
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a command is required after --")

    # Replace the process rather than spawning a shell so secrets are not
    # interpolated into command text or emitted by shell tracing.
    os.execvpe(command[0], command, normalized_provider_environment(args.provider))


if __name__ == "__main__":
    main()
