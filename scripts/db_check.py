"""
Generic SQLite schema inspector for local dev.
- Lists all tables
- Prints CREATE TABLE (DDL)
- Prints columns with defaults (PRAGMA table_info)
- Prints indexes and foreign keys

Usage:
  python scripts/db_check.py                 # all tables
  python scripts/db_check.py --table doctors # single table
  python scripts/db_check.py --like doc%     # tables matching pattern
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any, Mapping, Sequence

DB_PATH = Path("backend/db/sqlite.db")  # fixed path for local dev


def query_all(
    conn: sqlite3.Connection,
    sql: str,
    params: Sequence[Any] | Mapping[str, Any] = (),
) -> list[tuple]:
    cur = conn.execute(sql, params)
    try:
        return cur.fetchall()
    finally:
        cur.close()


def print_table_schema(conn: sqlite3.Connection, table: str) -> None:
    print(f"\n== {table} ==")

    # DDL
    ddl_rows = query_all(
        conn,
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?;",
        (table,),
    )
    ddl = ddl_rows[0][0] if ddl_rows else None
    print("\n-- CREATE TABLE")
    print(ddl or "<no DDL found>")

    # Columns (includes defaults)
    print("\n-- COLUMNS (PRAGMA table_info)")
    # row: (cid, name, type, notnull, dflt_value, pk)
    for cid, name, coltype, notnull, dflt_value, pk in query_all(conn, f"PRAGMA table_info({table});"):
        # Normalize defaults for readability (None vs literal / function)
        default_str = "NULL" if dflt_value is None else str(dflt_value)
        print(f"{cid:2d} | {name:20s} | {coltype:12s} | notnull={bool(notnull)} | " f"pk={pk} | default={default_str}")

    # Indexes
    print("\n-- INDEXES (PRAGMA index_list)")
    # row: (seq, name, unique, origin, partial)
    for idx in query_all(conn, f"PRAGMA index_list({table});"):
        name = idx[1]
        unique = bool(idx[2])
        origin = idx[3]
        partial = bool(idx[4])
        print(f"name={name} | unique={unique} | origin={origin} | partial={partial}")

        # index columns
        cols = query_all(conn, f"PRAGMA index_info({name});")
        if cols:
            joined = ", ".join(c[2] for c in cols)  # (seqno, cid, name)
            print("  -> columns:", joined)

    # Foreign keys
    print("\n-- FOREIGN KEYS (PRAGMA foreign_key_list)")
    fks = query_all(conn, f"PRAGMA foreign_key_list({table});")
    if not fks:
        print("<none>")
    else:
        # row: (id, seq, table, from, to, on_update, on_delete, match)
        for r in fks:
            print(
                f"id={r[0]} seq={r[1]} | {r[3]} -> {r[2]}.{r[4]} " f"(on_update={r[5]}, on_delete={r[6]}, match={r[7]})"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect local SQLite schema")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--table", help="Inspect a single table by exact name")
    group.add_argument("--like", help="Inspect tables matching LIKE pattern, e.g. 'doc%%'")
    args = parser.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"DB file not found: {DB_PATH} (did you run `alembic upgrade head`?)")

    conn = sqlite3.connect(DB_PATH)
    try:
        if args.table:
            tables = [args.table]
        else:
            if args.like:
                rows = query_all(
                    conn,
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ? ORDER BY name;",
                    (args.like,),
                )
            else:
                rows = query_all(
                    conn,
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;",
                )
            tables = [r[0] for r in rows]

        if not tables:
            print("No tables found.")
            return

        print("== Tables ==")
        for t in tables:
            print("-", t)

        for t in tables:
            print_table_schema(conn, t)

        print("\nOK.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
