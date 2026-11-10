"""
reset_test_data.py - rebuild the TEST database from fixtures/.

Usage (from the homework 2 folder):
    python reset_test_data.py

Creates flask_app/database/test.db with the course test data and its
embeddings. Your own resume.db is never touched.
"""
import os
from dotenv import load_dotenv

load_dotenv()
os.environ['DB_PATH'] = 'flask_app/database/test.db'

from flask_app.utils.database import database

db = database()
print(f"Resetting test data in {db.db_path} ...")
db.createTables(reset=True, seed_folder='fixtures')
result = db.syncEmbeddings()
if result['failed']:
    print("WARNING: some embeddings failed - check EMBEDDING_MODEL and your key.")
print("Test data ready.")
