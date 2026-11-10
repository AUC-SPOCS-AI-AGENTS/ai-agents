"""
llm.py - the AI side of the resume agent (Homework 2 version).

Flow for every chat message (handle_chat):
  1. The Orchestrator writes a PLAN as JSON (route + reason + steps).
  2. Our code reads the plan as DATA with json.loads and checks it.
     (No eval(): model output is never run as Python here.)
  3. Each step runs in order. A later step receives the earlier step's
     result, which is what makes two-step requests work.
  4. One final model call turns the results into a short, honest reply.
  5. A trace is printed in the terminal for every message.
"""

import json
import os
import re
import uuid

import requests
from jinja2 import Template

from flask_app.utils.embeddings import EmbeddingError
from flask_app.utils.semantic_search import semantic_search, SEARCHABLE_TABLES

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"   # used when CHAT_MODEL is not set in .env


# --------------------------------------------------------------------------
# Talking to the chat model (from HW0)
# --------------------------------------------------------------------------

def send_message(user_message, system_prompt="You are a helpful assistant."):
    """Send one message to the chat model and return its reply text."""
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key or api_key == 'paste-your-key-here':
        return "⚠️ No API key found. Add your OpenRouter key to the .env file and restart the app."

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8080",
    }
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    try:
        response = requests.post(
            OPENROUTER_URL,
            headers=headers,
            json={"model": os.getenv('CHAT_MODEL') or DEFAULT_MODEL, "messages": messages},
            timeout=60,
        )
        result = response.json()
    except Exception as error:
        return f"⚠️ Could not reach OpenRouter: {error}"

    if 'error' in result:
        return f"⚠️ OpenRouter error: {result['error'].get('message', 'Unknown API error')}"
    if 'choices' not in result:
        return f"⚠️ Unexpected response from OpenRouter: {result}"
    return result['choices'][0]['message']['content']


# --------------------------------------------------------------------------
# Expert prompts (from HW1)
# --------------------------------------------------------------------------

MASTER_TEMPLATE = Template("""\
You are a {{ role }}, an expert in {{ domain }}.

{{ specific_instructions }}
{% if background_context %}
Context:
{{ background_context }}
{% endif %}
{% if few_shot_examples %}
Examples:
{{ few_shot_examples }}
{% endif %}
Request: {{ request }}
""", trim_blocks=True, lstrip_blocks=True)


def fill_template(role, domain, specific_instructions, request,
                  background_context="", few_shot_examples=""):
    """Render MASTER_TEMPLATE into one expert's system prompt."""
    return MASTER_TEMPLATE.render(
        role=role,
        domain=domain,
        specific_instructions=specific_instructions,
        background_context=background_context,
        few_shot_examples=few_shot_examples,
        request=request,
    ).strip()


def strip_code_fences(text):
    """
    Models often wrap answers in ```json ... ``` or ```sql ... ```.
    Remove that wrapper so json.loads / SQLite get the content itself.
    """
    text = text.strip()
    match = re.match(r"^```[a-zA-Z]*\s*(.*?)\s*```$", text, re.DOTALL)
    return match.group(1).strip() if match else text


def ask_expert(db, role, message):
    """Build the expert's prompt from llm_roles, call the model, clean the output."""
    config = db.getLLMRoles()[role]
    background_context = config['background_context'] or ""
    if role == "Content Expert":
        background_context += "\n" + db.getResumeText()

    system_prompt = fill_template(
        role=config['role'],
        domain=config['domain'],
        specific_instructions=config['specific_instructions'],
        background_context=background_context,
        few_shot_examples=config['few_shot_examples'] or "",
        request=message,
    )
    return strip_code_fences(send_message(message, system_prompt))


# --------------------------------------------------------------------------
# The trace: a short log of what happened for every message
# --------------------------------------------------------------------------

class Trace:
    """Prints one line per event, all tagged with the same request ID."""

    def __init__(self, user_message):
        self.request_id = uuid.uuid4().hex[:6]
        print(f"\n[{self.request_id}] ===== new request =====")
        self.log("user", user_message)

    def log(self, label, text):
        print(f"[{self.request_id}] {label:10} | {text}")


# --------------------------------------------------------------------------
# Reading and checking the Orchestrator's plan
# --------------------------------------------------------------------------

ALLOWED_ROUTES = {"exact", "semantic", "two_step", "write", "content"}
ALLOWED_EXPERTS = {"Semantic Search", "Database Read Expert",
                   "Database Write Expert", "Content Expert"}
MAX_STEPS = 3


def parse_plan(plan_text):
    """
    Read the Orchestrator's plan as DATA (json.loads, never eval) and check
    every part of it. Returns (route, reason, steps) or raises ValueError.
    """
    plan = json.loads(plan_text)          # raises ValueError if it isn't JSON
    if not isinstance(plan, dict):
        raise ValueError("the plan must be a JSON object")

    route = plan.get("route")
    reason = str(plan.get("reason", "")).strip()
    steps = plan.get("steps")

    if route not in ALLOWED_ROUTES:
        raise ValueError(f"unknown route {route!r}")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise ValueError(f"steps must be a list of 1 to {MAX_STEPS} steps")

    for number, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError(f"step {number} is not an object")
        expert = step.get("expert")
        if expert not in ALLOWED_EXPERTS:
            raise ValueError(f"step {number}: unknown expert {expert!r}")
        if expert == "Semantic Search":
            if not str(step.get("query", "")).strip():
                raise ValueError(f"step {number}: search needs a query")
            tables = step.get("tables") or SEARCHABLE_TABLES
            if not isinstance(tables, list) or any(t not in SEARCHABLE_TABLES for t in tables):
                raise ValueError(f"step {number}: unknown table in {tables!r}")
            step["tables"] = tables
        elif not str(step.get("message", "")).strip():
            raise ValueError(f"step {number}: {expert} needs a message")

    return route, reason, steps


# --------------------------------------------------------------------------
# Running each kind of step
# --------------------------------------------------------------------------

NAME_COLUMN = {          # table -> (id column, name column)
    'institutions': ('inst_id', 'name'),
    'positions': ('position_id', 'title'),
    'experiences': ('experience_id', 'name'),
    'skills': ('skill_id', 'name'),
}


def record_name(db, table, record_id):
    """The record's exact stored name, so a later SQL step can use it."""
    id_column, name_column = NAME_COLUMN[table]
    rows = db.query(f"SELECT {name_column} AS name FROM {table} WHERE {id_column} = ?",
                    (record_id,))
    return rows[0]['name'] if rows else ''


def run_semantic_step(db, step, trace):
    """Search by meaning and report the ranked results with their scores."""
    try:
        matches, all_scored = semantic_search(db, step["query"], tables=step["tables"])
    except EmbeddingError as error:
        trace.log("search", f"FAILED: {error}")
        return "ERROR: search by meaning is unavailable right now (the embedding call failed)."

    trace.log("search", f'query="{step["query"]}" tables={step["tables"]}')
    for result in all_scored[:5]:
        status = "MATCH" if result in matches else "below cut-off"
        trace.log("search", f"  {result['score']:.3f}  {result['table']} #{result['id']}  "
                            f"{result['text'][:55]}  ({status})")

    if not matches:
        return "NOT FOUND: no record matched closely enough."
    lines = [
        f"{m['table']} #{m['id']} name='{record_name(db, m['table'], m['id'])}' "
        f"(score {m['score']:.2f}): {m['text']}"
        for m in matches
    ]
    return "Found:\n" + "\n".join(lines)


def execute_read_query(db, sql, trace):
    """Run the Read Expert's SQL. Only a single SELECT is allowed."""
    if not sql.strip().upper().startswith("SELECT"):
        trace.log("read", "REFUSED: not a SELECT")
        return "Sorry, I couldn't safely answer that question."
    try:
        rows = db.query(sql)
    except Exception as error:
        trace.log("read", f"FAILED: {error}")
        return "Sorry, that question couldn't be answered."
    trace.log("read", f"rows returned: {rows}")
    return str(rows) if rows else "NOT FOUND: the query returned no rows."


def execute_write_action(db, generated_code, trace):
    """
    TEMPORARY (Phase 4): still the HW1 exec() version.
    Phase 5 replaces this with allowed operations + approval.
    """
    local_vars = {}
    try:
        exec(generated_code, {"db": db, "NULL": None}, local_vars)
    except Exception as error:
        trace.log("write", f"FAILED: {error}")
        return "Operation was unsuccessful."
    return local_vars.get("outcome", "Operation was unsuccessful.")


def run_step(db, step, previous_result, trace):
    """Run one step. `previous_result` is what the step before it produced."""
    expert = step["expert"]
    if expert == "Semantic Search":
        return run_semantic_step(db, step, trace)

    message = step["message"]
    if previous_result:
        message += ("\n\nResult of the previous step (use these exact names):\n"
                    + previous_result)

    output = ask_expert(db, expert, message)
    trace.log(expert.split()[1].lower() if expert.startswith("Database") else "content",
              f"generated: {output}")
    if output.startswith("⚠️"):
        return output
    if expert == "Database Read Expert":
        return execute_read_query(db, output, trace)
    if expert == "Database Write Expert":
        return execute_write_action(db, output, trace)
    return output                              # Content Expert


# --------------------------------------------------------------------------
# One chat message, start to finish
# --------------------------------------------------------------------------

def synthesize(user_message, results):
    """One final model call that turns the step results into a short reply."""
    steps_summary = "\n\n".join(f"{expert}:\n{result}" for expert, result in results)
    instructions = (
        f'The user asked: "{user_message}"\n\n'
        f"Here is what each step found or did:\n{steps_summary}\n\n"
        "Write ONE short, clear reply using ONLY these results. Rules:\n"
        "- If a result says NOT FOUND, clearly say it was not found. Never invent a record.\n"
        "- If a result starts with ERROR, say that search is unavailable right now.\n"
        "- If a Database Write Expert result is present, reuse it word for word.\n"
        "- Never mention SQL, Python, code, scores or these internal steps."
    )
    return send_message(user_message, instructions)


def handle_chat(db, user_message):
    """Handle one chat message: plan -> check -> run steps -> reply, with a trace."""
    trace = Trace(user_message)

    plan_text = ask_expert(db, "Orchestrator", user_message)
    trace.log("plan", plan_text)
    try:
        route, reason, steps = parse_plan(plan_text)
    except ValueError as error:
        trace.log("plan", f"REJECTED: {error}")
        trace.log("outcome", "no steps were run")
        return "Sorry, I couldn't plan a response to that."

    trace.log("route", f"{route} - {reason}")
    results, previous_result = [], ""
    for number, step in enumerate(steps, start=1):
        trace.log("step", f"{number}/{len(steps)} {step['expert']}")
        previous_result = run_step(db, step, previous_result, trace)
        results.append((step["expert"], previous_result))

    reply = synthesize(user_message, results)
    trace.log("outcome", reply.replace("\n", " ")[:150])
    return reply


def handle_ai_chat_request(db, role, message):
    """Kept for compatibility with socket_events.py (HW1 called this)."""
    if role == "Orchestrator":
        return handle_chat(db, message)
    return send_message(message)
