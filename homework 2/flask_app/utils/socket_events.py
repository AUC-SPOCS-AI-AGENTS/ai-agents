"""
socket_events.py — handles real-time chat messages using WebSockets.

WEBSOCKETS vs. HTTP:
  WebSockets keep the connection open, like a phone call, so both sides can
  send messages at any time. That's why the chat feels instant.

HOW EVENTS WORK:
  - Browser emits 'send_message'  ->  server handles it here
  - Server emits 'receive_message' ->  browser displays the reply

HW2 (Step 5): a destructive action waits for 'yes' or 'no'. We remember that
waiting action PER USER (per socket connection id, request.sid), so one user's
'yes' can never approve another user's action. The matching of yes / no /
anything else happens in llm.handle_user_message().
"""
from flask import current_app, request
from flask_socketio import emit
from flask_app import socketio
from flask_app.utils.llm import handle_user_message

# One small state dict per connected browser tab: {"pending": Action or missing}
SESSIONS = {}


@socketio.on('send_message')
def handle_message(data):
    """Called automatically when the browser emits a 'send_message' event."""
    user_message = data.get('message', '').strip()

    if not user_message:
        return

    db = current_app.db
    state = SESSIONS.setdefault(request.sid, {})

    try:
        ai_response = handle_user_message(db, user_message, state)
    except Exception as error:
        print(f"LLM error: {error}")
        ai_response = f"⚠️ Could not reach the AI: {error}"

    # Reply only to the user who sent the message
    emit('receive_message', {'response': ai_response})


@socketio.on('disconnect')
def handle_disconnect():
    """Forget the user's pending action when they close the page."""
    SESSIONS.pop(request.sid, None)
