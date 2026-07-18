from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import tools
from .llm import ExtractedInfo


@dataclass
class AgentStep:
    agent: str
    task: str
    ok: bool
    detail: str
    data: dict[str, Any]


class VerificationAgent:
    name = "Verification Agent"

    def run(self, info: ExtractedInfo, db_path: str | Path | None = None) -> AgentStep:
        if not info.email or not info.verification_postal_code:
            return AgentStep(self.name, "Verify the customer", False, "Need email and verification ZIP.", {})
        result = tools.verify_customer(info.email, info.verification_postal_code, db_path=db_path)
        detail = "Customer verified." if result["ok"] else f"Verification failed: {result.get('error')}"
        return AgentStep(self.name, "Verify the customer", result["ok"], detail, result)


class OrderAgent:
    name = "Order Agent"

    def run(self, customer_id: str, info: ExtractedInfo, db_path: str | Path | None = None) -> AgentStep:
        result = tools.locate_order(customer_id, info.order_id, db_path=db_path)
        detail = "Order located." if result["ok"] else f"Order lookup failed: {result.get('error')}"
        return AgentStep(self.name, "Locate the customer's order", result["ok"], detail, result)


class CustomerProfileAgent:
    name = "Customer Profile Agent"

    def run(
        self,
        customer_id: str,
        order_id: str,
        info: ExtractedInfo,
        db_path: str | Path | None = None,
    ) -> AgentStep:
        address = info.new_address
        result = tools.update_shipping_address(
            customer_id=customer_id,
            order_id=order_id,
            street=address.get("street", ""),
            city=address.get("city", ""),
            state=address.get("state", ""),
            postal_code=address.get("postal_code", ""),
            country=address.get("country", "US"),
            db_path=db_path,
        )
        detail = "Address updated." if result["ok"] else f"Address update failed: {result.get('error')}"
        return AgentStep(self.name, "Save the new address", result["ok"], detail, result)
