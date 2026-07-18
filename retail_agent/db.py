from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "retail_agent.sqlite"


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    raw = db_path or os.getenv("RETAIL_AGENT_DB") or DEFAULT_DB_PATH
    return Path(raw).expanduser().resolve()


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def init_db(db_path: str | Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS customers (
                customer_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                verification_postal_code TEXT NOT NULL,
                profile_street TEXT NOT NULL,
                profile_city TEXT NOT NULL,
                profile_state TEXT NOT NULL,
                profile_postal_code TEXT NOT NULL,
                profile_country TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                shipping_street TEXT NOT NULL,
                shipping_city TEXT NOT NULL,
                shipping_state TEXT NOT NULL,
                shipping_postal_code TEXT NOT NULL,
                shipping_country TEXT NOT NULL,
                FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
            );

            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT NOT NULL,
                actor TEXT NOT NULL,
                order_id TEXT,
                customer_id TEXT,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


def log_event(
    conn: sqlite3.Connection,
    event: str,
    actor: str,
    payload: dict[str, Any],
    order_id: str | None = None,
    customer_id: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_events(event, actor, order_id, customer_id, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (event, actor, order_id, customer_id, json.dumps(payload, sort_keys=True), now_iso()),
    )


def reset_demo_db(db_path: str | Path | None = None) -> Path:
    path = resolve_db_path(db_path)
    if path.exists():
        path.unlink()
    init_db(path)
    with connect(path) as conn:
        conn.executemany(
            """
            INSERT INTO customers(
                customer_id, name, email, verification_postal_code,
                profile_street, profile_city, profile_state, profile_postal_code, profile_country
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "cus_jamie",
                    "Jamie Rivera",
                    "jamie@example.com",
                    "98101",
                    "120 Pine St Apt 4",
                    "Seattle",
                    "WA",
                    "98101",
                    "US",
                ),
                (
                    "cus_riley",
                    "Riley Chen",
                    "riley@example.com",
                    "10001",
                    "88 Madison Ave",
                    "New York",
                    "NY",
                    "10001",
                    "US",
                ),
            ],
        )
        conn.executemany(
            """
            INSERT INTO orders(
                order_id, customer_id, status, created_at,
                shipping_street, shipping_city, shipping_state, shipping_postal_code, shipping_country
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "ORD-1001",
                    "cus_jamie",
                    "placed",
                    "2026-07-17T18:15:00+00:00",
                    "120 Pine St Apt 4",
                    "Seattle",
                    "WA",
                    "98101",
                    "US",
                ),
                (
                    "ORD-2002",
                    "cus_riley",
                    "placed",
                    "2026-07-17T18:30:00+00:00",
                    "88 Madison Ave",
                    "New York",
                    "NY",
                    "10001",
                    "US",
                ),
                (
                    "ORD-3003",
                    "cus_jamie",
                    "fulfilled",
                    "2026-07-14T09:10:00+00:00",
                    "120 Pine St Apt 4",
                    "Seattle",
                    "WA",
                    "98101",
                    "US",
                ),
            ],
        )
        log_event(conn, "demo_db_reset", "system", {"db_path": str(path)})
    return path
