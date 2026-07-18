# Retail Agent: Live Agents + LLM Calls Demo

This project demonstrates a retail support job where a customer asks to update the shipping address on a newly placed order.

It is intentionally small, but the moving pieces are real:

- Streamlit app with a two-turn customer support workflow | App we want to Eval
- NVIDIA NIM LLM calls through `ChatNVIDIA` | The brain of the system for customer interaction and agents
- Hermes project-local plugin with retail tools | The Agent environment managing and keeping track to Evaluate
- SQLite business state and audit trace | The app writes to SQL DB, persistent and attachable memory for agents
- Live eval runner that verifies database state after LLM/tool execution | The eureka moment!
- I developed with Hermes agent environemnt and NVIDIA LLM | You can swap with your choice of tools and models

## Scenario

Customer goal: place an order.

Business outcome: take an order that can be fulfilled.

Job: update the address on an existing order.

Tasks:

1. Verify the customer.
2. Locate the customer's order.
3. Collect the customer's new address.
4. Save the new address.
5. Send confirmation to the customer.

Demo customer:

```text
email: jamie@example.com
verification ZIP: 98101
order: ORD-1001
```

Sample new address:

```text
742 Market St Apt 9, San Francisco, CA 94103, US
```

## First-Time Setup

From this folder:

```bash
cd /<<Path to the project>>/hermes-agents-eval/retail-agent
uv sync --extra dev
```

Hermes has already been installed on this machine at:

```bash
~/.local/bin/hermes
```

Hermes NVIDIA provider check:

```bash
~/.local/bin/hermes auth status nvidia
~/.local/bin/hermes -z "Reply with exactly: HERMES_OK" --provider nvidia -m nvidia/nemotron-3-super-120b-a12b
```

Enable the project-local Hermes plugin:

```bash
uv run python scripts/enable_hermes_plugin.py
HERMES_ENABLE_PROJECT_PLUGINS=true ~/.local/bin/hermes tools list | grep retail_agent
```

## Run The Streamlit App

By default, the app uses `ChatNVIDIA` when `NVIDIA_API_KEY` is present. If it is not present, it falls back to the Hermes CLI and uses the NVIDIA credential saved with `hermes auth add nvidia`.

```bash
uv run python scripts/reset_demo_db.py
uv run streamlit run app.py
```

To force `ChatNVIDIA` directly:

```bash
export NVIDIA_API_KEY="your_ngc_key_here"
export RETAIL_AGENT_LLM_MODE=chatnvidia
uv run streamlit run app.py
```

To force the Hermes CLI fallback:

```bash
export RETAIL_AGENT_LLM_MODE=hermes
uv run streamlit run app.py
```

Open:

```text
http://localhost:8501
```

Try two turns:

```text
I recently moved. Please update the order I just placed. My email is jamie@example.com and current ZIP is 98101.
```

```text
Please use 742 Market St Apt 9, San Francisco, CA 94103, US.
```

## Run Live Hermes Evals

These evals use the Hermes CLI, NVIDIA provider, and the project-local Hermes plugin. Hermes can use the NVIDIA credential saved with `hermes auth add nvidia`, so this does not require `NVIDIA_API_KEY` in the shell if Hermes auth is logged in.

```bash
HERMES_ENABLE_PROJECT_PLUGINS=true uv run python evals/live_eval.py --engine hermes
```

Outputs are written to:

```text
evals/runs/<engine>-<timestamp>/
```

The runner writes:

- `summary.json`
- `trajectories.jsonl`
- per-case SQLite databases
- per-case Hermes usage files

## Run Local Tests

```bash
uv run pytest -q
```

The tests use a rule-based extractor, not the live model, so they do not consume NVIDIA quota.

## Eval Success Measures

Functional:

- The correct order address is updated in SQLite.

Safety:

- A wrong customer's order is never modified.

Performance:

- Each live eval case finishes within its case budget.

Customer experience:

- A clear response is returned.

Tool correctness:

- The expected retail tool events appear in the audit trace.

Recovery:

- Unmodifiable or unsafe requests return helpful failure behavior.

## Important Files

- `app.py`: Streamlit app
- `retail_agent/workflow.py`: two-turn workflow coordinator
- `retail_agent/agents.py`: Verification, Order, and Customer Profile agents
- `retail_agent/tools.py`: SQLite-backed business tools
- `.hermes/plugins/retail-agent/__init__.py`: Hermes project plugin
- `evals/live_eval.py`: live eval runner
- `evals/cases.jsonl`: eval cases
