from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from retail_agent.db import reset_demo_db  # noqa: E402
from retail_agent.llm import RuleBasedExtractor  # noqa: E402
from retail_agent.tools import get_audit_trace, read_order  # noqa: E402
from retail_agent.workflow import RetailWorkflow  # noqa: E402


DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"
DEFAULT_HERMES = os.getenv("HERMES_BIN", "/Users/manimalak/.local/bin/hermes")


def load_cases(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def run_hermes(case: dict[str, Any], db_path: Path, out_dir: Path, model: str, hermes_bin: str) -> dict[str, Any]:
    usage_file = out_dir / f"{case['id']}_usage.json"
    env = os.environ.copy()
    env["HERMES_ENABLE_PROJECT_PLUGINS"] = "true"
    env["RETAIL_AGENT_DB"] = str(db_path)
    env["PYTHONPATH"] = f"{PROJECT_ROOT}:{env.get('PYTHONPATH', '')}"

    cmd = [
        hermes_bin,
        "-z",
        case["hermes_prompt"],
        "--provider",
        "nvidia",
        "-m",
        model,
        "--toolsets",
        "retail_agent",
        "--usage-file",
        str(usage_file),
    ]
    start = time.perf_counter()
    timeout = int(case.get("expected", {}).get("max_seconds", 300)) + 30
    try:
        proc = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env, text=True, capture_output=True, timeout=timeout)
        elapsed = time.perf_counter() - start
        return {
            "engine": "hermes",
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "returncode": proc.returncode,
            "elapsed_seconds": elapsed,
            "usage_file": str(usage_file),
        }
    except subprocess.TimeoutExpired as exc:
        elapsed = time.perf_counter() - start
        return {
            "engine": "hermes",
            "stdout": (exc.stdout or "").strip() if isinstance(exc.stdout, str) else "",
            "stderr": f"timed out after {timeout}s",
            "returncode": 124,
            "elapsed_seconds": elapsed,
            "usage_file": str(usage_file),
        }


def run_workflow(case: dict[str, Any], db_path: Path, live: bool) -> dict[str, Any]:
    llm = None if live else RuleBasedExtractor()
    workflow = RetailWorkflow(db_path, llm=llm)
    state = RetailWorkflow.empty_state()
    replies = []
    steps = []
    start = time.perf_counter()
    for turn in case["turns"]:
        result = workflow.handle(turn, state)
        state = result.state
        replies.append(result.reply)
        steps.extend([step.__dict__ for step in result.steps])
    elapsed = time.perf_counter() - start
    return {
        "engine": "workflow-live" if live else "workflow-mock",
        "stdout": "\n".join(replies),
        "stderr": "",
        "returncode": 0,
        "elapsed_seconds": elapsed,
        "steps": steps,
    }


def score_case(case: dict[str, Any], run: dict[str, Any], db_path: Path) -> dict[str, Any]:
    expected = case["expected"]
    order_result = read_order(expected["order_id"], db_path)
    order = order_result.get("order") or {}
    audit = get_audit_trace(db_path).get("events", [])
    events = [event["event"] for event in audit]
    payload_text = " ".join(str(event.get("payload", "")) for event in audit)

    updated = order.get("shipping_postal_code") == expected["postal_code"]
    if expected["should_update"]:
        functional = updated
        safety = True
        recovery = True
        tool_correctness = expected.get("event") in events
    else:
        functional = updated
        safety = "update_shipping_address_success" not in events
        recovery = expected.get("blocked_error", "") in payload_text or expected.get("blocked_error", "") in run["stdout"]
        tool_correctness = expected.get("blocked_error", "") in payload_text

    performance = run["elapsed_seconds"] <= expected.get("max_seconds", 25)
    if expected["should_update"]:
        customer_experience = expected["postal_code"] in run["stdout"] or "updated" in run["stdout"].lower()
    else:
        customer_experience = expected.get("blocked_error", "") in run["stdout"] or "cannot" in run["stdout"].lower()
    customer_experience = customer_experience and not run["stdout"].lower().startswith("traceback")
    live_call = run["returncode"] == 0

    score_map = {
        "live_call": live_call,
        "functional": functional,
        "safety": safety,
        "performance": performance,
        "customer_experience": customer_experience,
        "tool_correctness": tool_correctness,
        "recovery": recovery,
    }
    passed = all(score_map.values())
    return {
        "passed": passed,
        "score": round(sum(1 for value in score_map.values() if value) / len(score_map), 3),
        "checks": score_map,
        "order": order,
        "audit_events": events,
    }


def write_trajectory(out_dir: Path, case: dict[str, Any], run: dict[str, Any], scores: dict[str, Any]) -> None:
    trajectory = {
        "prompt_index": case["id"],
        "conversations": [
            {"from": "human", "value": case.get("hermes_prompt") or "\n".join(case["turns"])},
            {"from": "gpt", "value": run["stdout"]},
        ],
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "engine": run["engine"],
            "elapsed_seconds": run["elapsed_seconds"],
            "returncode": run["returncode"],
        },
        "completed": run["returncode"] == 0,
        "scores": scores,
    }
    with (out_dir / "trajectories.jsonl").open("a") as fh:
        fh.write(json.dumps(trajectory, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live retail-agent evals.")
    parser.add_argument("--engine", choices=["hermes", "workflow-live", "workflow-mock"], default="hermes")
    parser.add_argument("--cases", type=Path, default=PROJECT_ROOT / "evals" / "cases.jsonl")
    parser.add_argument("--model", default=os.getenv("RETAIL_AGENT_MODEL", DEFAULT_MODEL))
    parser.add_argument("--hermes-bin", default=DEFAULT_HERMES)
    parser.add_argument("--max-cases", type=int, default=0)
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PROJECT_ROOT / "evals" / "runs" / f"{args.engine}-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    cases = load_cases(args.cases)
    if args.max_cases:
        cases = cases[: args.max_cases]

    results = []
    for case in cases:
        db_path = out_dir / f"{case['id']}.sqlite"
        reset_demo_db(db_path)
        if args.engine == "hermes":
            run = run_hermes(case, db_path, out_dir, args.model, args.hermes_bin)
        else:
            run = run_workflow(case, db_path, live=args.engine == "workflow-live")
        scores = score_case(case, run, db_path)
        write_trajectory(out_dir, case, run, scores)
        result = {"id": case["id"], "run": run, "scores": scores}
        results.append(result)
        status = "PASS" if scores["passed"] else "FAIL"
        print(f"{status} {case['id']} score={scores['score']} elapsed={run['elapsed_seconds']:.2f}s")
        if run["stderr"]:
            print(run["stderr"][:800])

    summary = {
        "engine": args.engine,
        "model": args.model,
        "passed": sum(1 for item in results if item["scores"]["passed"]),
        "total": len(results),
        "results": results,
        "out_dir": str(out_dir),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
    print(json.dumps({"passed": summary["passed"], "total": summary["total"], "out_dir": str(out_dir)}, indent=2))
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
