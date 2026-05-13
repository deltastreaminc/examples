from __future__ import annotations

import re


PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input_per_mtok": 3.0,
        "output_per_mtok": 15.0,
        "cache_write_per_mtok": 3.75,
        "cache_read_per_mtok": 0.30,
    },
    "claude-sonnet-4-5": {
        "input_per_mtok": 3.0,
        "output_per_mtok": 15.0,
        "cache_write_per_mtok": 3.75,
        "cache_read_per_mtok": 0.30,
    },
    "claude-haiku-4-6": {
        "input_per_mtok": 1.0,
        "output_per_mtok": 5.0,
        "cache_write_per_mtok": 1.25,
        "cache_read_per_mtok": 0.10,
    },
    "claude-haiku-4-5": {
        "input_per_mtok": 1.0,
        "output_per_mtok": 5.0,
        "cache_write_per_mtok": 1.25,
        "cache_read_per_mtok": 0.10,
    },
}


_DATE_SUFFIX_RE = re.compile(r"-\d{8}$")


def _lookup_rates(model: str) -> dict[str, float] | None:
    rates = PRICING.get(model)
    if rates is not None:
        return rates
    # Strip a trailing -YYYYMMDD version suffix (e.g. claude-sonnet-4-5-20260929).
    stripped = _DATE_SUFFIX_RE.sub("", model)
    if stripped != model:
        rates = PRICING.get(stripped)
        if rates is not None:
            return rates
    # Fall back to longest matching prefix key (handles future suffixes).
    candidates = [k for k in PRICING if model.startswith(k)]
    if candidates:
        best = max(candidates, key=len)
        return PRICING[best]
    return None


def cost_usd(model: str, usage: dict[str, int]) -> float | None:
    rates = _lookup_rates(model)
    if rates is None:
        return None
    return (
        int(usage.get("input_tokens", 0)) * rates["input_per_mtok"]
        + int(usage.get("output_tokens", 0)) * rates["output_per_mtok"]
        + int(usage.get("cache_creation_input_tokens", 0)) * rates["cache_write_per_mtok"]
        + int(usage.get("cache_read_input_tokens", 0)) * rates["cache_read_per_mtok"]
    ) / 1_000_000.0
