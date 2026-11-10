"""
try_orchestrator.py — HW2 Step 4: send real questions through the Orchestrator.

Run from inside "homework 2":
    python try_orchestrator.py --test   -> on the TEST database built from fixtures/
    python try_orchestrator.py          -> on YOUR database

Watch the [trace ...] lines: route, reason, search scores, and each step.
"""
import sys
from dotenv import load_dotenv
load_dotenv()

from flask_app.utils.database import database
from flask_app.utils.embeddings import sync_embeddings
from flask_app.utils.llm import handle_ai_chat_request

if '--test' in sys.argv:
    db = database(db_path='test_resume.db', seed_folder='fixtures')
    db.createTables(purge=True)
    print("Test database:", sync_embeddings(db))
else:
    db = database()

QUESTIONS = [
    "Find my MSU experience",       # S1: semantic search -> Michigan State University
    "What AI skills do I have?",    # S2: semantic search in skills only
    "List all my skills",           # S3: exact -> Database Read Expert
    "What did I do at MSU?",        # S4: two dependent steps
    "Find my Harvard experience",   # S11: not found
]

for question in QUESTIONS:
    print("\n" + "#" * 70)
    print("USER:", question)
    reply = handle_ai_chat_request(db, "Orchestrator", question)
    print("REPLY:", reply)
