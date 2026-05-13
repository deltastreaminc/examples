#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from shared import bench_core as bc


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmark"
OUT_DIR = BENCH / "out"


def _load_candidates() -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]], dict[str, Any]]:
    answer = json.loads((BENCH / "answer_key_candidates.json").read_text())
    prompts = []
    by_id: dict[int, dict[str, Any]] = {}
    for p in answer["prompts"]:
        prompts.append(
            {
                "prompt_id": p["prompt_id"],
                "title": p["title"],
                "text": p["text"],
                "kind": p["kind"],
                "top_k": p["top_k"],
            }
        )
        by_id[int(p["prompt_id"])] = p
    return prompts, by_id, answer


def _augment_prompt_with_windows(prompt: str, dataset_meta: dict[str, Any]) -> str:
    windows = dataset_meta.get("windows", {})
    anchor = dataset_meta.get("anchor_ts_utc")
    return (
        f"{prompt}\n"
        f"Use these fixed benchmark windows: anchor_ts={anchor}, "
        f"last_24h_start={windows.get('last_24h_start')}, "
        f"last_7d_start={windows.get('last_7d_start')}, "
        f"prev_7d_start={windows.get('prev_7d_start')}, "
        f"prev_7d_end={windows.get('prev_7d_end')}.\n"
        "Filter records into these windows using return_ts (the time the customer "
        "submitted the return), NOT refund_ts or order_ts. A record belongs to a "
        "window when window_start <= return_ts < window_end."
    )


def _parse_decisions(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    decisions = payload.get("decisions")
    if not isinstance(decisions, list) or not all(isinstance(x, dict) for x in decisions):
        return [], "missing_or_invalid_decisions"
    return decisions, None


def _numeric_close(actual: float, expected: float, abs_tol: float, rel_tol: float) -> bool:
    diff = abs(actual - expected)
    tol = max(abs_tol, rel_tol * abs(expected))
    return diff <= tol


def grade_record(rec: bc.RunRecord, spec: dict[str, Any]) -> bc.VerdictRecord:
    if rec.error:
        return bc.VerdictRecord(
            stage=rec.stage,
            run_id=rec.run_id,
            agent=rec.agent,
            model=rec.model,
            prompt_id=rec.prompt_id,
            repeat_index=rec.repeat_index,
            verdict="fail",
            failure_reasons=[f"runtime_error:{rec.error}"],
            parsed_payload=None,
        )
    parsed = rec.parsed_payload
    if parsed is None:
        parsed, err = bc.extract_json_payload(rec.final_text)
    else:
        err = None
    if err or parsed is None:
        return bc.VerdictRecord(
            stage=rec.stage,
            run_id=rec.run_id,
            agent=rec.agent,
            model=rec.model,
            prompt_id=rec.prompt_id,
            repeat_index=rec.repeat_index,
            verdict="fail",
            failure_reasons=[f"malformed:{err}"],
            parsed_payload=None,
        )

    decisions, d_err = _parse_decisions(parsed)
    if d_err:
        return bc.VerdictRecord(
            stage=rec.stage,
            run_id=rec.run_id,
            agent=rec.agent,
            model=rec.model,
            prompt_id=rec.prompt_id,
            repeat_index=rec.repeat_index,
            verdict="fail",
            failure_reasons=[d_err],
            parsed_payload=parsed,
        )

    expected_rows = list(spec["expected_rows"])
    top_k = int(spec.get("top_k", len(expected_rows)))
    exact_fields = list(spec.get("exact_fields", []))
    numeric_fields = list(spec.get("numeric_fields", []))
    abs_tol = float(spec.get("abs_tol", 1.0))
    rel_tol = float(spec.get("rel_tol", 0.01))

    failures: list[str] = []
    if len(decisions) < top_k:
        failures.append(f"too_few_rows:{len(decisions)}<{top_k}")
    decisions = decisions[:top_k]
    expected_rows = expected_rows[:top_k]

    for i, expected in enumerate(expected_rows):
        if i >= len(decisions):
            break
        actual = decisions[i]
        for f in exact_fields:
            if actual.get(f) != expected.get(f):
                failures.append(
                    f"exact_mismatch_row_{i + 1}:{f}:actual={actual.get(f)} expected={expected.get(f)}"
                )
        for f in numeric_fields:
            av = actual.get(f)
            ev = expected.get(f)
            if av is None or ev is None:
                failures.append(f"numeric_missing_row_{i + 1}:{f}")
                continue
            try:
                avf = float(av)
                evf = float(ev)
            except (TypeError, ValueError):
                failures.append(f"numeric_invalid_row_{i + 1}:{f}")
                continue
            if not _numeric_close(avf, evf, abs_tol, rel_tol):
                failures.append(
                    f"numeric_mismatch_row_{i + 1}:{f}:actual={avf} expected={evf} abs_tol={abs_tol} rel_tol={rel_tol}"
                )

    verdict = "pass" if not failures else "fail"
    return bc.VerdictRecord(
        stage=rec.stage,
        run_id=rec.run_id,
        agent=rec.agent,
        model=rec.model,
        prompt_id=rec.prompt_id,
        repeat_index=rec.repeat_index,
        verdict=verdict,
        failure_reasons=failures,
        parsed_payload=parsed,
    )


def _run_stage(
    *,
    run_id: str,
    stage: str,
    models: list[str],
    prompts: list[dict[str, Any]],
    answer_specs: dict[int, dict[str, Any]],
    repeats: int,
    combined_agent: bc.AgentConfig,
    raw_agent: bc.AgentConfig,
    dataset_meta: dict[str, Any],
) -> tuple[list[bc.RunRecord], list[bc.VerdictRecord]]:
    run_records: list[bc.RunRecord] = []
    verdict_records: list[bc.VerdictRecord] = []
    for model in models:
        for p in prompts:
            pid = int(p["prompt_id"])
            prompt_text = _augment_prompt_with_windows(p["text"], dataset_meta)
            spec = answer_specs[pid]
            for r in range(1, repeats + 1):
                for agent in (combined_agent, raw_agent):
                    print(
                        f"[{stage}] {agent.name}/{model}/p{pid} repeat {r}/{repeats} ...",
                        flush=True,
                    )
                    rec = bc.run_one(
                        run_id=run_id,
                        stage=stage,
                        agent=agent,
                        model=model,
                        prompt_id=pid,
                        prompt_text=prompt_text,
                        repeat_index=r,
                    )
                    run_records.append(rec)
                    verdict = grade_record(rec, spec)
                    verdict_records.append(verdict)
                    print(
                        f"   -> {verdict.verdict} in={rec.input_tokens} out={rec.output_tokens} "
                        f"tools={rec.tool_calls} latency={rec.latency_ms}ms cost={rec.cost_usd} err={rec.error}",
                        flush=True,
                    )
    return run_records, verdict_records


def _summaries(
    run_id: str,
    dataset_meta: dict[str, Any],
    runs: list[dict[str, Any]],
    verdicts: list[dict[str, Any]],
    selected_prompt_ids: list[int],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    verdict_by_key = {
        (v["stage"], v["agent"], v["model"], v["prompt_id"], v["repeat_index"]): v
        for v in verdicts
    }

    rollup: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "runs": 0,
            "passes": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "tool_calls": 0,
            "latencies": [],
            "total_cost_usd": 0.0,
        }
    )

    per_prompt: dict[tuple[str, str, str, int], dict[str, Any]] = defaultdict(
        lambda: {
            "runs": 0,
            "passes": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "tool_calls": 0,
            "latencies": [],
            "total_cost_usd": 0.0,
        }
    )

    for r in runs:
        key = (r["stage"], r["agent"], r["model"])
        pk = (r["stage"], r["agent"], r["model"], int(r["prompt_id"]))
        v = verdict_by_key.get((r["stage"], r["agent"], r["model"], r["prompt_id"], r["repeat_index"]))
        for bucket in (rollup[key], per_prompt[pk]):
            bucket["runs"] += 1
            bucket["passes"] += 1 if (v and v["verdict"] == "pass") else 0
            bucket["tokens_in"] += int(r.get("input_tokens", 0))
            bucket["tokens_out"] += int(r.get("output_tokens", 0))
            bucket["tool_calls"] += int(r.get("tool_calls", 0))
            bucket["latencies"].append(float(r.get("latency_ms", 0)))
            bucket["total_cost_usd"] += float(r.get("cost_usd", 0) or 0)

    rollup_rows = []
    for (stage, agent, model), d in sorted(rollup.items()):
        pass_rate = d["passes"] / d["runs"] if d["runs"] else 0.0
        cpc = d["total_cost_usd"] / d["passes"] if d["passes"] else None
        rollup_rows.append(
            {
                "stage": stage,
                "run_id": run_id,
                "agent": agent,
                "model": model,
                "runs": d["runs"],
                "passes": d["passes"],
                "pass_rate": pass_rate,
                "tokens_in": d["tokens_in"],
                "tokens_out": d["tokens_out"],
                "tool_calls": d["tool_calls"],
                "total_cost_usd": round(d["total_cost_usd"], 6),
                "cost_per_correct": round(cpc, 6) if cpc is not None else None,
                "latency_p50_ms": bc.median_or_none(d["latencies"]),
            }
        )

    per_prompt_rows = []
    for (stage, agent, model, pid), d in sorted(per_prompt.items()):
        pass_rate = d["passes"] / d["runs"] if d["runs"] else 0.0
        per_prompt_rows.append(
            {
                "stage": stage,
                "run_id": run_id,
                "agent": agent,
                "model": model,
                "prompt_id": pid,
                "runs": d["runs"],
                "passes": d["passes"],
                "pass_rate": pass_rate,
                "tokens_in": d["tokens_in"],
                "tokens_out": d["tokens_out"],
                "tool_calls": d["tool_calls"],
                "total_cost_usd": round(d["total_cost_usd"], 6),
                "latency_p50_ms": bc.median_or_none(d["latencies"]),
            }
        )

    summary = {
        "run_id": run_id,
        "dataset": dataset_meta,
        "selected_prompt_ids": selected_prompt_ids,
        "rollup": rollup_rows,
    }
    return summary, per_prompt_rows


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Run the returns combined-vs-raw benchmark over a fixed 6-scenario "
            "set. Each scenario is executed --repeats times against each (model, agent) "
            "pair and graded against benchmark/answer_key_candidates.json."
        )
    )
    ap.add_argument(
        "--models",
        default="claude-sonnet-4-5-20250929,claude-haiku-4-5-20251001",
        help="comma-separated model list",
    )
    ap.add_argument(
        "--repeats",
        type=int,
        default=4,
        help="repeats per (model, agent, scenario); default 4",
    )
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        raise RuntimeError("at least one model must be provided via --models")

    prompts, specs_by_id, answer = _load_candidates()
    dataset_meta = answer.get("dataset", {})

    combined_agent = bc.load_agent(BENCH / "agents" / "combined")
    raw_agent = bc.load_agent(BENCH / "agents" / "raw")
    if raw_agent is None:
        raise RuntimeError("raw agent not initialized")

    run_id = time.strftime("%Y%m%d-%H%M%S")
    run_dir = OUT_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    scenario_ids = sorted(int(p["prompt_id"]) for p in prompts)
    print(
        f"[run] models={models} scenarios={scenario_ids} repeats={args.repeats}",
        flush=True,
    )

    runs, verdicts = _run_stage(
        run_id=run_id,
        stage="main",
        models=models,
        prompts=prompts,
        answer_specs=specs_by_id,
        repeats=args.repeats,
        combined_agent=combined_agent,
        raw_agent=raw_agent,
        dataset_meta=dataset_meta,
    )

    run_dicts = bc.as_dicts(runs)
    verdict_dicts = bc.as_dicts(verdicts)

    summary, per_prompt_summary = _summaries(
        run_id,
        dataset_meta,
        run_dicts,
        verdict_dicts,
        scenario_ids,
    )

    manifest = {
        "run_id": run_id,
        "models": models,
        "repeats": args.repeats,
        "scenario_ids": scenario_ids,
        "dataset": dataset_meta,
        "source_files": {
            "prompts_candidates": str(BENCH / "prompts_candidates.json"),
            "answer_key_candidates": str(BENCH / "answer_key_candidates.json"),
        },
        "outputs": {
            "runs_jsonl": str(run_dir / "runs.jsonl"),
            "verdicts_jsonl": str(run_dir / "verdicts.jsonl"),
            "summary_json": str(run_dir / "summary.json"),
            "per_prompt_summary_json": str(run_dir / "per_prompt_summary.json"),
            "manifest_json": str(run_dir / "manifest.json"),
        },
    }

    bc.write_jsonl(run_dir / "runs.jsonl", run_dicts)
    bc.write_jsonl(run_dir / "verdicts.jsonl", verdict_dicts)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    (run_dir / "per_prompt_summary.json").write_text(json.dumps(per_prompt_summary, indent=2))
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    print(f"run completed -> {run_dir}")
    print(f"scenarios: {scenario_ids}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
