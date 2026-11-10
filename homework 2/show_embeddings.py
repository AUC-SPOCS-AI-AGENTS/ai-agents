"""Print what is stored in the embeddings table (used to show S5 in the demo)."""
import json
import sqlite3

connection = sqlite3.connect('flask_app/database/resume.db')
rows = connection.execute(
    "SELECT source_table, record_id, text, vector FROM embeddings "
    "ORDER BY source_table, record_id"
)
for table, record_id, text, vector in rows:
    print(f"{table:12} #{record_id:<3} dims={len(json.loads(vector))}  {text[:60]}")
    