"""
tests/run_scenarios.py — HW2 Step 7: ONE command that runs scenarios S1-S11.

Run from inside "homework 2":
    python tests/run_scenarios.py            -> prints each scenario ID with PASS / FAIL
    python tests/run_scenarios.py --verbose  -> also prints the full trace of every scenario

What it uses:
  - the TEST data in fixtures/ (copied into tests/test_resume.db), never your real resume
  - the real OpenRouter API for the chat model and the embedding model (marked [API])
  - S10 makes the embedding call fail on purpose by using a model name that does not
    exist, ONLY inside this test; your real key and .env are not changed.

Every scenario starts from a fresh copy of the test data, so the order doesn't matter.
"""
import io
import os
import sys
import shutil
import contextlib

# Windows: always print as UTF-8, even when the output goes to a file
sys.stdout.reconfigure(encoding="utf-8")

# Run from the "homework 2" folder, whatever folder the command was typed in
HW2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(HW2)
sys.path.insert(0, HW2)

from dotenv import load_dotenv
load_dotenv()

from flask_app.utils.database import database
from flask_app.utils.embeddings import sync_embeddings, search
from flask_app.utils.llm import handle_user_message

VERBOSE = '--verbose' in sys.argv
TEMPLATE_DB = os.path.join('tests', '_template_test.db')
TEST_DB = os.path.join('tests', 'test_resume.db')


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def build_template():
    """Load fixtures/ once and embed it; every scenario starts from a copy of this."""
    if os.path.exists(TEMPLATE_DB):
        os.remove(TEMPLATE_DB)
    db = database(db_path=TEMPLATE_DB, seed_folder='fixtures')
    with contextlib.redirect_stdout(io.StringIO()):
        db.createTables(purge=True)
    print("Test data loaded from fixtures/:", sync_embeddings(db))


def fresh_db():
    shutil.copyfile(TEMPLATE_DB, TEST_DB)
    db = database(db_path=TEST_DB, seed_folder='fixtures')
    return db


def skills(db):
    return sorted(r['name'] for r in db.query("SELECT name FROM skills"))


class Chat:
    """One user talking to the agent; keeps the replies and the printed trace."""
    def __init__(self, db):
        self.db, self.state, self.log = db, {}, ""

    def say(self, message):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            reply = handle_user_message(self.db, message, self.state)
        self.log += f"\nUSER: {message}\n{buffer.getvalue()}AGENT: {reply}\n"
        return reply

    @property
    def pending(self):
        return self.state.get('pending')


# ----------------------------------------------------------------------
# The scenarios. Each returns (passed: bool, short evidence: str, trace: str)
# ----------------------------------------------------------------------

def s1():
    chat = Chat(fresh_db())
    chat.say("Find my MSU experience")
    ok = ("search by meaning" in chat.log
          and any("Michigan State University" in l and "(MATCH)" in l for l in chat.log.splitlines()))
    return ok, "Michigan State University is a MATCH with its score in the trace", chat.log


def s2():
    chat = Chat(fresh_db())
    reply = chat.say("What AI skills do I have?")
    lines = chat.log.splitlines()
    ml_match = any("Machine Learning" in l and "(MATCH)" in l for l in lines)
    ps_match = any("Public Speaking" in l and "(MATCH)" in l for l in lines)
    ok = ml_match and not ps_match and "Public Speaking" not in reply
    return ok, f"Machine Learning matched={ml_match}, Public Speaking matched={ps_match}", chat.log


def s3():
    chat = Chat(fresh_db())
    chat.say("List all my skills")
    ok = ("route = sql" in chat.log and "Database Read Expert" in chat.log
          and "search by meaning" not in chat.log)
    return ok, "route = sql (Database Read Expert), no search by meaning", chat.log


def s4():
    chat = Chat(fresh_db())
    chat.say("What did I do at MSU?")
    ok = ("search by meaning" in chat.log
          and "step 2: Database Read Expert" in chat.log
          and "'Michigan State University'" in chat.log)
    return ok, "step 1 search resolved MSU; step 2 SQL used 'Michigan State University'", chat.log


def s5():
    db = fresh_db()
    chat = Chat(db)
    chat.say("Add Kubernetes to BRAINWORKS")
    # "Restart": a brand-new database object + the normal startup steps (no purge)
    restarted = database(db_path=TEST_DB, seed_folder='fixtures')
    with contextlib.redirect_stdout(io.StringIO()):
        restarted.createTables()
        sync_embeddings(restarted)
    row = restarted.query("SELECT skill_id FROM skills WHERE name = 'Kubernetes'")
    has_embedding = bool(row) and bool(restarted.query(
        "SELECT 1 FROM embeddings WHERE table_name = 'skills' AND record_id = ?", (row[0]['skill_id'],)))
    found = search(restarted, "container orchestration", tables=['skills'], top_k=1, min_score=0)
    top = found[0]['text'] if found else None
    ok = bool(row) and has_embedding and top == "Skill: Kubernetes"
    return ok, f"after restart: row={bool(row)}, embedding={has_embedding}, top search result={top!r}", chat.log


def s6():
    db = fresh_db(); before = skills(db)
    chat = Chat(db)
    asked = chat.say("Remove Python from CSE 847")
    chat.say("no")
    ok = "This will delete skill 'Python'" in asked and skills(db) == before
    return ok, "exact action shown; after 'no' the skills are unchanged", chat.log


def s7():
    db = fresh_db(); before = skills(db)
    chat = Chat(db)
    chat.say("Remove Python from CSE 847")
    chat.say("yes")
    removed = sorted(set(before) - set(skills(db)))
    ok = removed == ["Python"] and len(skills(db)) == len(before) - 1
    return ok, f"removed after 'yes': {removed}", chat.log


def s8():
    db = fresh_db(); before = skills(db)
    chat = Chat(db)
    chat.say("Remove HTML from CSE 847")
    chat.say("maybe")
    after_maybe = (skills(db) == before and chat.pending is None)
    chat.say("yes")
    chat.say("Remove HTML from CSE 847")
    chat.say("How many skills do I have?")       # change the subject
    chat.say("yes")
    ok = after_maybe and skills(db) == before and chat.pending is None
    return ok, "'maybe' and a new subject both cancel; later 'yes' changes nothing", chat.log


def s9():
    db = fresh_db(); before = skills(db)
    chat = Chat(db)
    asked = chat.say("Clean up my skills so the list is empty")
    paused = chat.pending is not None and chat.pending.name == "delete_all_skills"
    unchanged = skills(db) == before
    chat.say("no")
    ok = paused and unchanged and "This will delete ALL" in asked
    return ok, f"paused={paused} (delete_all_skills), skills unchanged={unchanged}", chat.log


def s10():
    db = fresh_db()
    chat = Chat(db)
    real_model = os.environ.get('EMBEDDING_MODEL')
    os.environ['EMBEDDING_MODEL'] = 'this-model-does-not-exist/for-s10'   # only inside the test
    try:
        reply = chat.say("Find my MSU experience")
        stored_bad = db.query("SELECT COUNT(*) AS n FROM embeddings WHERE model = ?",
                              ('this-model-does-not-exist/for-s10',))[0]['n']
    finally:
        if real_model is None:
            os.environ.pop('EMBEDDING_MODEL', None)
        else:
            os.environ['EMBEDDING_MODEL'] = real_model
    clear_error = "not available" in reply and "Michigan" not in reply
    start = len(chat.log)
    chat.say("Find my MSU experience")            # same question, real model restored
    works_after = any("Michigan State University" in l and "(MATCH)" in l
                      for l in chat.log[start:].splitlines())
    ok = clear_error and stored_bad == 0 and works_after
    return ok, f"clear error={clear_error}, bad vectors stored={stored_bad}, works afterwards={works_after}", chat.log


def s11():
    chat = Chat(fresh_db())
    reply = chat.say("Find my Harvard experience")
    ok = "nothing found" in chat.log and "(MATCH)" not in chat.log
    return ok, f"no match above the cut-off; reply: {reply[:70]!r}", chat.log


SCENARIOS = [
    ("S1", "Find my MSU experience", s1),
    ("S2", "What AI skills do I have?", s2),
    ("S3", "List all my skills -> Read Expert", s3),
    ("S4", "What did I do at MSU? (two steps)", s4),
    ("S5", "Add a skill, restart, still there + searchable", s5),
    ("S6", "Deletion, then no", s6),
    ("S7", "Deletion, then yes", s7),
    ("S8", "maybe / change subject", s8),
    ("S9", "Clean up my skills so the list is empty", s9),
    ("S10", "Embedding call fails", s10),
    ("S11", "Find my Harvard experience", s11),
]


def main():
    build_template()
    passed = 0
    for sid, title, run in SCENARIOS:
        try:
            ok, evidence, log = run()
        except Exception as error:          # a crash is a FAIL, never a silent pass
            ok, evidence, log = False, f"crashed: {type(error).__name__}: {error}", ""
        passed += ok
        print(f"{sid:<4} {'PASS' if ok else 'FAIL'}  [API]  {title}  ->  {evidence}")
        if VERBOSE or not ok:
            print("      trace:" + log.replace("\n", "\n      "))
    print(f"\n{passed}/{len(SCENARIOS)} scenarios passed")
    for path in (TEST_DB, TEMPLATE_DB):
        if os.path.exists(path):
            os.remove(path)


if __name__ == "__main__":
    main()
