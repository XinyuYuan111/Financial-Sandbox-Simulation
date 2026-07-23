# Parallel Market Sandbox

Framework Alpha is a local, event-sourced crypto market simulation that can be saved, replayed, and forked. The first implementation slice follows the v0.2 infrastructure specification: one target token, synthetic USDx, an integer-only ledger, a local CLOB, persisted observations, checkpoints, isolated branches, and a validated `.sandbox` archive.

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

## Verification

```powershell
.venv\Scripts\python -m pytest
cd frontend
npm run check
npm run build
```

Runtime data is written to `data/sandbox.db` by default. Set `SANDBOX_DATA_DIR` to use another local directory.

