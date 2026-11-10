"""
llm.py — sends messages to an AI language model via the OpenRouter API.

This file is the bridge between your Flask app and an AI model.
When a student types a message in the chat, it travels here, gets sent to
OpenRouter, and the AI's reply comes back.

KEY CONCEPTS:
  - API (Application Programming Interface): a way for two programs to talk
    to each other over the internet. OpenRouter exposes an API we can call.
  - HTTP POST request: sending data to a server (like submitting a form).
  - System prompt: instructions given to the AI before the conversation starts.

HW2 CHANGES (Step 4 — choose the right search, handle two-step requests):
  - The Orchestrator now returns its plan as JSON. We read it with json.loads()
    (data, never code) and check it: unknown experts or tables are rejected.
    -> eval() is gone.
  - New step type "Semantic Search": embeds the question and compares it with
    the stored embeddings (see embeddings.py). Results are ranked, with scores.
  - Dependent steps: every step receives the results of the steps before it,
    so "What did I do at MSU?" = search resolves "MSU" -> Read Expert uses
    "Michigan State University" in its SQL.
  - If a search finds nothing, we stop and say "not found" (no invented records).
  - Model output is cleaned of ``` code fences before it is used.
  - A short trace is printed for every request (Step 6 will extend it).

HW2 CHANGES (Step 5 — ask before destructive changes):
  - exec() is gone. The Write Expert returns JSON: one allowed operation + values.
    operations.py checks it and is the ONLY code that writes. Its execute()
    refuses to run a destructive action without approval (ApprovalRequired).
  - handle_user_message() is the new entry point for the chat. It remembers one
    pending action per user and matches the answer:
        yes            -> run exactly the stored action (the model is not asked again)
        no             -> cancel, nothing changes
        anything else  -> the pending action is CANCELLED (rule in the report);
                          an unclear reply ("maybe") gets "I need a clear yes or no",
                          a new request is handled normally. So a later "yes"
                          can never approve an old action.
"""

import os
import json
import re
import uuid
import requests
from jinja2 import Template

from flask_app.utils.embeddings import search, get_min_score, EmbeddingError
from flask_app.utils.operations import (propose, execute, OperationError, ApprovalRequired)

# The URL we send our messages to.
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Which chat model to use (read from .env, with the HW1 model as the fallback).
DEFAULT_MODEL = os.getenv("CHAT_MODEL", "openai/gpt-4o-mini")

# ----------------------------------------------------------------------
# What the Orchestrator is allowed to ask for (HW2 Step 4)
# ----------------------------------------------------------------------
ALLOWED_EXPERTS = {
    "Database Read Expert",    # exact questions -> SQL SELECT
    "Semantic Search",         # fuzzy questions -> search by meaning (no LLM)
    "Database Write Expert",   # changes to the data
    "Content Expert",          # general questions about the resume text
}
SEARCHABLE_TABLES = ["institutions", "positions", "experiences", "skills"]
MAX_STEPS = 4                  # a plan longer than this is rejected

# One shared template for every expert's system prompt.
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
    """Render MASTER_TEMPLATE into one expert's full system prompt."""
    return MASTER_TEMPLATE.render(
        role=role,
        domain=domain,
        specific_instructions=specific_instructions,
        background_context=background_context,
        few_shot_examples=few_shot_examples,
        request=request,
    ).strip()


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------

def clean_model_output(text):
    """Remove ```json ... ``` code fences that models often wrap around their answer."""
    text = (text or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def trace(request_id, message):
    """One trace line in the terminal. Never print the API key here."""
    print(f"[trace {request_id}] {message}")


# ----------------------------------------------------------------------
# Experts
# ----------------------------------------------------------------------

def handle_ai_chat_request(db, role, message, request_id=None):
    if role is None:
        return send_message(message)

    config = db.getLLMRoles()[role]
    background_context = config['background_context'] or ""
    if role == "Content Expert":
        background_context += "\n" + db.getResumeText()
    if role == "Database Write Expert":
        background_context += "\n" + current_data_for_writer(db)

    system_prompt = fill_template(
        role=config['role'],
        domain=config['domain'],
        specific_instructions=config['specific_instructions'],
        background_context=background_context,
        few_shot_examples=config['few_shot_examples'] or "",
        request=message,
    )
    output = clean_model_output(send_message(message, system_prompt))
    print(f"[{role}] generated:\n{output}\n")

    if role == "Database Read Expert":
        return execute_read_query(db, output)
    if role == "Database Write Expert":
        return execute_write_action(db, output, request_id)
    if role == "Orchestrator":
        return run_orchestrator_plan(db, message, output, request_id)
    return output


def execute_read_query(db, sql):
    if not sql.strip().upper().startswith("SELECT"):
        return "Sorry, I couldn't safely answer that question."
    try:
        return str(db.query(sql))
    except Exception as error:
        print(f"Read Expert query failed: {error}")
        return "Sorry, that question couldn't be answered."


def current_data_for_writer(db):
    """The exact names the Write Expert may use (so it never guesses an ID or a name)."""
    experiences = ", ".join(f"'{r['name']}'" for r in db.query("SELECT name FROM experiences"))
    skills = ", ".join(
        f"'{r['skill']}' (in '{r['experience']}')"
        for r in db.query("SELECT s.name AS skill, e.name AS experience FROM skills s "
                          "LEFT JOIN experiences e ON s.experience_id = e.experience_id")
    )
    return f"Current experiences: {experiences}\nCurrent skills: {skills or 'none'}"


def execute_write_action(db, output, request_id=None):
    """
    The Write Expert only CHOOSES an operation (JSON). It never runs code.
    propose() checks it; execute() performs it, or raises ApprovalRequired
    for a destructive action (handled in handle_user_message).
    """
    try:
        choice = json.loads(output)
        if not isinstance(choice, dict):
            raise ValueError("not a JSON object")
    except (ValueError, json.JSONDecodeError):
        trace(request_id, f"write rejected: not valid JSON: {output!r}")
        return "Sorry, I couldn't understand that change. Nothing was changed."

    name = choice.get("operation")
    if name == "none":
        trace(request_id, f"write: no allowed operation fits ({choice.get('reason', '')})")
        return "That isn't a change I'm allowed to make. Nothing was changed."

    try:
        action = propose(db, name, choice.get("args") or {})
    except OperationError as error:
        trace(request_id, f"write rejected: {error}")
        return f"I couldn't do that: {error} Nothing was changed."

    trace(request_id, f"write proposed: {action.summary()} | destructive={action.destructive}")
    try:
        outcome = execute(db, action)      # destructive -> raises ApprovalRequired, nothing runs
    except OperationError as error:
        trace(request_id, f"write failed: {error}")
        return f"I couldn't do that: {error} Nothing was changed."
    trace(request_id, f"write done (safe operation): {outcome}")
    return outcome


def run_semantic_search(db, step, request_id):
    """
    Search by meaning. Returns (found: bool, text for the next steps).
    The trace shows the top scores even when nothing passes the cut-off,
    so you can always see WHY something was or wasn't found.
    """
    query, tables = step["query"], step["tables"]
    cutoff = get_min_score()
    trace(request_id, f"search by meaning: {query!r} in {tables} (cut-off {cutoff})")

    ranked = search(db, query, tables=tables, top_k=5, min_score=0)   # may raise EmbeddingError
    for r in ranked:
        mark = "MATCH" if r['score'] >= cutoff else "below cut-off"
        trace(request_id, f"   {r['score']:.3f}  {r['table']} #{r['record_id']}  {r['text'][:60]}  ({mark})")

    matches = [r for r in ranked if r['score'] >= cutoff]
    if not matches:
        return False, f"NOT FOUND: nothing in the resume matches {query!r}."

    lines = [f"Search results for {query!r} (most similar first):"]
    for r in matches:
        lines.append(f"- {r['table']} #{r['record_id']}: {r['text']} (score {r['score']:.2f})")
    return True, "\n".join(lines)


# ----------------------------------------------------------------------
# The Orchestrator: plan as JSON -> checked -> run step by step
# ----------------------------------------------------------------------

def parse_plan(plan_text):
    """
    Read the Orchestrator's plan as DATA (json.loads), never as code.
    Raises ValueError if anything is missing or not allowed.
    """
    plan = json.loads(clean_model_output(plan_text))
    if not isinstance(plan, dict):
        raise ValueError("the plan is not a JSON object")

    steps = plan.get("steps")
    if not isinstance(steps, list) or not (1 <= len(steps) <= MAX_STEPS):
        raise ValueError(f"the plan must have 1 to {MAX_STEPS} steps")

    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("every step must be a JSON object")
        expert = step.get("expert")
        if expert not in ALLOWED_EXPERTS:
            raise ValueError(f"unknown expert: {expert!r}")

        if expert == "Semantic Search":
            query = step.get("query")
            if not isinstance(query, str) or not query.strip():
                raise ValueError("a Semantic Search step needs a 'query'")
            tables = step.get("tables") or SEARCHABLE_TABLES
            if not isinstance(tables, list) or any(t not in SEARCHABLE_TABLES for t in tables):
                raise ValueError(f"unknown table in {tables!r}")
            step["tables"] = tables
        else:
            message = step.get("message")
            if not isinstance(message, str) or not message.strip():
                raise ValueError(f"a {expert} step needs a 'message'")

    plan["route"] = str(plan.get("route", "unknown"))
    plan["reason"] = str(plan.get("reason", ""))
    return plan


def run_orchestrator_plan(db, original_request, plan_text, request_id=None):
    request_id = request_id or uuid.uuid4().hex[:6]

    try:
        plan = parse_plan(plan_text)
    except (ValueError, json.JSONDecodeError) as error:
        trace(request_id, f"plan rejected: {error} | raw plan: {plan_text!r}")
        return "Sorry, I couldn't plan a response to that."

    trace(request_id, f"route = {plan['route']} | reason: {plan['reason']}")

    results = []          # (expert, what was asked, result text)
    for number, step in enumerate(plan["steps"], start=1):
        expert = step["expert"]

        if expert == "Semantic Search":
            try:
                found, text = run_semantic_search(db, step, request_id)
            except EmbeddingError as error:
                trace(request_id, f"step {number}: search FAILED: {error}")
                return ("⚠️ Search by meaning is not available right now "
                        f"({error}). I did not guess an answer.")
            results.append((expert, step["query"], text))
            if not found:
                trace(request_id, f"step {number}: nothing found -> stop, reply 'not found'")
                break
            continue

        # Dependent steps: give this expert everything found so far
        message = step["message"]
        if results:
            previous = "\n".join(text for _, _, text in results)
            message += ("\n\nResults from the previous steps "
                        "(use the exact names written here):\n" + previous)

        trace(request_id, f"step {number}: {expert} <- {step['message']!r}")
        response = handle_ai_chat_request(db, expert, message, request_id)
        trace(request_id, f"step {number}: result: {str(response)[:120]}")
        results.append((expert, step["message"], str(response)))

    steps_summary = "\n".join(f"{expert}: {text}" for expert, _, text in results)
    synthesis_prompt = (
        f'The user asked: "{original_request}"\n\n'
        f"Here is what each step found or did:\n{steps_summary}\n\n"
        "Write ONE short, clear reply using ONLY the information above. "
        "If a step says NOT FOUND, or a database result is an empty list [], "
        "tell the user honestly that it was not found in the resume; never invent records. "
        "A Database Write Expert result is already the exact message to show the user -- "
        "reuse it verbatim. Never mention SQL, Python, code, scores or these internal steps."
    )
    reply = send_message(original_request, synthesis_prompt)
    trace(request_id, f"outcome: replied ({len(results)} step(s) ran)")
    return reply


# ----------------------------------------------------------------------
# The chat entry point: approvals (HW2 Step 5)
# ----------------------------------------------------------------------

YES_WORDS = {"yes", "y"}
NO_WORDS = {"no", "n"}
UNCLEAR_WORDS = {"maybe", "hmm", "hm", "idk", "notsure", "perhaps", "ok", "okay",
                 "sure", "wait", "yesno", "possibly", "dontknow"}


def _short_answer(message):
    """'Yes!' -> 'yes', 'not sure' -> 'notsure'."""
    return re.sub(r"[^a-z]", "", message.lower())


def handle_user_message(db, message, state):
    """
    Called by socket_events.py for every chat message.
    `state` is a dict kept per user; state["pending"] holds the action waiting for yes/no.
    """
    request_id = uuid.uuid4().hex[:6]
    trace(request_id, f"user: {message!r}")
    answer = _short_answer(message)
    pending = state.get("pending")

    if pending:
        state.pop("pending")                 # whatever happens next, it is no longer waiting

        if answer in YES_WORDS:
            trace(request_id, f"approval: APPROVED -> running exactly {pending.summary()} (action {pending.id})")
            try:
                outcome = execute(db, pending, approved=True)
            except OperationError as error:
                outcome = f"Nothing was changed: {error}"
            trace(request_id, f"outcome: {outcome}")
            return outcome

        if answer in NO_WORDS:
            trace(request_id, f"approval: CANCELLED by 'no' -> {pending.summary()} not run")
            return "Cancelled. Nothing was changed."

        if answer in UNCLEAR_WORDS:
            trace(request_id, f"approval: CANCELLED (unclear answer {message!r}) -> {pending.summary()} not run")
            return ("I need a clear 'yes' or 'no', so I cancelled it. Nothing was changed. "
                    "Send the request again if you still want it.")

        trace(request_id, f"approval: CANCELLED (user moved on) -> {pending.summary()} not run")
        # ...and continue below: the new message is handled as a normal request

    elif answer in YES_WORDS | NO_WORDS:
        trace(request_id, "approval: none (nothing was waiting)")
        return "There is nothing waiting for your approval right now."

    try:
        reply = handle_ai_chat_request(db, "Orchestrator", message, request_id)
        trace(request_id, "approval: none")
        return reply
    except ApprovalRequired as waiting:
        state["pending"] = waiting.action
        trace(request_id, f"approval: WAITING for yes/no -> {waiting.action.summary()} (action {waiting.action.id})")
        return f"{waiting.action.description} Reply yes or no."


# ----------------------------------------------------------------------
# Talking to OpenRouter
# ----------------------------------------------------------------------

def send_message(user_message, system_prompt="You are a helpful assistant."):
    """
    Send a message to the AI and return its response as a string.
    Returns an error message (starting with ⚠️) if something went wrong.
    """
    api_key = os.getenv('OPENROUTER_API_KEY')

    if not api_key or api_key == 'paste-your-key-here':
        return "⚠️ No API key found. Add your OpenRouter key to the .env file and restart the app."

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8080"
    }

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_message}
    ]

    response = requests.post(
        OPENROUTER_URL,
        headers=headers,
        json={"model": DEFAULT_MODEL, "messages": messages},
        timeout=30
    )

    result = response.json()

    if 'error' in result:
        error_message = result['error'].get('message', 'Unknown API error')
        return f"⚠️ OpenRouter error: {error_message}"

    if 'choices' not in result:
        return f"⚠️ Unexpected response from OpenRouter: {result}"

    return result['choices'][0]['message']['content']
