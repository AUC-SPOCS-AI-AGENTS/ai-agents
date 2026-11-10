"""
try_approval.py — HW2 Step 5: run the approval scenarios on the TEST database.

Run from inside "homework 2":   python try_approval.py
It always rebuilds test_resume.db from fixtures/, so your real resume is never touched.
After every message it prints the skills in the database, so you can SEE
that "no" changes nothing and "yes" changes exactly what was shown.
"""
from dotenv import load_dotenv
load_dotenv()

from flask_app.utils.database import database
from flask_app.utils.embeddings import sync_embeddings
from flask_app.utils.llm import handle_user_message

db = database(db_path='test_resume.db', seed_folder='fixtures')
db.createTables(purge=True)
print("Test database:", sync_embeddings(db))


def skills():
    return [r['name'] for r in db.query("SELECT name FROM skills ORDER BY skill_id")]


state = {}   # the same kind of per-user state that socket_events.py keeps


def say(message):
    reply = handle_user_message(db, message, state)
    print(f"   USER : {message}")
    print(f"   AGENT: {reply}")
    print(f"   skills in DB now: {skills()}\n")


def scenario(title):
    print("\n" + "#" * 70 + f"\n{title}\n   skills before: {skills()}\n")


scenario("S6: deletion request, then 'no'  (database must NOT change)")
say("Remove Python from CSE 847")
say("no")

scenario("S7: same deletion, then 'yes'  (ONLY Python must disappear)")
say("Remove Python from CSE 847")
say("yes")

scenario("S8a: deletion, then 'maybe', then 'yes'  (nothing may run)")
say("Remove HTML from CSE 847")
say("maybe")
say("yes")

scenario("S8b: deletion, then change the subject, then 'yes'  (old action must NOT run)")
say("Remove HTML from CSE 847")
say("How many skills do I have?")
say("yes")

scenario("S9: no danger word, must still pause  (answer 'no')")
say("Clean up my skills so the list is empty")
say("no")

scenario("Safe change: add runs at once, with the right experience")
say("Add Rust to BRAINWORKS")
print("   Rust row:", db.query("SELECT * FROM skills WHERE name = 'Rust'"))
print("   Rust embedding stored:",
      bool(db.query("SELECT 1 FROM embeddings e JOIN skills s ON e.record_id = s.skill_id "
                    "WHERE e.table_name = 'skills' AND s.name = 'Rust'")))
