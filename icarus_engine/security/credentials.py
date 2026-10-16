from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


_DEFAULT_CONTRACT = Path(__file__).resolve().parents[2] / "config" / "credential_contract.json"


@dataclass(frozen=True)
class CredentialSpec:
    canonical: str
    aliases: tuple[str, ...]
    provider: str


@dataclass(frozen=True)
class CredentialStatus:
    canonical_name: str
    present: bool
    matched_alias: str | None

    def as_dict(self) -> dict[str, str | bool | None]:
        return {
            "canonical_name": self.canonical_name,
            "present": self.present,
            "matched_alias": self.matched_alias,
        }


def load_contract(path: Path | None = None) -> dict[str, CredentialSpec]:
    contract_path = path or _DEFAULT_CONTRACT
    raw = json.loads(contract_path.read_text(encoding="utf-8"))
    specs: dict[str, CredentialSpec] = {}
    for item in raw["credentials"]:
        spec = CredentialSpec(
            canonical=str(item["canonical"]),
            aliases=tuple(str(alias) for alias in item["aliases"]),
            provider=str(item["provider"]),
        )
        if not spec.canonical or spec.canonical in specs:
            raise ValueError(f"invalid or duplicate canonical credential: {spec.canonical!r}")
        if spec.canonical not in spec.aliases:
            raise ValueError(f"canonical credential missing from aliases: {spec.canonical}")
        if len(spec.aliases) != len(set(spec.aliases)):
            raise ValueError(f"duplicate aliases for credential: {spec.canonical}")
        specs[spec.canonical] = spec
    return specs


def _spec_for(name: str) -> CredentialSpec:
    contract = load_contract()
    try:
        return contract[name]
    except KeyError as exc:
        raise KeyError(name) from exc


def _nonempty(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.strip():
        return None
    return value


def credential_status(
    name: str,
    env: Mapping[str, str] | None = None,
) -> CredentialStatus:
    source = os.environ if env is None else env
    spec = _spec_for(name)
    for alias in spec.aliases:
        if _nonempty(source.get(alias)) is not None:
            return CredentialStatus(
                canonical_name=spec.canonical,
                present=True,
                matched_alias=alias,
            )
    return CredentialStatus(
        canonical_name=spec.canonical,
        present=False,
        matched_alias=None,
    )


def resolve_credential(
    name: str,
    env: Mapping[str, str] | None = None,
) -> str | None:
    source = os.environ if env is None else env
    spec = _spec_for(name)
    for alias in spec.aliases:
        value = _nonempty(source.get(alias))
        if value is not None:
            return value
    return None
