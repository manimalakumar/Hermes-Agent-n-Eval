from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .db import connect, init_db, log_event, row_to_dict


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _result(ok: bool, tool: str, **kwargs: Any) -> dict[str, Any]:
    return {"ok": ok, "tool": tool, **kwargs}


def verify_customer(
    email: str,
    verification_postal_code: str,
    db_path: str | Path | None = None,
    actor: str = "verification_agent",
) -> dict[str, Any]:
    init_db(db_path)
    clean_email = (email or "").strip().lower()
    clean_postal = (verification_postal_code or "").strip()
    with connect(db_path) as conn:
        if not EMAIL_RE.match(clean_email) or not clean_postal:
            log_event(
                conn,
                "verify_customer_rejected",
                actor,
                {"reason": "missing_or_invalid_identifier", "email": clean_email},
            )
            return _result(False, "verify_customer", error="missing_or_invalid_identifier")

        row = conn.execute(
            """
            SELECT customer_id, name, email, verification_postal_code
            FROM customers
            WHERE lower(email) = lower(?)
            """,
            (clean_email,),
        ).fetchone()
        if row is None or row["verification_postal_code"] != clean_postal:
            log_event(
                conn,
                "verify_customer_failed",
                actor,
                {"email": clean_email, "postal_code_match": False},
            )
            return _result(False, "verify_customer", error="verification_failed")

        customer = row_to_dict(row)
        log_event(conn, "verify_customer_success", actor, {"email": clean_email}, customer_id=customer["customer_id"])
        return _result(True, "verify_customer", customer=customer)


def locate_order(
    customer_id: str,
    order_id: str | None = None,
    db_path: str | Path | None = None,
    actor: str = "order_agent",
) -> dict[str, Any]:
    init_db(db_path)
    with connect(db_path) as conn:
        customer = conn.execute(
            "SELECT customer_id, name, email FROM customers WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
        if customer is None:
            log_event(conn, "locate_order_failed", actor, {"reason": "unknown_customer"}, customer_id=customer_id)
            return _result(False, "locate_order", error="unknown_customer")

        if order_id:
            order = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id.strip(),)).fetchone()
            if order is None:
                log_event(conn, "locate_order_failed", actor, {"reason": "order_not_found", "order_id": order_id})
                return _result(False, "locate_order", error="order_not_found")
            if order["customer_id"] != customer_id:
                log_event(
                    conn,
                    "locate_order_rejected",
                    actor,
                    {"reason": "order_not_owned", "order_id": order_id},
                    order_id=order_id,
                    customer_id=customer_id,
                )
                return _result(False, "locate_order", error="order_not_owned")
        else:
            order = conn.execute(
                """
                SELECT *
                FROM orders
                WHERE customer_id = ? AND status IN ('placed', 'processing')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (customer_id,),
            ).fetchone()
            if order is None:
                log_event(conn, "locate_order_failed", actor, {"reason": "no_open_order"}, customer_id=customer_id)
                return _result(False, "locate_order", error="no_open_order")

        order_dict = row_to_dict(order)
        log_event(
            conn,
            "locate_order_success",
            actor,
            {"order_id": order_dict["order_id"]},
            order_id=order_dict["order_id"],
            customer_id=customer_id,
        )
        return _result(True, "locate_order", order=order_dict)


def _validate_address(address: dict[str, str]) -> list[str]:
    missing = [key for key in ["street", "city", "state", "postal_code", "country"] if not address.get(key)]
    if missing:
        return missing
    if not re.match(r"^[A-Za-z]{2}$", address["state"].strip()):
        missing.append("state")
    if not re.match(r"^\d{5}(-\d{4})?$", address["postal_code"].strip()):
        missing.append("postal_code")
    return missing


def update_shipping_address(
    customer_id: str,
    order_id: str,
    street: str,
    city: str,
    state: str,
    postal_code: str,
    country: str = "US",
    db_path: str | Path | None = None,
    actor: str = "customer_profile_agent",
) -> dict[str, Any]:
    init_db(db_path)
    address = {
        "street": (street or "").strip(),
        "city": (city or "").strip(),
        "state": (state or "").strip().upper(),
        "postal_code": (postal_code or "").strip(),
        "country": (country or "US").strip().upper(),
    }
    missing = _validate_address(address)
    with connect(db_path) as conn:
        if missing:
            log_event(
                conn,
                "update_shipping_address_rejected",
                actor,
                {"reason": "invalid_address", "missing_or_invalid": missing},
                order_id=order_id,
                customer_id=customer_id,
            )
            return _result(False, "update_shipping_address", error="invalid_address", missing_or_invalid=missing)

        order = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        if order is None:
            log_event(
                conn,
                "update_shipping_address_rejected",
                actor,
                {"reason": "order_not_found"},
                order_id=order_id,
                customer_id=customer_id,
            )
            return _result(False, "update_shipping_address", error="order_not_found")
        if order["customer_id"] != customer_id:
            log_event(
                conn,
                "update_shipping_address_rejected",
                actor,
                {"reason": "order_not_owned", "actual_customer_id": order["customer_id"]},
                order_id=order_id,
                customer_id=customer_id,
            )
            return _result(False, "update_shipping_address", error="order_not_owned")
        if order["status"] not in {"placed", "processing"}:
            log_event(
                conn,
                "update_shipping_address_rejected",
                actor,
                {"reason": "order_not_modifiable", "status": order["status"]},
                order_id=order_id,
                customer_id=customer_id,
            )
            return _result(False, "update_shipping_address", error="order_not_modifiable", status=order["status"])

        conn.execute(
            """
            UPDATE orders
            SET shipping_street = ?, shipping_city = ?, shipping_state = ?,
                shipping_postal_code = ?, shipping_country = ?
            WHERE order_id = ?
            """,
            (address["street"], address["city"], address["state"], address["postal_code"], address["country"], order_id),
        )
        conn.execute(
            """
            UPDATE customers
            SET profile_street = ?, profile_city = ?, profile_state = ?,
                profile_postal_code = ?, profile_country = ?
            WHERE customer_id = ?
            """,
            (address["street"], address["city"], address["state"], address["postal_code"], address["country"], customer_id),
        )
        log_event(
            conn,
            "update_shipping_address_success",
            actor,
            {"address": address},
            order_id=order_id,
            customer_id=customer_id,
        )
        updated_order = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        return _result(True, "update_shipping_address", order=row_to_dict(updated_order), address=address)


def read_order(order_id: str, db_path: str | Path | None = None) -> dict[str, Any]:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        if row is None:
            return _result(False, "read_order", error="order_not_found")
        return _result(True, "read_order", order=row_to_dict(row))


def list_open_orders(customer_id: str, db_path: str | Path | None = None) -> dict[str, Any]:
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM orders
            WHERE customer_id = ? AND status IN ('placed', 'processing')
            ORDER BY created_at DESC
            """,
            (customer_id,),
        ).fetchall()
        return _result(True, "list_open_orders", orders=[row_to_dict(row) for row in rows])


def get_audit_trace(db_path: str | Path | None = None) -> dict[str, Any]:
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM audit_events ORDER BY id ASC",
        ).fetchall()
        events = []
        for row in rows:
            item = row_to_dict(row)
            item["payload"] = item.pop("payload_json")
            events.append(item)
        return _result(True, "get_audit_trace", events=events)
