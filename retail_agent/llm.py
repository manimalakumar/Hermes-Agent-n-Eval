from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"


@dataclass
class ExtractedInfo:
    wants_address_update: bool = False
    email: str | None = None
    verification_postal_code: str | None = None
    order_id: str | None = None
    new_address: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    missing: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExtractedInfo":
        address = data.get("new_address") or {}
        if not isinstance(address, dict):
            address = {}
        missing = data.get("missing") or []
        if not isinstance(missing, list):
            missing = []
        return cls(
            wants_address_update=bool(data.get("wants_address_update")),
            email=_clean_optional(data.get("email")),
            verification_postal_code=_clean_optional(data.get("verification_postal_code")),
            order_id=_clean_optional(data.get("order_id")),
            new_address={str(k): str(v).strip() for k, v in address.items() if v is not None and str(v).strip()},
            confidence=float(data.get("confidence") or 0),
            missing=[str(item) for item in missing],
        )


def _clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


class RuleBasedExtractor:
    """Test fallback. The app and live eval default to the NVIDIA extractor."""

    def extract(self, message: str, state: dict[str, Any] | None = None) -> ExtractedInfo:
        del state
        email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", message)
        order_match = re.search(r"\bORD-\d+\b", message, re.IGNORECASE)
        zips = re.findall(r"\b\d{5}(?:-\d{4})?\b", message)
        address = {}
        address_match = re.search(
            r"(?P<street>\d+\s+[^,]+),\s*(?P<city>[^,]+),\s*(?P<state>[A-Za-z]{2})\s+(?P<postal>\d{5}(?:-\d{4})?)",
            message,
        )
        if address_match:
            address = {
                "street": address_match.group("street").strip(),
                "city": address_match.group("city").strip(),
                "state": address_match.group("state").strip().upper(),
                "postal_code": address_match.group("postal").strip(),
                "country": "US",
            }
        return ExtractedInfo(
            wants_address_update=bool(re.search(r"\b(address|moved|shipping|ship)\b", message, re.IGNORECASE)),
            email=email_match.group(0).lower() if email_match else None,
            verification_postal_code=zips[0] if zips else None,
            order_id=order_match.group(0).upper() if order_match else None,
            new_address=address,
            confidence=0.6 if address or email_match else 0.3,
        )

    def confirm(self, payload: dict[str, Any]) -> str:
        order_id = payload.get("order_id") or "the order"
        address = payload.get("address") or {}
        address_text = format_address(address)
        return f"Confirmed. I updated {order_id} to ship to {address_text}."


class LiveNvidiaLLM:
    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.getenv("RETAIL_AGENT_MODEL") or DEFAULT_MODEL

    def _client(self):
        if not os.getenv("NVIDIA_API_KEY"):
            raise RuntimeError("NVIDIA_API_KEY is not set in this shell.")
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_nvidia_ai_endpoints import ChatNVIDIA

        llm = ChatNVIDIA(model=self.model, temperature=0)
        return llm, HumanMessage, SystemMessage

    def extract(self, message: str, state: dict[str, Any] | None = None) -> ExtractedInfo:
        llm, HumanMessage, SystemMessage = self._client()
        system = (
            "You extract retail support fields for an order shipping-address update. "
            "Return only valid JSON. Do not add markdown."
        )
        schema = {
            "wants_address_update": "boolean",
            "email": "string or null",
            "verification_postal_code": "old ZIP/postal code used to verify the customer, string or null",
            "order_id": "string like ORD-1001 or null",
            "new_address": {
                "street": "string",
                "city": "string",
                "state": "2-letter US state",
                "postal_code": "new shipping ZIP/postal code",
                "country": "country code, default US",
            },
            "confidence": "number from 0 to 1",
            "missing": "list of needed fields",
        }
        prompt = {
            "task": "Extract fields from the latest customer message.",
            "known_state": state or {},
            "latest_message": message,
            "json_schema": schema,
        }
        response = llm.invoke(
            [
                SystemMessage(content=system),
                HumanMessage(content=json.dumps(prompt, sort_keys=True)),
            ]
        )
        content = getattr(response, "content", str(response))
        return ExtractedInfo.from_dict(extract_json_object(content))

    def confirm(self, payload: dict[str, Any]) -> str:
        llm, HumanMessage, SystemMessage = self._client()
        response = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "Write a concise customer support confirmation. "
                        "Mention the order id and destination address. Do not reveal internal IDs."
                    )
                ),
                HumanMessage(content=json.dumps(payload, sort_keys=True)),
            ]
        )
        return str(getattr(response, "content", response)).strip()


class HermesCliLLM:
    """Live fallback that uses Hermes' configured NVIDIA auth instead of NVIDIA_API_KEY."""

    def __init__(self, model: str | None = None, hermes_bin: str | None = None) -> None:
        self.model = model or os.getenv("RETAIL_AGENT_MODEL") or DEFAULT_MODEL
        self.hermes_bin = hermes_bin or os.getenv("HERMES_BIN") or str(Path.home() / ".local" / "bin" / "hermes")

    def _run(self, prompt: str) -> str:
        if not Path(self.hermes_bin).exists() and not shutil.which(self.hermes_bin):
            raise RuntimeError("Hermes CLI was not found. Set NVIDIA_API_KEY or HERMES_BIN.")
        timeout = int(os.getenv("RETAIL_AGENT_HERMES_TIMEOUT", "120"))
        proc = subprocess.run(
            [
                self.hermes_bin,
                "-z",
                prompt,
                "--provider",
                "nvidia",
                "-m",
                self.model,
            ],
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "Hermes CLI call failed.")
        return proc.stdout.strip()

    def extract(self, message: str, state: dict[str, Any] | None = None) -> ExtractedInfo:
        schema = {
            "wants_address_update": "boolean",
            "email": "string or null",
            "verification_postal_code": "old ZIP/postal code used to verify the customer, string or null",
            "order_id": "string like ORD-1001 or null",
            "new_address": {
                "street": "string",
                "city": "string",
                "state": "2-letter US state",
                "postal_code": "new shipping ZIP/postal code",
                "country": "country code, default US",
            },
            "confidence": "number from 0 to 1",
            "missing": "list of needed fields",
        }
        payload = {
            "task": "Extract fields from a retail shipping-address-update message. Return only valid JSON.",
            "known_state": state or {},
            "latest_message": message,
            "json_schema": schema,
        }
        content = self._run(json.dumps(payload, sort_keys=True))
        return ExtractedInfo.from_dict(extract_json_object(content))

    def confirm(self, payload: dict[str, Any]) -> str:
        prompt = (
            "Write a concise customer support confirmation. Mention the order id and destination address. "
            "Do not reveal internal IDs. Payload: "
            + json.dumps(payload, sort_keys=True)
        )
        return self._run(prompt)


def make_llm(live: bool = True):
    mode = os.getenv("RETAIL_AGENT_LLM_MODE", "auto").lower()
    if not live or mode == "mock":
        return RuleBasedExtractor()
    if mode == "chatnvidia":
        return LiveNvidiaLLM()
    if mode == "hermes":
        return HermesCliLLM()
    if os.getenv("NVIDIA_API_KEY"):
        return LiveNvidiaLLM()
    return HermesCliLLM()
    return LiveNvidiaLLM()


def extracted_to_dict(info: ExtractedInfo) -> dict[str, Any]:
    return asdict(info)


def format_address(address: dict[str, str]) -> str:
    return (
        f"{address.get('street', '')}, {address.get('city', '')}, "
        f"{address.get('state', '')} {address.get('postal_code', '')}, {address.get('country', 'US')}"
    ).strip(", ")
