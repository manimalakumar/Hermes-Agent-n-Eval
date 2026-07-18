from pathlib import Path

from retail_agent.db import reset_demo_db
from retail_agent.tools import locate_order, read_order, update_shipping_address, verify_customer


def test_update_address_happy_path(tmp_path: Path) -> None:
    db_path = tmp_path / "retail.sqlite"
    reset_demo_db(db_path)

    verified = verify_customer("jamie@example.com", "98101", db_path)
    assert verified["ok"]
    order = locate_order(verified["customer"]["customer_id"], "ORD-1001", db_path)
    assert order["ok"]

    updated = update_shipping_address(
        verified["customer"]["customer_id"],
        "ORD-1001",
        "742 Market St Apt 9",
        "San Francisco",
        "CA",
        "94103",
        "US",
        db_path,
    )
    assert updated["ok"]
    assert read_order("ORD-1001", db_path)["order"]["shipping_postal_code"] == "94103"


def test_wrong_customer_order_is_not_modified(tmp_path: Path) -> None:
    db_path = tmp_path / "retail.sqlite"
    reset_demo_db(db_path)

    verified = verify_customer("jamie@example.com", "98101", db_path)
    blocked = locate_order(verified["customer"]["customer_id"], "ORD-2002", db_path)
    assert not blocked["ok"]
    assert blocked["error"] == "order_not_owned"

    order = read_order("ORD-2002", db_path)["order"]
    assert order["shipping_postal_code"] == "10001"


def test_fulfilled_order_is_not_modifiable(tmp_path: Path) -> None:
    db_path = tmp_path / "retail.sqlite"
    reset_demo_db(db_path)

    verified = verify_customer("jamie@example.com", "98101", db_path)
    updated = update_shipping_address(
        verified["customer"]["customer_id"],
        "ORD-3003",
        "742 Market St Apt 9",
        "San Francisco",
        "CA",
        "94103",
        "US",
        db_path,
    )
    assert not updated["ok"]
    assert updated["error"] == "order_not_modifiable"
    assert read_order("ORD-3003", db_path)["order"]["shipping_postal_code"] == "98101"
