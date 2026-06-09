from __future__ import annotations

import json
from pathlib import Path


class ScenarioState:
    def __init__(self, path: Path) -> None:
        self._path = path

    def next_scenario_seq(self) -> int:
        state = self._read_state()
        next_seq = int(state.get("next_scenario_seq", 1))
        state["next_scenario_seq"] = next_seq + 1
        self._write_state(state)
        return next_seq

    def _read_state(self) -> dict[str, int]:
        if not self._path.exists():
            return {"next_scenario_seq": 1}
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {"next_scenario_seq": 1}
        return {"next_scenario_seq": int(payload.get("next_scenario_seq", 1))}

    def _write_state(self, state: dict[str, int]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        temp_path.replace(self._path)
