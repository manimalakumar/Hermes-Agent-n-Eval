from pathlib import Path

from retail_agent.db import reset_demo_db
from retail_agent.llm import RuleBasedExtractor
from retail_agent.tools import read_order
from retail_agent.workflow import RetailWorkflow


def test_two_turn_workflow_updates_order(tmp_path: Path) -> None:
    db_path = tmp_path / "retail.sqlite"
    reset_demo_db(db_path)
    workflow = RetailWorkflow(db_path, llm=RuleBasedExtractor())
    state = RetailWorkflow.empty_state()

    first = workflow.handle(
        "I moved. My email is jamie@example.com and my current ZIP is 98101. Please update my order ORD-1001.",
        state,
    )
    assert first.state["awaiting"] == "address"
    assert first.state["customer_id"] == "cus_jamie"

    second = workflow.handle("742 Market St Apt 9, San Francisco, CA 94103", first.state)
    assert second.state["completed"]
    assert read_order("ORD-1001", db_path)["order"]["shipping_postal_code"] == "94103"
