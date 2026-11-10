"""
socket_events.py - handles real-time chat messages using WebSockets.

  - Browser emits 'send_message'   -> handle_message() below runs
  - Server emits 'receive_message' -> the browser shows the reply

HW2: every browser tab has its own Socket.IO session ID (request.sid).
We pass it to the agent so a pending "Reply yes or no" action belongs to
ONE chat. A "yes" typed in another tab can never approve it.
"""

from flask import current_app, request
from flask_socketio import emit

from flask_app import socketio
from flask_app.utils.llm import handle_ai_chat_request, PENDING_ACTIONS

# Set by create_app() in __init__.py (older versions use current_app.db instead).
db = None


def get_db():
    return getattr(current_app, 'db', None) or db


@socketio.on('send_message')
def handle_message(data):
    user_message = (data or {}).get('message', '').strip()
    if not user_message:
        return

    try:
        reply = handle_ai_chat_request(get_db(), role="Orchestrator",
                                       message=user_message, session_id=request.sid)
    except Exception as error:
        # The app must keep working after a failed operation.
        print(f"Chat error: {error}")
        reply = "⚠️ Something went wrong, and nothing was changed. Please try again."

    # emit() inside a handler replies only to the tab that sent the message.
    emit('receive_message', {'response': reply})


@socketio.on('disconnect')
def handle_disconnect(*args):
    """Tab closed or reloaded: forget anything it was waiting to approve."""
    PENDING_ACTIONS.pop(request.sid, None)
