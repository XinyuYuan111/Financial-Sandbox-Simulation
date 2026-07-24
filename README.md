# Parallel Market Sandbox

Framework Alpha is a local, event-sourced crypto market simulation that can be saved, replayed, and forked. It combines the v0.2 sandbox infrastructure with the Agent v0.1 runtime: typed observations, deterministic cognition, bounded planning, declarative strategy plans, action receipts, revisioned state, and an auditable OpenAI planning adapter.

The model keeps two kinds of market participants separate. Explicit Agents own persona, memory, beliefs, planning budgets, decisions, and private observations. The background market sector only supplies seeded market participation and never appears as a thinking Agent.

## Quick start

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
cd frontend
npm install
npm run build
cd ..
.venv\Scripts\python -m uvicorn sandbox.app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. The bundled scenario is explicitly marked `test_fixture`; live Quick Start refuses to resolve until chain and LLM provider adapters pass preflight.

## Agent modes

- `test_fixture`: deterministic local run. The fixture strategies still pass through Observation -> Decision -> Plan -> Action -> Receipt.
- `live_llm_smoke`: four generated Agents, synthetic holder data, and real OpenAI planning calls. This is the smallest live integration check.
- `live`: generated Compact (20) or Standard (200) populations. It additionally requires a configured holder-data adapter; none is enabled by default.

Population generation is seed-stable and conserves integer asset totals. Compact and Standard keep 70% of each asset with explicit Agents and 30% in the background market sector.

## OpenAI planning

The API key is read only by the backend. It is never returned by `/api/v1/providers`, persisted to SQLite, or included in `.sandbox` archives. Provider-side storage is fixed to `false`.

```powershell
$env:OPENAI_API_KEY = "..."
$env:SANDBOX_OPENAI_MODEL = "gpt-5.6-terra"       # optional
$env:SANDBOX_OPENAI_TIMEOUT_SECONDS = "30"         # optional
$env:SANDBOX_OPENAI_MAX_RETRIES = "1"              # optional
$env:SANDBOX_OPENAI_MAX_IN_FLIGHT = "4"            # optional
$env:SANDBOX_OPENAI_MAX_OUTPUT_TOKENS = "1800"     # optional
.venv\Scripts\python scripts\agent_smoke.py
```

The smoke script performs provider preflight, creates four Agents, processes at most four planning requests, verifies the event hash chain and asset conservation, checkpoints the run, and forks a child branch. It incurs real API usage. Without `OPENAI_API_KEY` it exits before creating a run and prints an actionable configuration message.

## Audit surfaces

The UI exposes each explicit Agent's account, observations, memory and beliefs, active plan, decisions, action receipts, and authoritative event references. The API equivalents are under:

```text
GET /api/v1/branches/{branch_id}/agents
GET /api/v1/branches/{branch_id}/agents/{agent_id}
GET /api/v1/branches/{branch_id}/agents/{agent_id}/observations
GET /api/v1/branches/{branch_id}/agents/{agent_id}/decisions
GET /api/v1/branches/{branch_id}/agents/{agent_id}/plans
GET /api/v1/branches/{branch_id}/agents/{agent_id}/receipts
```

## Paused interventions

World interventions are accepted only while a branch is `Paused`. The command-scoped Scenario Director creates a typed draft with a bounded effect catalog; a separate confirmation is required before current-time stages are committed. State effects are validated on a cloned world and committed atomically before dependent information is published. Future stages remain pending until the running branch reaches their virtual time.

```text
GET  /api/v1/branches/{branch_id}/intervention-plans
POST /api/v1/branches/{branch_id}/intervention-plans
POST /api/v1/branches/{branch_id}/intervention-plans/interpret
POST /api/v1/branches/{branch_id}/intervention-plans/{plan_id}/confirm
POST /api/v1/branches/{branch_id}/intervention-plans/{plan_id}/reject
```

Pause, resume, and run-speed commands are idempotent control-plane audit records. They do not create virtual World events or advance `sim_time_us`. Provider results that return while paused are persisted as non-authoritative material and activated only after resume.

## Verification

```powershell
.venv\Scripts\python -m pytest
cd frontend
npm run check
npm run build
```

Runtime data is written to `data/sandbox.db` by default. Set `SANDBOX_DATA_DIR` to use another local directory.
