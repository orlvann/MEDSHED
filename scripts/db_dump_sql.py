"""
SQLite SQL dump helper for local dev.

Usage:
  # schema-only (DDL)
  python scripts/db_dump_sql.py

  # full dump (DDL + INSERTs)
  python scripts/db_dump_sql.py --full

  # write to file
  python scripts/db_dump_sql.py --out dump.sql
  python scripts/db_dump_sql.py --full --out dump_full.sql
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Iterable

DB_PATH = Path("backend/db/sqlite.db")  # fixed dev path


def write_lines(lines: Iterable[str], out_path: Path | None) -> None:
    text = "\n".join(lines) + "\n"
    if out_path:
        out_path.write_text(text, encoding="utf-8")
        print(f"Wrote {out_path} ({len(text)} bytes)")
    else:
        print(text, end="")


def dump_schema(conn: sqlite3.Connection) -> list[str]:
    """Return DDL statements for tables, indexes, views, triggers (ordered)."""
    cur = conn.cursor()
    try:
        rows = cur.execute(
            """
            SELECT type, name, tbl_name, sql
            FROM sqlite_master
            WHERE sql IS NOT NULL
              AND type IN ('table','index','view','trigger')
            ORDER BY
              CASE type
                WHEN 'table' THEN 1
                WHEN 'index' THEN 2
                WHEN 'view' THEN 3
                WHEN 'trigger' THEN 4
              END,
              name
            """
        ).fetchall()
    finally:
        cur.close()

    lines: list[str] = [
        "-- Schema-only dump (SQLite)",
        "PRAGMA foreign_keys=OFF;",
        "",
    ]
    for typ, name, tbl, sql in rows:
        lines.append(f"-- {typ.upper()}: {name} (table={tbl})")
        lines.append(sql.rstrip(";") + ";")
        lines.append("")  # blank line between objects
    lines.append("-- End of schema")
    return lines


def dump_full(conn: sqlite3.Connection) -> list[str]:
    """Return a full SQL dump (schema + data) using iterdump()."""
    lines = ["-- Full dump (schema + data)", "PRAGMA foreign_keys=OFF;", ""]
    lines.extend(list(conn.iterdump()))
    lines.append("-- End of full dump")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump SQLite DB to SQL")
    parser.add_argument("--full", action="store_true", help="include data (INSERTs)")
    parser.add_argument("--out", type=Path, help="output file path (defaults to stdout)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"DB file not found: {DB_PATH} (run `make db-upgrade` first)")

    conn = sqlite3.connect(DB_PATH)
    try:
        lines = dump_full(conn) if args.full else dump_schema(conn)
        write_lines(lines, args.out)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
