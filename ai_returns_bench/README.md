# Returns Agent Benchmark

Repeatable, deterministic benchmark that quantifies why a precomputed
DeltaStream context view produces better agent outcomes than stitching raw
tables together at query time.

For every scenario the benchmark measures three things side by side:

- **correctness** (graded against a numerically derived answer key)
- **token + dollar cost**
- **end-to-end latency**

Two agent surfaces sit over the same Kafka-fed data:

- `combined`: a single precomputed DeltaStream materialized view
  (`customer_returns_context_mv`) that pre-joins orders, shipments, returns,
  and refunds and pre-computes per-row metrics (`refund_gap_usd`,
  `refund_lag_hours`, `is_late_delivery`, …)
- `raw`: four raw materialized views (`orders_raw_mv`, `shipments_raw_mv`,
  `returns_raw_mv`, `refunds_raw_mv`) — the agent must perform every join,
  bucket, ratio, and delta itself

Both agents talk to the same DeltaStream MCP server. Only the SQL surface
they are allowed to touch differs.

## Locked benchmark defaults

- models: `claude-sonnet-4-5-20250929`, `claude-haiku-4-5-20251001`
- dataset size: `1000` orders / `220` customers / `seed=42`
- temporal anchor: `2026-03-01T00:00:00Z` with `last_24h`, `last_7d`,
  and `prev_7d` windows (filtered on `return_ts`)
- 6 fixed scenarios per run, `--repeats=4` per (model, agent, scenario)
- single grading flow — no calibration, no prompt selection

## Requirements

- **Python 3.11–3.13.** Tested primarily on 3.13. Python 3.14 is currently
  problematic because `pydantic-core` does not yet ship a matching wheel for
  every platform; if you must use 3.14, expect to either build
  `pydantic-core` from source or use a virtualenv pinned to an earlier
  interpreter.
- **Docker** (for the local Redpanda broker in `kafka/docker-compose.yml`).
- **DeltaStream account** with a Kafka store reachable from your network and
  a sysadmin-capable role for the setup phase.
- **Anthropic API key** with access to Claude Sonnet 4.5 and Haiku 4.5.

Install the Python deps into a virtualenv:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## The 6 scenarios

| ID | Title | Kind | Expected raw outcome |
|----|-------|------|----------------------|
| 1  | Top customers by 24h refund gap                  | ranked top-5 | passes (single-table slice) |
| 2  | Top segments by 7d refund-gap delta              | ranked top-3 | fails (window delta + segment join) |
| 3  | Top regions by 7d avg refund lag                 | ranked top-3 | fails (avg under join) |
| 4  | Systemic refund-gap-worsened flag                | scalar       | fails (two-window sum + boolean writeback) |
| 5  | Top segments by 7d late-delivery return rate     | ranked top-3 | fails (3-way join + ratio + 0-1 formatting) |
| 6  | Top reasons by 7d return-count delta             | ranked top-3 | fails (strict-integer delta, sort tiebreaks) |

Scenario 1 is the deliberate baseline: a single-table slice on a per-row
metric that already exists on `refunds_raw_mv`. Both surfaces should pass it.
Scenarios 2–6 each layer a join, derived metric, window arithmetic, or
formatting rule that breaks the raw flow while staying trivial against the
precomputed view.

The full per-scenario rationale (`raw_vs_combined_note`, `why_raw`,
`why_combined`) lives in `benchmark/answer_key_candidates.json` so the agent
prompts themselves stay slim and unbiased.

## Layout

- `kafka/docker-compose.yml` — local Redpanda broker
- `scripts/generate_seed_data.py` — deterministic dataset + the 6 scenario
  prompts + an answer key derived from the same in-memory rows
- `scripts/build_insert_entity_sql.py` — generate DeltaStream
  `INSERT INTO ENTITY` loader SQL from local JSONL
- `scripts/seed_kafka.py` — alternative path: produce JSONL straight to Kafka
- `scripts/run_deltastream_setup.py` — one-command setup runner
  (`01 → 02 → 03`, optional `04`/`05`)
- `scripts/run_deltastream_cleanup.py` — one-command teardown
- `scripts/rebuild_answer_key_from_mv.py` — rebuild the answer key from the
  live combined MV (canonical path; matches what `combined` actually sees)
- `scripts/rebuild_answer_key_from_data.py` — alternate rebuild from raw
  JSONL (escape hatch when the MV is unavailable)
- `deltastream/01_setup.sql` — base objects (db / streams / changelogs)
- `deltastream/02_load_seed_data.sql` — generated row-loader SQL
- `deltastream/03_create_surfaces.sql` — 4 raw MVs + the combined context MV
- `deltastream/04_verify_setup.sql` — optional verification queries
- `deltastream/05_rbac_and_tokens.sql` — RBAC roles, grants, API tokens
- `deltastream/roles_and_tokens.md` — concise step-5 usage notes
- `benchmark/run_benchmark.py` — single entry point (no calibration phase)
- `benchmark/agents/{combined,raw}/` — per-agent config + system prompt
- `benchmark/prompts_candidates.json` — slim, agent-facing scenario prompts
- `benchmark/answer_key_candidates.json` — expected rows, tolerances, notes
- `benchmark/out/` — timestamped JSON outputs, one folder per run

## 1) Generate deterministic benchmark data

```bash
python3 scripts/generate_seed_data.py --orders 1000 --customers 220 --seed 42
```

Writes:

- `data/orders.jsonl`
- `data/shipments.jsonl`
- `data/returns.jsonl`
- `data/refunds.jsonl`
- `benchmark/prompts_candidates.json` (6 scenario prompts)
- `benchmark/answer_key_candidates.json` (deterministic grading specs)

Re-running with the same `--seed` and `--orders` reproduces every byte.

## 2) Start local Kafka (Redpanda)

```bash
docker compose -f kafka/docker-compose.yml up -d
```

(If you skipped the Requirements section above, install the Python deps now
with `pip install -r requirements.txt`.)

The benchmark harness uses PydanticAI with the Anthropic provider and
DeltaStream MCP toolsets.

Default topic names:

- `aws_returns_orders`
- `aws_returns_shipments`
- `aws_returns_returns`
- `aws_returns_refunds`

## 3) DeltaStream setup and seed load

### Single-command option (recommended)

```bash
export DELTASTREAM_API_TOKEN=<sysadmin_token>
python3 scripts/run_deltastream_setup.py \
  --server https://api.deltastream.io \
  --store-name aws_returns_kafka_store \
  --insecure
```

For local insecure-TLS servers also set:

```bash
export DELTASTREAM_INSECURE=1
```

This runs:

- `01_setup.sql`
- regenerate and run `02_load_seed_data.sql`
- `03_create_surfaces.sql`

Implementation detail: `01_setup.sql` does not force database/schema/store
context in the API payload, so `CREATE DATABASE/SCHEMA` execute cleanly
even when the target database does not yet exist.

`04_verify_setup.sql` and `05_rbac_and_tokens.sql` are skipped by default.
Add flags to include them:

```bash
python3 scripts/run_deltastream_setup.py \
  --server https://api.deltastream.io \
  --store-name aws_returns_kafka_store \
  --insecure \
  --run-verify \
  --run-rbac
```

After the combined MV is populated, rebuild the answer key against the live
view so the grading numbers match exactly what the `combined` agent sees:

```bash
python3 scripts/rebuild_answer_key_from_mv.py
```

The script defaults to `https://api.local.deltastream.io/v2/statements`.
Override with `DS_API_URL` if your stack is at a different URL:

```bash
DS_API_URL=https://<your-host>/v2/statements python3 scripts/rebuild_answer_key_from_mv.py
```

### Manual option

1. Log into DeltaStream with a sysadmin-capable role.
2. Manually create the Kafka store `aws_returns_kafka_store`.
3. Manually create a sysadmin API token for setup execution.
4. Run `deltastream/01_setup.sql` using that sysadmin token/store context.
5. Generate load SQL from local data files:
   ```bash
   python3 scripts/build_insert_entity_sql.py --store aws_returns_kafka_store
   ```
6. Run generated `deltastream/02_load_seed_data.sql` (uses
   `INSERT INTO ENTITY`) with the same sysadmin token/store.
7. Run `deltastream/03_create_surfaces.sql` with the same sysadmin
   token/store.
8. Optionally run `deltastream/04_verify_setup.sql`.
9. Run `deltastream/05_rbac_and_tokens.sql` manually.

## 3b) DeltaStream cleanup

By default cleanup performs all actions:

- terminate named queries
- drop benchmark relations
- drop benchmark Kafka topics

```bash
export DELTASTREAM_API_TOKEN=<sysadmin_token>
python3 scripts/run_deltastream_cleanup.py \
  --server https://api.deltastream.io/v2 \
  --store-name aws_returns_kafka_store \
  --insecure
```

Optional switches:

- `--no-stop-queries`
- `--no-drop-relations`
- `--no-drop-topics`

Note: `01_setup.sql` pins all source relations to
`'starting.position' = 'earliest'` so preloaded Kafka data is read from
the beginning.

## 4) Run the benchmark sweep

**Configure the MCP endpoint** — both `benchmark/agents/combined/config.json` and
`benchmark/agents/raw/config.json` default to
`https://api.local.deltastream.io/mcp/v2`. Edit the `mcp_url` field in each
file if your stack uses a different URL before running.

Set the per-agent MCP tokens (issued by `05_rbac_and_tokens.sql`):

```bash
export COMBINED_MCP_TOKEN=<token_with_combined_view_access>
export RAW_MCP_TOKEN=<token_with_raw_view_access>
export ANTHROPIC_API_KEY=<your_key>
export DELTASTREAM_INSECURE=1   # only for self-signed local stacks
export BENCH_TOOL_RETRIES=4     # tolerate transient MCP retries
```

Then run the canonical sweep:

```bash
python3 benchmark/run_benchmark.py --repeats 4
```

That executes 6 scenarios × 4 repeats × 2 agents × 2 models = **96 runs**
in roughly 15–25 minutes against a healthy local stack.

CLI surface (intentionally minimal):

```
--models   comma-separated model list
           default: claude-sonnet-4-5-20250929,claude-haiku-4-5-20251001
--repeats  repeats per (model, agent, scenario); default 4
```

## Outputs (all JSON, repeatable format)

Each run writes a timestamped folder under `benchmark/out/<YYYYMMDD-HHMMSS>/`:

- `runs.jsonl` — one record per (agent, model, scenario, repeat)
- `verdicts.jsonl` — pass/fail with expected-vs-actual payloads and failure
  reasons
- `summary.json` — aggregate metrics by (agent, model)
- `per_prompt_summary.json` — metrics by (agent, model, scenario)
- `manifest.json` — run metadata (models, repeats, scenarios, source files)

These files are designed to be consumed directly in notebooks, BI tools,
or CI.

## Results

Reference run (`benchmark/reference_run/20260512-115832/`) — `--repeats 4`, both default models, the
6 locked scenarios:

### Headline pass rate

| Agent      | Sonnet 4.5    | Haiku 4.5     |
|------------|---------------|---------------|
| `combined` | 24/24 (100%)  | 23/24 (96%)   |
| `raw`      |  4/24  (17%)  |  4/24 (17%)   |

The 4 raw passes in each model column are all on scenario 1 (the
single-table baseline); raw goes 0/4 on scenarios 2–6 for both models.

### Cost per correct answer

| Agent      | Sonnet 4.5 | Haiku 4.5 |
|------------|-----------:|----------:|
| `combined` |   $0.0288  |  $0.0164  |
| `raw`      |   $0.3838  |  $0.4272  |

That is a ~13× efficiency gap on Sonnet and ~26× on Haiku. The raw cost
is dominated by repeated multi-table SELECTs that the agent issues while
attempting to derive the metrics that the combined view already exposes
as columns.

### Median latency (ms)

| Agent      | Sonnet 4.5 | Haiku 4.5 |
|------------|-----------:|----------:|
| `combined` |     8,265  |    4,929  |
| `raw`      |    18,052  |   14,213  |

### Token volume (input tokens, all 24 runs per cell)

| Agent      | Sonnet 4.5 | Haiku 4.5 |
|------------|-----------:|----------:|
| `combined` |    172,231 |   307,051 |
| `raw`      |    409,241 | 1,549,631 |

Raw burns ~2.4× the input tokens on Sonnet and ~5× on Haiku. Smaller
models compensate for missing precomputed structure with more tool calls
and larger payloads, not fewer.

## Notes

- Keep the prompt file, answer key, and seeded data from the same
  generator run. Reseeding with a different `--seed`/size requires
  regenerating prompts and key together.
- For strict A/B fairness, run both agents against the same data and
  same model list (the default invocation does this).
- The 6-scenario set is intentionally fixed: scenario 1 demonstrates that
  raw can win on trivial single-table reads, and 2–6 demonstrate where
  the precomputed surface stops being a convenience and becomes the
  difference between a correct and an incorrect agent answer.
