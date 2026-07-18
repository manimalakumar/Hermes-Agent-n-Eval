from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .agents import AgentStep, CustomerProfileAgent, OrderAgent, VerificationAgent
from .llm import extracted_to_dict, format_address, make_llm
from .tools import read_order


@dataclass
class WorkflowResult:
    reply: str
    state: dict[str, Any]
    steps: list[AgentStep]
    extracted: dict[str, Any]
    order: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reply": self.reply,
            "state": self.state,
            "steps": [asdict(step) for step in self.steps],
            "extracted": self.extracted,
            "order": self.order,
        }


class RetailWorkflow:
    def __init__(self, db_path: str | Path | None = None, llm: Any | None = None) -> None:
        self.db_path = db_path
        self.llm = llm or make_llm(live=True)
        self.verification_agent = VerificationAgent()
        self.order_agent = OrderAgent()
        self.profile_agent = CustomerProfileAgent()

    @staticmethod
    def empty_state() -> dict[str, Any]:
        return {
            "customer_id": None,
            "customer_name": None,
            "email": None,
            "verification_postal_code": None,
            "order_id": None,
            "awaiting": "verification",
            "completed": False,
        }

    def handle(self, message: str, state: dict[str, Any] | None = None) -> WorkflowResult:
        state = dict(state or self.empty_state())
        info = self.llm.extract(message, state)
        extracted = extracted_to_dict(info)
        steps: list[AgentStep] = []

        if info.email:
            state["email"] = info.email
        if info.verification_postal_code and not state.get("verification_postal_code"):
            state["verification_postal_code"] = info.verification_postal_code
        if info.order_id:
            state["order_id"] = info.order_id

        if not state.get("customer_id"):
            if state.get("email") and state.get("verification_postal_code"):
                info.email = state["email"]
                info.verification_postal_code = state["verification_postal_code"]
                step = self.verification_agent.run(info, self.db_path)
                steps.append(step)
                if not step.ok:
                    state["awaiting"] = "verification"
                    return WorkflowResult(
                        "I could not verify that customer. Please check the email and verification ZIP.",
                        state,
                        steps,
                        extracted,
                    )
                customer = step.data["customer"]
                state["customer_id"] = customer["customer_id"]
                state["customer_name"] = customer["name"]
                state["awaiting"] = "order"
            else:
                state["awaiting"] = "verification"
                return WorkflowResult(
                    "I can help with that. Please send the email on the order and the current billing or shipping ZIP.",
                    state,
                    steps,
                    extracted,
                )

        if not state.get("order_id") or state.get("awaiting") == "order":
            step = self.order_agent.run(state["customer_id"], info, self.db_path)
            steps.append(step)
            if not step.ok:
                state["awaiting"] = "order"
                return WorkflowResult(
                    "I verified you, but I could not find an open order I can safely modify. Please share the order number.",
                    state,
                    steps,
                    extracted,
                )
            state["order_id"] = step.data["order"]["order_id"]
            state["awaiting"] = "address"

        if not info.new_address:
            order = read_order(state["order_id"], self.db_path).get("order")
            return WorkflowResult(
                f"I found order {state['order_id']}. Please send the full new shipping address.",
                state,
                steps,
                extracted,
                order,
            )

        step = self.profile_agent.run(state["customer_id"], state["order_id"], info, self.db_path)
        steps.append(step)
        order = step.data.get("order") if step.data.get("ok") else read_order(state["order_id"], self.db_path).get("order")
        if not step.ok:
            state["awaiting"] = "address"
            return WorkflowResult(
                "I could not save that address. Please send a complete US address with street, city, state, and ZIP.",
                state,
                steps,
                extracted,
                order,
            )

        state["completed"] = True
        state["awaiting"] = "done"
        payload = {
            "order_id": state["order_id"],
            "customer_name": state.get("customer_name"),
            "address": step.data["address"],
            "address_text": format_address(step.data["address"]),
        }
        try:
            reply = self.llm.confirm(payload)
        except Exception:
            reply = f"Confirmed. I updated order {state['order_id']} to ship to {payload['address_text']}."
        return WorkflowResult(reply, state, steps, extracted, order)
