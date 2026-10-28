
"""
llm.py — sends messages to an AI language model via the NVIDIA API.
"""

import os
import requests
from jinja2 import Template
import re


# NVIDIA API endpoint.
# We keep the original variable name to avoid changing other code.
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"


MASTER_TEMPLATE = Template(
    """
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
""",
    trim_blocks=True,
    lstrip_blocks=True,
)


def fill_template(
    role,
    domain,
    specific_instructions,
    request,
    background_context="",
    few_shot_examples="",
):
    return MASTER_TEMPLATE.render(
        role=role,
        domain=domain,
        specific_instructions=specific_instructions,
        request=request,
        background_context=background_context,
        few_shot_examples=few_shot_examples,
    ).strip()


def send_message(user_message, system_prompt="You are a helpful assistant."):
    """
    Send a message to NVIDIA and return its response as a string.
    The API key is loaded from the existing .env variable.
    """
    api_key = os.getenv("OPENROUTER_API_KEY")

    if not api_key or api_key == "paste-your-key-here":
        return (
            "No API key found. Add your NVIDIA API key to the "
            ".env file under OPENROUTER_API_KEY and restart the app."
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8000",
        "X-OpenRouter-Title": "CSE 491 Homework 1",
    }

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers=headers,
            json={
                "model": DEFAULT_MODEL,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 2048,
            },
            timeout=60,
        )

        response.raise_for_status()
        result = response.json()

    except requests.exceptions.HTTPError:
        try:
            error_details = response.json()
        except ValueError:
            error_details = response.text

        print(f"NVIDIA API HTTP error: {error_details}")
        return f"NVIDIA API error ({response.status_code}): {error_details}"

    except requests.exceptions.RequestException as error:
        print(f"NVIDIA API connection error: {error}")
        return f"Could not reach NVIDIA API: {error}"

    except ValueError:
        return "NVIDIA API returned an invalid JSON response."

    if "error" in result:
        error_message = result["error"].get("message", "Unknown API error")
        return f"NVIDIA API error: {error_message}"

    if "choices" not in result or not result["choices"]:
        return f"Unexpected response from NVIDIA API: {result}"

    return result["choices"][0]["message"]["content"]


def handle_ai_chat_request(db, role, message):
    if role is None:
        return send_message(message)

    roles = db.getLLMRoles()
    role_data = roles.get(role)

    if role_data is None:
        return f"Unknown AI role: {role}"

    background_context = role_data["background_context"] or ""
    few_shot_examples = role_data["few_shot_examples"] or ""

    if role == "Content Expert":
        background_context = (
            background_context + "\n" + db.getResumeText()
        ).strip()

    system_prompt = fill_template(
        role=role,
        domain=role_data["domain"],
        specific_instructions=role_data["specific_instructions"],
        request=message,
        background_context=background_context,
        few_shot_examples=few_shot_examples,
    )

    ai_response = send_message(message, system_prompt).strip()
    print(f"{role} response: {ai_response}")

    if role == "Database Read Expert":
        return execute_read_query(db, ai_response)

    if role == "Database Write Expert":
        return execute_write_action(db, ai_response)

    if role == "Orchestrator":
        return run_orchestrator_plan(db, message, ai_response)

    return ai_response


def execute_read_query(db, sql):
    sql = sql.strip()

    # Only SELECT queries are allowed.
    if not sql.upper().startswith("SELECT"):
        return "Error: Only SELECT queries are allowed."

    try:
        results = db.query(sql)
        return str(results)
    except Exception as error:
        print(f"Database read error: {error}")
        return f"Could not read from the database: {error}"


def execute_write_action(db, code):
    try:
        local_vars = {}
        exec(code, {"db": db, "NULL": None}, local_vars)

        return local_vars.get(
            "outcome",
            "The write action finished without a result message.",
        )

    except Exception as error:
        print(f"Database write error: {error}")
        return f"Could not update the database: {error}"




def run_orchestrator_plan(db, user_message, plan):
    import json

    try:
        start = plan.find("[")
        end = plan.rfind("]")

        if start == -1 or end == -1:
            return "I couldn't understand the plan. Please try again."

        calls = json.loads(plan[start:end + 1])

        if not isinstance(calls, list):
            return "Error: The orchestrator plan must be a list."

        results = []

        allowed_roles = {
            "Database Read Expert",
            "Database Write Expert",
            "Content Expert",
        }

        for call in calls:
            if not isinstance(call, dict):
                continue

            role = call.get("role")
            message = call.get("message")

            if role not in allowed_roles or not isinstance(message, str):
                continue

            result = handle_ai_chat_request(
                db,
                role=role,
                message=message,
            )

            results.append(f"{role}: {result}")

        if not results:
            return send_message(
                user_message,
                "You are a friendly resume assistant. "
                "Answer greetings naturally. For resume questions, "
                "use only the available resume information.",
            )

        synthesis_prompt = (
            "Answer the user's original request using the expert results. "
            "Be clear and concise. Do not invent information.\n\n"
            f"Original request: {user_message}\n\n"
            f"Expert results:\n{chr(10).join(results)}"
        )

        return send_message(
            synthesis_prompt,
            "You are the Orchestrator. Synthesize the expert results "
            "into one helpful answer for the user.",
        )

    except Exception as error:
        print(f"Orchestrator error: {error}")
        return f"Could not complete the plan: {error}"
