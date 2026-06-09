from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    return int(raw)


@dataclass(frozen=True)
class Config:
    kafka_bootstrap_servers: str
    loop_sleep_ms: int
    customer_count: int
    merchant_count: int
    scenario_seed_base: int
    state_file: Path
    create_topics: bool


def load_config() -> Config:
    return Config(
        kafka_bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        loop_sleep_ms=_env_int("LOOP_SLEEP_MS", 1500),
        customer_count=_env_int("CUSTOMER_COUNT", 500),
        merchant_count=_env_int("MERCHANT_COUNT", 50),
        scenario_seed_base=_env_int("SCENARIO_SEED_BASE", 10_000_000),
        state_file=Path(os.getenv("DEMO_STATE_FILE", ".stablecoin-payment-demo-state.json")),
        create_topics=os.getenv("CREATE_TOPICS", "true").strip().lower() in {"1", "true", "yes", "on"},
    )
