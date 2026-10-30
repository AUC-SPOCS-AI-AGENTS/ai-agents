"""
routes.py — defines the URL paths (routes) that the web app responds to.

A ROUTE maps a URL to a Python function. When a browser visits a URL,
Flask calls the matching function and sends back its return value as HTML.

Example:
  Browser visits http://localhost:8080/resume
      → Flask calls the resume() function below
      → resume() queries the database and renders resume.html
      → The browser receives and displays the HTML page

The @app.route('/path') decorator is what connects a URL to a function.
You learned about decorators in your OOP course — they wrap a function
with extra behavior. Here, the decorator registers the function with Flask.

NOTE: Chat messages do NOT go through a route. They travel over a
      WebSocket connection handled in flask_app/utils/socket_events.py.
      Read that file after this one to see how the chat works.
"""
from flask import current_app
from flask import Blueprint

from flask import render_template

main = Blueprint ('main', __name__)
# db is set by create_app() in __init__.py after the app is initialized.
# It gives every route access to the database without creating a new
# connection on each request.



# ------------------------------------------------------------------
# HOME PAGE
# ------------------------------------------------------------------

@main.route('/')
def home():
    """
    Render the homepage.

    The homepage is defined in templates/home.html.
    Edit that file to add your own bio, photo, and introduction.
    """
    return render_template('home.html')


# ------------------------------------------------------------------
# RESUME PAGE
# ------------------------------------------------------------------

@main.route('/resume')
def resume():
    """
    Render the resume page with live data from the database.

    We call db.getResumeData() to load all institutions, positions,
    experiences, and skills. The result is a nested dictionary that
    we pass to the template as the variable 'resume'.

    In resume.html, Jinja2 loops over this dictionary to render the page.
    The chat panel is also part of resume.html — students can ask the AI
    questions about what they're reading.

    # NOTE: To update your resume, edit the CSV files in:
    #         flask_app/database/initial_data/
    #       Then restart the app to reload the database.
    """
    resume_data = current_app.db.getResumeData()
    return render_template('resume.html', resume=resume_data)
db_read_prompt = """
You are a database reading expert.
Your job is to answer questions about the resume by querying the database.
You have access to the following tools:
1. query_db_sql: run a SQL query against the database and return the results.
Note: You can only return the results of query_db_sql!
"""

db_read_config = {
    "name": "Database Read Expert",
    "description": "Database Read Expert",
    "instructions": db_read_prompt,
    "tools": ["query_db_sql"],
}
db_write_prompt = """
You are a database writing expert.
Your job is to update or insert information into the database based on the user's request.
You have access to the following tools:
1. update_db_sql: execute a SQL command to modify the database and return the confirmation.
Note: You can only return the results of update_db_sql!
"""

db_write_config = {
    "name": "Database Write Expert",
    "description": "Database Write Expert",
    "instructions": db_write_prompt,
    "tools": ["update_db_sql"],
}
content_prompt = """
You are a content expert.
Your job is to answer questions about the resume content itself.
You should summarize the information and provide a clear, concise answer based only on the resume data provided.
"""

content_config = {
    "name": "Content Expert",
    "description": "Content Expert",
    "instructions": content_prompt,
    "tools": [],
}
orchestrator_prompt = """
You are an orchestrator agent.
Your job is to decide which expert agents are needed to answer the user's request and in what order.
You have access to the following tools:
1. run_db_read_expert: use the database read expert.
2. run_db_write_expert: use the database write expert.
3. run_content_expert: use the content expert.
"""

orchestrator_config = {
    "name": "Orchestrator",
    "description": "Orchestrator",
    "instructions": orchestrator_prompt,
    "tools": [
        "run_db_read_expert",
        "run_db_write_expert",
        "run_content_expert",
    ],
}

@main.route("/chat", methods=["POST"])
def chat():
    user_message = request.form.get("message", "")
    
    # تجهيز البرومبت الأساسي
    prompt = LLM_PROMPT.render(
        role_description="You are the main orchestrator managing the expert agents.",
        user_message=user_message
    )
    
    # إرسال الطلب لـ OpenRouter API
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": DEFAULT_MODEL,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    
    response = requests.post(OPENROUTER_URL, headers=headers, json=payload)
    
    if response.status_code == 200:
        result = response.json()
        reply = result.get("choices", [{}])[0].get("message", {}).get("content", "No response")
        return {"reply": reply}
    else:
        return {"error": "Failed to communicate with AI model"}, 500
