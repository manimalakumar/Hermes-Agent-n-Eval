# Retail Agent and Workflow Evaluation

**Did the agent update the correct order—and leave the correct business state behind?**

A mini retail support application that connects a customer request to tool execution, persistent SQLite state, and an inspectable audit trace.

## What to explore

| Path | What it demonstrates |
| --- | --- |
| Streamlit application | A two-turn shipping-address update workflow. |
| Local tests | Deterministic behavior checks without live model calls. |
| Live evaluation | Model/tool execution followed by database and trace inspection. |

This is a demonstration of evaluating a business workflow. The criteria and runner are available; this README does not claim a measured live pass rate or production readiness.

## Before you run

You need Git, `uv`, and suitable credentials for live model calls. The Hermes path additionally requires a separately installed Hermes CLI and configured provider access. Follow the [Hermes project's installation guidance](https://github.com/NousResearch/hermes-agent) for its prerequisites.

The commands below describe the original workflow. They have not been rerun on a clean machine for this documentation refresh. Live commands can consume provider quota; local tests use a rule-based extractor.

## Workflow and technical instructions


This project demonstrates a retail support job where a customer asks to update the shipping address on a newly placed order.

It is compact by design, but the moving pieces are real:

- Streamlit app with a two-turn customer support workflow | App we want to Eval
- NVIDIA NIM LLM calls through `ChatNVIDIA` | The brain of the system for customer interaction and agents
- Hermes project-local plugin with retail tools | The Agent environment managing and keeping track to Evaluate
- SQLite business state and audit trace | The app writes to SQL DB, persistent and attachable memory for agents
- Live eval runner that verifies database state after LLM/tool execution | The eureka moment!
- I developed with Hermes agent environemnt and NVIDIA LLM | You can swap with your choice of tools and models

## Stack

| Layer | Technology | Role |
| --- | --- | --- |
| User interface | Streamlit | Interactive retail support demo |
| Agent environment | Hermes | Agent execution and project-local tool integration |
| Model integration | LangChain `ChatNVIDIA` / Hermes CLI | Two paths for invoking the model |
| Model provider | NVIDIA NIM | Hosted LLM inference |
| Business state | SQLite | Persistent customer and order data |
| Audit trail | SQLite-backed tool events | Records actions for inspection and evaluation |
| Live evaluation | Custom Python runner | Checks database state and tool traces after agent execution |
| Local testing | pytest | Tests workflow behavior without live model calls |

## Scenario

Customer goal: update the shipping address on an existing order.

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
git clone https://github.com/manimalakumar/Hermes-Agent-n-Eval.git
cd Hermes-Agent-n-Eval
uv sync --extra dev
```

The original development environment used the Hermes executable at the path below. Install and configure Hermes separately before using the Hermes-dependent commands; this path is not supplied by cloning the repository:

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
