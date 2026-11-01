"""LLM-powered decision-support assistant (Claude).

"Ask your data": a business question becomes DuckDB SQL (Claude), the SQL is
checked by a read-only guard and run locally, and Claude explains the result in
plain English with a recommended action. Answers are grounded in the query
result, and the SQL is always shown so a human can verify it.

Without credentials the app still works in offline mode: curated questions
with hand-written SQL, and the rule-based insights brief.
"""

import json
import os
import re
from dataclasses import dataclass, field

import duckdb
import pandas as pd

from retail_bi import config
from retail_bi.warehouse import schema_description

MODEL = os.environ.get("RETAIL_BI_MODEL", "claude-opus-5-5")
MAX_ROWS = 500

FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|ATTACH|DETACH|COPY|EXPORT|IMPORT|PRAGMA|INSTALL|LOAD|CALL|SET|RESET|"
    r"CHECKPOINT|VACUUM|GRANT|REVOKE|TRUNCATE|REPLACE\s+INTO|READ_\w+|GLOB|SNIFF_CSV|HTTPFS)\b",
    re.IGNORECASE,
)

BUSINESS_NOTES = """
Business definitions (use these exactly):
- Currency is GBP (£). Data covers 2009-12-01 to 2011-12-09; December 2011 is a partial month.
- fact_sales has one row per invoice line. Sales have is_return = false and positive quantity;
  returns/cancellations have is_return = true and NEGATIVE quantity and line_revenue.
- Net revenue = SUM(line_revenue) over all lines (sales + returns). Gross revenue = SUM over sales only.
- An order = a distinct sales invoice (use v_orders for order-level questions: order_value, units, lines).
- customer_id is NULL for guest checkouts; exclude NULLs for customer-level questions.
- dim_product.product_family is a keyword-derived category; dim_customer.cohort_month is the first-purchase month.
- customer_segments has the RFM segment per customer (Champions, Loyal Customers, At Risk, New / Promising, Hibernating).
- daily_forecast has the next-28-day revenue forecast with an 80% interval.
"""

SQL_SYSTEM_PROMPT = """You are a senior data analyst for a UK online gift wholesaler. You translate business \
questions into a single DuckDB SQL query over the warehouse described below.

Rules:
- Return exactly one read-only query (SELECT or WITH ... SELECT). Never modify data or read files.
- Use only the tables and columns in the schema. Prefer clear column aliases (snake_case) and ROUND money to 2 dp.
- Aggregate rather than returning raw lines; keep results small (add ORDER BY and LIMIT 50 or less for rankings).
- Use DuckDB functions (DATE_TRUNC, STRFTIME, DATE_DIFF, FILTER clauses, window functions).
- If the question cannot be answered from this data, return an empty sql string and explain why.

Schema:
{schema}
{notes}"""

ANSWER_SYSTEM_PROMPT = """You are a senior data analyst presenting results to a business manager at a UK online \
gift wholesaler. Answer the question using ONLY the query result provided - never invent numbers. Lead with the \
direct answer in one or two sentences, add the one or two most useful supporting facts, then give one concrete, \
practical recommendation. Use £ for money. Keep it under 120 words. Plain markdown, no headings."""

BRIEF_SYSTEM_PROMPT = """You are the head of analytics at a UK online gift wholesaler writing for the leadership \
team. Using ONLY the facts in the JSON provided (never invent or extrapolate numbers), write a crisp briefing in \
markdown with three sections: 'Key findings' (4-5 bullets, each with a number), 'Risks to watch' (2-3 bullets) \
and 'Recommended actions for next quarter' (3-4 numbered, specific actions with the expected impact stated \
qualitatively). Under 300 words."""

SQL_SCHEMA = {
    "type": "object",
    "properties": {
        "sql": {"type": "string", "description": "One DuckDB SELECT query, or empty string if unanswerable"},
        "explanation": {"type": "string", "description": "One sentence on how the query answers the question"},
    },
    "required": ["sql", "explanation"],
    "additionalProperties": False,
}

EXAMPLE_QUESTIONS = {
    "Which 10 products earned the most net revenue?": """
        SELECT p.description, p.product_family, ROUND(SUM(f.line_revenue), 2) AS net_revenue
        FROM fact_sales f JOIN dim_product p ON f.stock_code = p.stock_code
        GROUP BY ALL ORDER BY net_revenue DESC LIMIT 10""",
    "How did revenue and orders change by quarter?": """
        SELECT DATE_TRUNC('quarter', order_date) AS quarter,
               ROUND(SUM(line_revenue), 2) AS net_revenue,
               COUNT(DISTINCT invoice) FILTER (WHERE NOT is_return) AS orders
        FROM fact_sales GROUP BY 1 ORDER BY 1""",
    "Which countries outside the UK have the highest average order value (min 20 orders)?": """
        SELECT country, COUNT(*) AS orders, ROUND(AVG(order_value), 2) AS avg_order_value,
               ROUND(SUM(order_value), 2) AS revenue
        FROM v_orders WHERE country <> 'United Kingdom'
        GROUP BY country HAVING COUNT(*) >= 20 ORDER BY avg_order_value DESC LIMIT 10""",
    "How much revenue do At Risk customers represent, and who are the top 10?": """
        SELECT customer_id, recency_days, frequency AS orders, ROUND(monetary, 2) AS lifetime_revenue,
               ROUND(SUM(monetary) OVER (), 2) AS all_at_risk_revenue,
               COUNT(*) OVER () AS at_risk_customers
        FROM customer_segments WHERE segment = 'At Risk'
        ORDER BY monetary DESC LIMIT 10""",
    "Which product categories have the highest return rate?": """
        SELECT p.product_family,
               ROUND(-SUM(f.line_revenue) FILTER (WHERE f.is_return), 2) AS returned_value,
               ROUND(100.0 * -SUM(f.line_revenue) FILTER (WHERE f.is_return)
                     / SUM(f.line_revenue) FILTER (WHERE NOT f.is_return), 2) AS return_rate_pct
        FROM fact_sales f JOIN dim_product p ON f.stock_code = p.stock_code
        GROUP BY 1 ORDER BY return_rate_pct DESC""",
    "What revenue is forecast for each of the next 4 weeks?": """
        SELECT DATE_TRUNC('week', date) AS week_start, ROUND(SUM(forecast), 2) AS forecast,
               ROUND(SUM(lower_80), 2) AS lower_80, ROUND(SUM(upper_80), 2) AS upper_80
        FROM daily_forecast GROUP BY 1 ORDER BY 1""",
}


class SQLGuardError(ValueError):
    pass


def guard_sql(sql: str) -> str:
    """Allow a single read-only SELECT/WITH statement; reject anything that writes or touches files."""
    cleaned = re.sub(r"--[^\n]*", " ", sql).strip().rstrip(";").strip()
    if not cleaned:
        raise SQLGuardError("Empty query.")
    if ";" in cleaned:
        raise SQLGuardError("Only one SQL statement is allowed.")
    if not re.match(r"^(SELECT|WITH)\b", cleaned, re.IGNORECASE):
        raise SQLGuardError("Only SELECT queries are allowed.")
    match = FORBIDDEN.search(cleaned)
    if match:
        raise SQLGuardError(f"Keyword not allowed in read-only mode: {match.group(0)}")
    return cleaned


def read_only_connection() -> duckdb.DuckDBPyConnection:
    # Read-only file + no external access: even a query that slipped past the guard cannot write or read files.
    return duckdb.connect(str(config.WAREHOUSE_DB), read_only=True, config={"enable_external_access": False})


def run_query(sql: str) -> pd.DataFrame:
    safe = guard_sql(sql)
    with read_only_connection() as con:
        return con.sql(safe).limit(MAX_ROWS).df()


def warehouse_schema() -> str:
    with read_only_connection() as con:
        return schema_description(con)


def _has_credentials() -> bool:
    # The SDK reads an API key / auth token from the environment, or a profile saved by `ant auth login`.
    if any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE")):
        return True
    return os.path.isdir(os.path.expanduser("~/.config/anthropic"))


def _client():
    """Return an Anthropic client, or None if the SDK or credentials are unavailable."""
    if not _has_credentials():
        return None
    try:
        import anthropic

        return anthropic.Anthropic()
    except (ImportError, Exception):
        return None


def llm_available() -> bool:
    return _client() is not None


@dataclass
class Answer:
    question: str
    sql: str = ""
    explanation: str = ""
    result: pd.DataFrame = field(default_factory=pd.DataFrame)
    narrative: str = ""
    error: str = ""
    attempts: int = 0


def _create(client, system: str, user: str, effort: str, max_tokens: int = 8000, json_schema: dict | None = None):
    import anthropic

    output_config = {"effort": effort}
    if json_schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": json_schema}
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            # The schema/system prompt is identical on every call, so cache it.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config=output_config,
            # If a safety classifier declines, retry server-side on Anthropic's recommended fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as exc:
        raise RuntimeError("Claude API authentication failed - check ANTHROPIC_API_KEY.") from exc
    except anthropic.RateLimitError as exc:
        raise RuntimeError("Claude API rate limit reached - wait a minute and try again.") from exc
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"Claude API error ({exc.status_code}): {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise RuntimeError("Could not reach the Claude API - check your internet connection.") from exc

    if response.stop_reason == "refusal":
        raise RuntimeError("The model declined this request. Try rephrasing the question.")
    text = "".join(block.text for block in response.content if block.type == "text")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("The response was cut off (max_tokens). Try a narrower question.")
    return text


def ask(question: str, max_attempts: int = 2) -> Answer:
    """Question -> SQL (Claude) -> guarded local execution -> grounded explanation (Claude)."""
    answer = Answer(question=question)
    client = _client()
    if client is None:
        answer.error = "No Claude API credentials found. Set ANTHROPIC_API_KEY to enable free-form questions."
        return answer

    system = SQL_SYSTEM_PROMPT.format(schema=warehouse_schema(), notes=BUSINESS_NOTES)
    prompt = f"Question: {question}"
    for attempt in range(1, max_attempts + 1):
        answer.attempts = attempt
        try:
            payload = json.loads(_create(client, system, prompt, effort="medium", json_schema=SQL_SCHEMA))
        except (RuntimeError, json.JSONDecodeError) as exc:
            answer.error = str(exc)
            return answer
        answer.sql, answer.explanation = payload["sql"].strip(), payload["explanation"]
        if not answer.sql:
            answer.error = answer.explanation or "This question cannot be answered from the available data."
            return answer
        try:
            answer.result = run_query(answer.sql)
            answer.error = ""
            break
        except (SQLGuardError, duckdb.Error) as exc:
            # Self-correction: show the model its own query and the error, once.
            answer.error = f"{type(exc).__name__}: {exc}"
            prompt = (
                f"Question: {question}\n\nYour previous query failed.\nQuery:\n{answer.sql}\n\n"
                f"Error:\n{answer.error}\n\nReturn a corrected query."
            )
    if answer.error:
        return answer

    preview = answer.result.head(50).to_csv(index=False)
    user = (
        f"Question: {question}\n\nSQL used:\n{answer.sql}\n\n"
        f"Result ({len(answer.result)} rows, first 50 shown as CSV):\n{preview}"
    )
    try:
        answer.narrative = _create(client, ANSWER_SYSTEM_PROMPT, user, effort="low", max_tokens=4000)
    except RuntimeError as exc:
        answer.error = str(exc)
    return answer


def run_example(question: str) -> Answer:
    """Offline mode: run a curated question with hand-written SQL."""
    answer = Answer(question=question, sql=EXAMPLE_QUESTIONS[question].strip(), explanation="Curated example query.")
    answer.result = run_query(answer.sql)
    return answer


def ai_brief(facts: dict) -> str:
    """Leadership briefing written by Claude from the computed facts only."""
    client = _client()
    if client is None:
        raise RuntimeError("No Claude API credentials found. Set ANTHROPIC_API_KEY to generate the AI brief.")
    return _create(client, BRIEF_SYSTEM_PROMPT, json.dumps(facts, indent=2, default=str), effort="medium")
