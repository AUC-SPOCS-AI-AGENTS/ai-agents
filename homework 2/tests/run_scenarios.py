"""
run_scenarios.py - run the HW2 scenarios S1-S11 and print PASS / FAIL.

Usage (from the homework 2 folder, with the app STOPPED):
    python tests/run_scenarios.py

What it does:
  - rebuilds the TEST database (flask_app/database/test.db) from fixtures/,
    so your own resume.db is never touched
  - sends each scenario's messages through the same handle_chat() the
    website uses, and checks the database and the trace
  - saves every trace to tests/last_run_traces.txt (evidence for the report)

All scenarios use the real OpenRouter API (marked [API]), so the key in
.env must work. S10 makes the embedding call fail ON PURPOSE by using a
wrong embedding model name just for that test; the real key is untouched.
Model answers can vary a little between runs, so if one scenario fails,
look at its trace in tests/last_run_traces.txt.
"""

import io
import os
import sys
from contextlib import redirect_stdout

# Run from the homework 2 folder no matter where the command was typed.
HW_FOLDER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(HW_FOLDER)
sys.path.insert(0, HW_FOLDER)

from dotenv import load_dotenv
load_dotenv()
os.environ['DB_PATH'] = 'flask_app/database/test.db'

from flask_app.utils.database import database
from flask_app.utils.semantic_search import semantic_search
from flask_app.utils import llm

SESSION = "test-session"
TRACE_FILE = os.path.join('tests', 'last_run_traces.txt')
db = database()
results = []
all_traces = []


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def chat(message):
    """Send one chat message; return (reply, trace text printed for it)."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        reply = llm.handle_chat(db, message, SESSION)
    trace = buffer.getvalue()
    all_traces.append(f"{trace}[reply] {reply}\n")
    return reply, trace


def skills():
    return sorted(r['name'] for r in db.query("SELECT name FROM skills"))


def scenario(scenario_id, title):
    """Decorator: run the test, record PASS/FAIL, never stop the whole run."""
    def wrap(test):
        all_traces.append(f"\n########## {scenario_id}: {title} ##########\n")
        llm.PENDING_ACTIONS.pop(SESSION, None)        # each scenario starts clean
        try:
            ok, detail = test()
        except Exception as error:                    # a crash is a FAIL, not the end
            ok, detail = False, f"crashed: {error}"
        results.append((scenario_id, ok))
        print(f"{scenario_id:4} [API] {'PASS' if ok else 'FAIL'}  {title} - {detail}")
        return test
    return wrap


def has(trace, text):
    return text.lower() in trace.lower()


# --------------------------------------------------------------------------
# Fresh test data
# --------------------------------------------------------------------------

print("Resetting test data ...")
with redirect_stdout(io.StringIO()):
    db.createTables(reset=True, seed_folder='fixtures')
    sync = db.syncEmbeddings()
if sync['failed']:
    print("Could not create the test embeddings - check OPENROUTER_API_KEY and EMBEDDING_MODEL.")
    sys.exit(1)
print(f"Test data ready ({sync['added']} embeddings).\n")
ORIGINAL_SKILLS = skills()


# --------------------------------------------------------------------------
# The scenarios
# --------------------------------------------------------------------------

@scenario("S1", "Find my MSU experience")
def s1():
    reply, trace = chat("Find my MSU experience")
    found = any("(MATCH)" in line and "Michigan State" in line for line in trace.splitlines())
    used_search = has(trace, "| query=")
    return found and used_search, "Michigan State University is a MATCH, scores in trace" \
        if found else "Michigan State University was not a MATCH"


@scenario("S2", "What AI skills do I have?")
def s2():
    reply, trace = chat("What AI skills do I have?")
    lines = trace.splitlines()
    ml = any("(MATCH)" in l and "Machine Learning" in l for l in lines)
    ps = any("(MATCH)" in l and "Public Speaking" in l for l in lines)
    return ml and not ps, f"Machine Learning matched={ml}, Public Speaking matched={ps}"


@scenario("S3", "How many positions do I have?")
def s3():
    reply, trace = chat("How many positions do I have?")
    read = has(trace, "Database Read Expert") and not has(trace, "Semantic Search")
    return read and "4" in reply, f"route via Read Expert={read}, reply: {reply[:60]}"


@scenario("S4", "What did I do at MSU?")
def s4():
    reply, trace = chat("What did I do at MSU?")
    two = has(trace, "1/2 Semantic Search") and has(trace, "2/2 Database Read Expert")
    sql_lines = [l for l in trace.splitlines() if "read" in l and "generated:" in l]
    # The user typed "MSU"; if step 2's SQL says "Michigan", it used step 1's result.
    uses_name = any("Michigan" in l for l in sql_lines)
    return two and uses_name, f"two steps={two}, step 2 used the name from step 1={uses_name}"


@scenario("S5", "Add a skill, restart, still there and searchable")
def s5():
    reply, trace = chat("Add Rust as a skill to BRAINWORKS")
    restarted = database()                              # like restarting the app
    with redirect_stdout(io.StringIO()):
        restarted.createTables()
        restarted.syncEmbeddings()
    in_db = "Rust" in [r['name'] for r in restarted.query("SELECT name FROM skills")]
    embedded = restarted.query("SELECT COUNT(*) AS n FROM embeddings e JOIN skills s "
                               "ON e.source_table = 'skills' AND e.record_id = s.skill_id "
                               "WHERE s.name = 'Rust'")[0]['n'] == 1
    matches, _ = semantic_search(restarted, "Rust programming language", tables=['skills'])
    searchable = bool(matches) and matches[0]['text'] == "Rust"
    return in_db and embedded and searchable, \
        f"in db={in_db}, has embedding={embedded}, search finds it={searchable}"


@scenario("S6", "Deletion request, then no")
def s6():
    before = skills()
    reply, _ = chat("Remove Python from CSE 847")
    shown = "Python" in reply and "yes or no" in reply
    chat("no")
    return shown and skills() == before, f"action shown={shown}, unchanged={skills() == before}"


@scenario("S7", "Same deletion request, then yes")
def s7():
    before = skills()
    reply, _ = chat("Remove Python from CSE 847")
    chat("yes")
    removed = sorted(set(before) - set(skills()))
    return removed == ["Python"], f"removed: {removed} (expected only Python)"


@scenario("S8", "Deletion, then maybe; and deletion, then change of subject")
def s8():
    before = skills()
    chat("Remove CSS from CSE 847")
    chat("maybe")
    after_maybe = skills() == before and SESSION not in llm.PENDING_ACTIONS
    chat("Remove CSS from CSE 847")
    chat("How many skills do I have?")
    reply, _ = chat("yes")
    after_switch = skills() == before and "nothing waiting" in reply
    return after_maybe and after_switch, \
        f"maybe -> nothing ran={after_maybe}, old action not approved later={after_switch}"


@scenario("S9", "Clean up my skills so the list is empty")
def s9():
    before = skills()
    reply, trace = chat("Clean up my skills so the list is empty")
    paused = SESSION in llm.PENDING_ACTIONS and skills() == before
    chat("no")
    return paused and skills() == before, f"paused for approval={paused}"


@scenario("S10", "Embedding call fails")
def s10():
    real_model = os.environ.get('EMBEDDING_MODEL', '')
    os.environ['EMBEDDING_MODEL'] = 'not-a-real/embedding-model'   # break it on purpose
    try:
        reply, trace = chat("Find my MSU experience")
    finally:
        os.environ['EMBEDDING_MODEL'] = real_model                # put it back
    failed_in_trace = has(trace, "search     | FAILED")
    no_invention = "(MATCH)" not in trace                     # no made-up or zero-vector match
    words = ("unavailable", "not available", "error", "try again", "couldn't", "could not", "unable")
    clear_error = failed_in_trace and any(w in reply.lower() for w in words)
    reply2, trace2 = chat("Find my MSU experience")               # app still works?
    recovered = any("(MATCH)" in l and "Michigan State" in l for l in trace2.splitlines())
    return clear_error and no_invention and recovered, \
        f"clear error={clear_error}, no invented match={no_invention}, works afterwards={recovered}"


@scenario("S11", "Find my Harvard experience")
def s11():
    reply, trace = chat("Find my Harvard experience")
    no_match = "(MATCH)" not in trace
    no_invention = not any(name in reply for name in ("Michigan", "National Institutes", "Standard"))
    return no_match and no_invention, f"no match={no_match}, no invented record={no_invention}"


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------

with open(TRACE_FILE, 'w', encoding='utf-8') as f:
    f.write("".join(all_traces))

passed = sum(ok for _, ok in results)
print(f"\n{passed}/{len(results)} scenarios passed. Traces saved to {TRACE_FILE}")
sys.exit(0 if passed == len(results) else 1)
