"""
try_search.py — HW2 Step 3: look at REAL similarity scores before choosing the cut-off.

Run from inside "homework 2":
    python try_search.py          -> uses YOUR database (flask_app/database/resume.db)
    python try_search.py --test   -> builds a separate TEST database from fixtures/
"""
import sys
from dotenv import load_dotenv
load_dotenv()

from flask_app.utils.database import database
from flask_app.utils.embeddings import search, sync_embeddings, EmbeddingError

if '--test' in sys.argv:
    # Separate file, loaded from fixtures/, so your real resume is never touched
    db = database(db_path='test_resume.db', seed_folder='fixtures')
    db.createTables(purge=True)          # always start the test data fresh
    print("Test database:", sync_embeddings(db))
else:
    db = database()

TESTS = [
    ("MSU experience",     None),        # should match Michigan State University (S1)
    ("AI skills",          ['skills']),  # should rank ML-type skills first (S2)
    ("AI skills",          None),        # same question, ALL tables (S2 trap)
    ("Harvard experience", None),        # should NOT match anything (S11)
]

for question, tables in TESTS:
    print("=" * 70)
    print(f"Question: {question!r}   tables: {tables or 'ALL'}")
    try:
        results = search(db, question, tables=tables, top_k=6, min_score=0)
    except EmbeddingError as error:
        print("  EMBEDDING FAILED:", error)
        continue
    for r in results:
        print(f"  {r['score']:.3f}  {r['table']:<13} #{r['record_id']:<3} {r['text'][:55]}")