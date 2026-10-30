
"""
socket_events.py — handles real-time chat messages.
"""

from flask_socketio import emit
from flask_app import socketio
from flask_app.utils.llm import send_message
from flask import current_app


@socketio.on('send_message')
def handle_message(data):
    user_message = data.get('message', '').strip()

    if not user_message:
        return

    try:
        system_prompt = build_resume_system_prompt(current_app.db)
        ai_response = send_message(user_message, system_prompt)
    except Exception as error:
        print(f"LLM error: {error}")
        ai_response = f"Could not reach the AI: {error}"

    emit('receive_message', {'response': ai_response})


def build_resume_system_prompt(db):
    resume_text = db.getResumeText()

    return f"""You are a helpful AI assistant reviewing a resume.
You have been given the resume content below. Use it to answer questions
accurately and helpfully. If asked something not covered in the resume,
say so honestly rather than guessing.
Keep answers concise. You may use light markdown (bold, bullet lists) but
avoid large tables.

RESUME CONTENT:
{resume_text}
"""

