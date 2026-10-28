
from flask import current_app
from flask_socketio import emit
from flask_app import socketio
from flask_app.utils.llm import handle_ai_chat_request


@socketio.on('send_message')
def handle_message(data):
    user_message = data.get('message', '').strip()

    if not user_message:
        return

    try:
        db = current_app.db

        # Save the resume data before processing the request.
        before = db.getResumeData()

        ai_response = handle_ai_chat_request(
            db,
            role="Orchestrator",
            message=user_message
        )

        # Compare the resume data after processing the request.
        after = db.getResumeData()
        resume_changed = before != after

    except Exception as error:
        print(f"LLM error: {error}")
        ai_response = f"⚠️ Could not reach the AI: {error}"
        resume_changed = False

    emit('receive_message', {
        'response': ai_response,
        'resume_changed': resume_changed
    })



