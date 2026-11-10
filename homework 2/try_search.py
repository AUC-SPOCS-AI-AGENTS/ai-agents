"""
try_search.py - try a search by meaning and see ALL the scores.

Usage (from the homework 2 folder):
    python try_search.py "MSU experience"              # your own resume.db
    python try_search.py "MSU experience" --test       # the test data (test.db)
    python try_search.py "AI skills" --test --tables skills

Use it to choose SEARCH_MIN_SCORE from real numbers (README Step 3).
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()
args = sys.argv[1:]
if '--test' in args:
    os.environ['DB_PATH'] = 'flask_app/database/test.db'
    args.remove('--test')
tables = None
if '--tables' in args:
    i = args.index('--tables')
    tables = args[i + 1].split(',')
    del args[i:i + 2]
query = ' '.join(args)

from flask_app.utils.database import database
from flask_app.utils.semantic_search import semantic_search

db = database()
matches, all_scored = semantic_search(db, query, tables=tables)
print(f'Query: "{query}"   database: {db.db_path}   tables: {tables or "all"}')
if tables == ['skills']:
    print(f"Cut-off (SKILL_MIN_SCORE): {os.getenv('SKILL_MIN_SCORE', '0.25')}")
else:
    print(f"Cut-off (SEARCH_MIN_SCORE): {os.getenv('SEARCH_MIN_SCORE', '0.35')}")
    
for r in all_scored[:10]:
    mark = 'MATCH' if r in matches else '     '
    print(f"  {mark}  {r['score']:.3f}  {r['table']:12} #{r['id']:<3} {r['text'][:60]}")
if not matches:
    print("  -> no match above the cut-off: the agent should say 'not found'")
