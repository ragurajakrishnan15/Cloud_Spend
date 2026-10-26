"""Prompt construction for the optional LLM layer. Only ledger figures, small result tables and limitations are sent:
never credentials, connection settings or raw database access."""

from __future__ import annotations

import json

from cloudspend.ai.ledger import Ledger
from cloudspend.ai.tools import ToolResult

SYSTEM_PROMPT = """You are a finance analyst assistant for a cloud-spend dashboard. The data is SYNTHETIC.
Rules:
- Quote numbers ONLY from the "figures" list, exactly as given. The "tables" are context for names and ranking only: do not
  quote any number that appears only in a table.
- Do not calculate new numbers, estimate savings, round differently, or mention any number that is not provided.
- Do not claim a cause for any change or anomaly; say the data shows what changed, not why.
- If something is missing or unavailable, say so plainly instead of guessing.
- Be concise (under 200 words), plain language, no markdown tables."""

MAX_TABLE_ROWS = 10


def build_user_prompt(question: str, intent: str, results: list[ToolResult], ledger: Ledger, limitations: list[str]) -> str:
    figures = [{"id": f.id, "label": f.label, "value": ledger.fmt(f.id)} for f in ledger.figures()]
    tables = {f"{r.tool}.{name}": df.head(MAX_TABLE_ROWS).astype(str).to_dict("records")
              for r in results for name, df in r.tables.items()}
    payload = {"intent": intent, "question": question, "figures": figures, "tables": tables, "limitations": limitations}
    return "Answer the question using only this data.\n" + json.dumps(payload, default=str)
