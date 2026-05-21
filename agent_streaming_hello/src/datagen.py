"""Simple background pageviews data generator."""

from __future__ import annotations

import json
import random
import threading
import time
import uuid
from dataclasses import dataclass

from kafka import KafkaProducer

from .config import AppConfig
from .constants import DEFAULT_PAGES, TOPIC_PAGEVIEWS


@dataclass
class DatagenStats:
    sent_events: int = 0
    last_error: str | None = None


class PageviewDataGenerator:
    def __init__(self, config: AppConfig, events_per_second: float = 5.0) -> None:
        self._config = config
        self._eps = max(events_per_second, 0.2)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.stats = DatagenStats()

    def _producer(self) -> KafkaProducer:
        return KafkaProducer(
            bootstrap_servers=self._config.bootstrap_servers(),
            security_protocol="SASL_SSL",
            sasl_mechanism="PLAIN",
            sasl_plain_username=self._config.kafka_username,
            sasl_plain_password=self._config.kafka_password.get_secret_value(),
            value_serializer=lambda payload: json.dumps(payload).encode("utf-8"),
            linger_ms=10,
        )

    def _one_event(self) -> dict[str, str | int]:
        return {
            "event_ts": int(time.time() * 1000),
            "user_id": f"user_{random.randint(1, 40)}",
            "session_id": str(uuid.uuid4()),
            "page": random.choice(DEFAULT_PAGES),
        }

    def _run_loop(self) -> None:
        interval = 1.0 / self._eps
        producer: KafkaProducer | None = None
        try:
            producer = self._producer()
            while not self._stop_event.is_set():
                event = self._one_event()
                producer.send(TOPIC_PAGEVIEWS, value=event)
                self.stats.sent_events += 1
                time.sleep(interval)
        except Exception as exc:  # noqa: BLE001
            self.stats.last_error = f"{type(exc).__name__}: {exc}"
        finally:
            if producer is not None:
                producer.flush(timeout=5)
                producer.close(timeout=3)

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def reset_stats(self) -> None:
        self.stats = DatagenStats()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
