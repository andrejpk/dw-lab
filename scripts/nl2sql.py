"""
Simple Copilot SDK-powered NL2SQL CLI for the local DuckDB warehouse.

Usage:
    python scripts/nl2sql.py
    python scripts/nl2sql.py --question "How many store sales rows are there?"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
from copilot import CopilotClient
from copilot.session_events import AssistantMessageData


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "data" / "warehouse" / "tpcds.duckdb"
PREFERRED_MODELS = ("gpt-5.5", "gpt-5.4", "gpt-5.3-codex", "claude-sonnet-4.6", "claude-sonnet-4.5")
MAX_SCHEMA_CHARS = 20_000


class NL2SQLError(Exception):
    """Raised when Copilot returns unusable SQL."""


def connect_read_only(db_path: Path) -> duckdb.DuckDBPyConnection:
    if not db_path.exists():
        raise FileNotFoundError(
            f"DuckDB file not found: {db_path}. Run scripts/load_tpcds.py first."
        )
    return duckdb.connect(str(db_path), read_only=True)


def load_schema(con: duckdb.DuckDBPyConnection) -> str:
    rows = con.execute(
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'main'
        ORDER BY table_name, ordinal_position
        """
    ).fetchall()
    if not rows:
        raise NL2SQLError("No tables found in the DuckDB database.")

    tables: dict[str, list[str]] = {}
    for table_name, column_name, data_type in rows:
        tables.setdefault(table_name, []).append(f"{column_name} {data_type}")

    lines = [
        f"- {table_name}({', '.join(columns)})"
        for table_name, columns in tables.items()
    ]
    schema = "\n".join(lines)
    if len(schema) > MAX_SCHEMA_CHARS:
        return schema[:MAX_SCHEMA_CHARS] + "\n... schema truncated ..."
    return schema


async def choose_model(client: CopilotClient, requested_model: str | None) -> str | None:
    if requested_model:
        return requested_model

    models = await client.list_models()
    available = {model.id for model in models}
    for model_id in PREFERRED_MODELS:
        if model_id in available:
            return model_id
    if models:
        return models[0].id
    return None


async def ask_copilot(prompt: str, model: str | None, timeout: float) -> str:
    async with CopilotClient(working_directory=str(REPO_ROOT)) as client:
        selected_model = await choose_model(client, model)
        async with await client.create_session(
            model=selected_model,
            system_message={
                "mode": "append",
                "content": (
                    "You generate DuckDB SQL for local analytical questions. "
                    "Do not use tools. Return exactly the requested format."
                ),
            },
        ) as session:
            event = await session.send_and_wait(prompt, timeout=timeout)

    if event is None or not isinstance(event.data, AssistantMessageData):
        raise NL2SQLError("Copilot did not return a SQL response.")
    return event.data.content


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise NL2SQLError(f"Copilot returned non-JSON output:\n{text}")
        value = json.loads(match.group(0))

    if not isinstance(value, dict):
        raise NL2SQLError("Copilot JSON response must be an object.")
    return value


def normalize_sql(sql: str) -> str:
    query = sql.strip()
    if query.endswith(";"):
        query = query[:-1].strip()
    if ";" in query:
        raise NL2SQLError("Refusing SQL containing multiple statements.")
    if not re.match(r"^(select|with)\b", query, flags=re.IGNORECASE):
        raise NL2SQLError("Only read-only SELECT or WITH queries are allowed.")
    return query


def generate_prompt(question: str, schema: str, row_limit: int) -> str:
    return f"""
Generate one DuckDB SQL query to answer the user's question.

Rules:
- Use only the tables and columns in the schema.
- Return JSON only, with keys "sql" and "notes".
- The SQL must be a single read-only SELECT or WITH query.
- Prefer aggregation for direct numeric questions.
- Add a LIMIT of {row_limit} for detail/listing queries unless the user asks for a different limit.

Schema:
{schema}

Question:
{question}
""".strip()


def execute_query(
    con: duckdb.DuckDBPyConnection, query: str, row_limit: int
) -> tuple[list[str], list[tuple[Any, ...]], bool]:
    limited_query = f"SELECT * FROM ({query}) AS nl2sql_result LIMIT {row_limit + 1}"
    cursor = con.execute(limited_query)
    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchall()
    truncated = len(rows) > row_limit
    if truncated:
        rows = rows[:row_limit]
    return columns, rows, truncated


def format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def format_table(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    if not rows:
        return "(no rows)"

    rendered = [[format_value(value) for value in row] for row in rows]
    widths = [
        max(len(str(column)), *(len(row[i]) for row in rendered))
        for i, column in enumerate(columns)
    ]
    header = " | ".join(str(column).ljust(widths[i]) for i, column in enumerate(columns))
    separator = "-+-".join("-" * width for width in widths)
    body = [
        " | ".join(row[i].ljust(widths[i]) for i in range(len(columns)))
        for row in rendered
    ]
    return "\n".join([header, separator, *body])


def answer_from_result(
    columns: Sequence[str], rows: Sequence[Sequence[Any]], truncated: bool
) -> str:
    if not rows:
        return "No matching rows."
    if len(rows) == 1 and len(columns) == 1:
        return f"{columns[0]}: {format_value(rows[0][0])}"

    suffix = "\n\n(Result truncated.)" if truncated else ""
    return f"{format_table(columns, rows)}{suffix}"


async def answer_question(
    question: str, db_path: Path, model: str, row_limit: int, timeout: float
) -> None:
    with connect_read_only(db_path) as con:
        schema = load_schema(con)
        prompt = generate_prompt(question, schema, row_limit)
        response = await ask_copilot(prompt, model, timeout)
        payload = extract_json_object(response)
        raw_sql = payload.get("sql")
        if not isinstance(raw_sql, str):
            raise NL2SQLError(f"Copilot response missing string 'sql': {response}")

        query = normalize_sql(raw_sql)
        columns, rows, truncated = execute_query(con, query, row_limit)

    print("\nSQL:")
    print(query)
    print("\nAnswer:")
    print(answer_from_result(columns, rows, truncated))

    notes = payload.get("notes")
    if isinstance(notes, str) and notes.strip():
        print(f"\nNotes: {notes.strip()}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ask natural-language questions of DuckDB.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="DuckDB database path.")
    parser.add_argument(
        "--model",
        help="Copilot model to use. Defaults to the first available preferred model.",
    )
    parser.add_argument("--row-limit", type=int, default=25, help="Rows to print for tabular answers.")
    parser.add_argument("--timeout", type=float, default=120.0, help="Copilot response timeout seconds.")
    parser.add_argument("--question", "-q", help="Ask one question and exit.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    questions = [args.question] if args.question else None

    try:
        if questions is not None:
            asyncio.run(
                answer_question(
                    questions[0], args.db, args.model, args.row_limit, args.timeout
                )
            )
            return 0

        print("DuckDB NL2SQL. Press Ctrl+C or enter a blank question to exit.")
        while True:
            question = input("\nQuestion> ").strip()
            if not question:
                return 0
            asyncio.run(
                answer_question(question, args.db, args.model, args.row_limit, args.timeout)
            )
    except (duckdb.Error, FileNotFoundError, NL2SQLError, TimeoutError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
