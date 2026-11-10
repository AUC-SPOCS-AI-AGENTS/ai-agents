"""
database.py — manages all interactions with the SQLite database.

A database is an organized way to store and retrieve data. We use SQLite,
which stores everything in a single file (resume.db) — no server needed.

This file is organized as a class called `database`. You learned about classes
in your OOP course: a class bundles related data and functions together.
Here, the class bundles all database operations (creating tables, inserting
data, querying data) into one place.

HOW THE DATA IS ORGANIZED:
  institutions  (e.g. Michigan State University)
      └── positions  (e.g. Instructor)
              └── experiences  (e.g. CSE 491)
                      └── skills  (e.g. Python, level 10)

HW2 CHANGES (Step 1 — keep data across restarts):
  - Resume tables are loaded from CSV only ONCE, when the database is new.
    After that, anything added or deleted through the chat survives a restart.
  - llm_roles is reloaded from llm_roles.csv on EVERY start, so prompt edits
    take effect after a restart.
  - purge=True still exists, but only to deliberately reset (test) data.
  - db_path / data_folder / seed_folder can be changed, so the tests can use
    a separate database loaded from fixtures/ without touching real data.
"""

import sqlite3
import csv
import os

# Path to the SQLite database file — created automatically on first run
DB_PATH = 'flask_app/database/resume.db'

# Default folder that holds create_tables/ and initial_data/
DATA_FOLDER = 'flask_app/database/'

# Tables must be created in this order because of foreign key relationships.
# For example, 'positions' references 'institutions', so institutions must exist first.
TABLE_ORDER = ['institutions', 'positions', 'experiences', 'skills', 'llm_roles', 'embeddings']

# HW2: resume data is loaded ONCE (when the database is new), so user edits survive restarts.
RESUME_TABLES = ['institutions', 'positions', 'experiences', 'skills']


class database:
    """
    Manages all interactions with the SQLite resume database.

    Usage:
        db = database()
        db.createTables()             # keeps existing data, reloads prompts
        db.createTables(purge=True)   # full reset (use only for test data)
        data = db.getResumeData()     # returns the full resume as a dict
    """

    def __init__(self, db_path=DB_PATH, data_folder=DATA_FOLDER, seed_folder=None):
        """
        db_path:     which SQLite file to use (tests pass a separate file)
        data_folder: folder that contains create_tables/
        seed_folder: folder that contains the seed CSVs
                     (default: <data_folder>/initial_data, tests pass fixtures/)
        """
        self.db_path = db_path
        self.data_folder = data_folder
        self.seed_folder = seed_folder or os.path.join(data_folder, 'initial_data')

    # ------------------------------------------------------------------
    # CORE QUERY FUNCTION
    # ------------------------------------------------------------------

    def query(self, sql, params=()):
        """
        Execute any SQL statement and return results as a list of dicts.

        Args:
            sql    (str):   The SQL statement to run.
            params (tuple): Values to safely substitute into the SQL.

        Returns:
            list: A list of dicts for SELECT queries; empty list otherwise.

        WHY params INSTEAD OF F-STRINGS?
            Never put user input directly into SQL like:
                f"SELECT * FROM users WHERE name = '{name}'"
            A malicious user could type  '; DROP TABLE users; --  as their name.
            Using params=() tells SQLite to treat the value as data, not code.
            This is called "parameterized queries" and prevents SQL injection.
        """
        # Connect to the database file (creates it if it doesn't exist)
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA foreign_keys = ON")

        # row_factory lets us access columns by name: row['title']
        # instead of by index: row[0]
        connection.row_factory = sqlite3.Row

        cursor = connection.cursor()
        cursor.execute(sql, params)

        # Only fetch rows for queries that return data
        results = []
        if sql.strip().upper().startswith(('SELECT', 'PRAGMA')):
            results = [dict(row) for row in cursor.fetchall()]

        connection.commit()
        connection.close()
        return results

    # ------------------------------------------------------------------
    # TABLE SETUP (HW2 Step 1)
    # ------------------------------------------------------------------

    def _table_exists(self, table):
        """Return True if a table with this name already exists in the database."""
        rows = self.query(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,)
        )
        return len(rows) > 0

    def createTables(self, purge=False):
        """
        Startup rules:
          - purge=True       -> drop everything and start fresh (ONLY for resetting test data)
          - new database     -> create tables and load the resume CSVs once
          - existing database-> keep resume data exactly as it is
          - llm_roles        -> reloaded on EVERY start so prompt edits take effect

        Why not just purge=False with the old code?
          The old code re-ran the CSV seed on every start with INSERT OR IGNORE:
            * a CSV row you deleted came back (its ID was free again)
            * an edited prompt in llm_roles.csv was ignored (its ID already existed)
        """
        if purge:
            # Drop tables in reverse order so foreign keys don't block deletion
            for table in reversed(TABLE_ORDER):
                self.query(f"DROP TABLE IF EXISTS {table}")

        is_new_database = not self._table_exists('institutions')

        # Create only the tables that are missing
        for table in TABLE_ORDER:
            if not self._table_exists(table):
                self._create_table(table)

        if is_new_database:
            print("New database: loading resume data from CSV files")
            for table in RESUME_TABLES:
                self._seed_table(table)
        else:
            print("Existing database found: keeping resume data")

        # Prompts always come fresh from llm_roles.csv, and always from the app's own
        # initial_data/ folder (test fixtures only hold resume data, not prompts)
        self.query("DELETE FROM llm_roles")
        self._seed_table('llm_roles', folder=os.path.join(self.data_folder, 'initial_data'))

    def _create_table(self, table):
        """Read the .sql file for a table and execute it."""
        sql_file = os.path.join(self.data_folder, 'create_tables', f'{table}.sql')
        with open(sql_file, encoding='utf-8') as f:
            self.query(f.read())

    def _seed_table(self, table, folder=None):
        """
        Load rows from <folder or seed_folder>/<table>.csv into the table.

        The CSV files in flask_app/database/initial_data/ are where you
        customize the resume content. Each file corresponds to one table.

        # NOTE (HW2): resume CSVs are only read when the database is new.
        #       To reload them, reset the database (purge=True or delete resume.db).
        """
        csv_file = os.path.join(folder or self.seed_folder, f'{table}.csv')

        if not os.path.exists(csv_file):
            return

        with open(csv_file, encoding='utf-8') as f:
            rows = list(csv.DictReader(f))

        if not rows:
            return

        columns = list(rows[0].keys())
        placeholders = ', '.join(['?' for _ in columns])
        column_names = ', '.join(columns)
        sql = f"INSERT OR IGNORE INTO {table} ({column_names}) VALUES ({placeholders})"

        # Convert "NULL" strings from CSV into Python None values
        values = [
            tuple(None if cell == 'NULL' else cell for cell in row.values())
            for row in rows
        ]

        connection = sqlite3.connect(self.db_path)
        cursor = connection.cursor()
        cursor.executemany(sql, values)
        connection.commit()
        connection.close()
        print(f"  Loaded data for table: {table}")

    # ------------------------------------------------------------------
    # RESUME DATA
    # ------------------------------------------------------------------

    def getResumeData(self):
        """
        Return the full resume as a nested dictionary.

        Structure:
            {
              inst_id: {
                'name': '...', 'type': '...',
                'positions': {
                  position_id: {
                    'title': '...', 'start_date': '...',
                    'experiences': {
                      experience_id: {
                        'name': '...', 'description': '...',
                        'skills': { skill_id: {'name': '...', 'skill_level': 7} }
                      }
                    }
                  }
                }
              }
            }

        This nested structure is passed directly to the resume.html template,
        where Jinja2 loops over it to render the page.
        """
        resume = {}

        for institution in self.query("SELECT * FROM institutions"):
            inst_id = institution['inst_id']
            resume[inst_id] = dict(institution)
            resume[inst_id]['positions'] = {}

            positions = self.query(
                "SELECT * FROM positions WHERE inst_id = ? ORDER BY start_date DESC",
                (inst_id,)
            )

            for position in positions:
                pos_id = position['position_id']
                resume[inst_id]['positions'][pos_id] = dict(position)
                resume[inst_id]['positions'][pos_id]['experiences'] = {}

                experiences = self.query(
                    "SELECT * FROM experiences WHERE position_id = ? ORDER BY start_date DESC",
                    (pos_id,)
                )

                for experience in experiences:
                    exp_id = experience['experience_id']
                    resume[inst_id]['positions'][pos_id]['experiences'][exp_id] = dict(experience)
                    resume[inst_id]['positions'][pos_id]['experiences'][exp_id]['skills'] = {}

                    skills = self.query(
                        "SELECT * FROM skills WHERE experience_id = ?",
                        (exp_id,)
                    )

                    for skill in skills:
                        skill_id = skill['skill_id']
                        resume[inst_id]['positions'][pos_id]['experiences'][exp_id]['skills'][skill_id] = dict(skill)

        self._format_dates(resume)
        return resume

    def _format_dates(self, resume):
        """
        Convert raw date strings like '2019-01-01' to 'YYYY-MM' format.
        None end_dates become 'Present'.
        Modifies the resume dict in place.
        """
        for institution in resume.values():
            for position in institution['positions'].values():
                position['start_date'] = self._short_date(position['start_date'])
                position['end_date'] = self._short_date(position['end_date']) or 'Present'

                for experience in position['experiences'].values():
                    experience['start_date'] = self._short_date(experience['start_date'])
                    experience['end_date'] = self._short_date(experience['end_date']) or ''

    def _short_date(self, date_string):
        """Return just the 'YYYY-MM' part of a date string, or None."""
        if date_string:
            return str(date_string)[:7]
        return None

    def getResumeText(self):
        """
        Return the resume as a plain-text string, used as context for the AI.

        # NOTE: This is exactly what the AI reads about you before answering
        #       questions. Edit your CSV files to change what it knows.
        """
        resume = self.getResumeData()
        lines = []

        for institution in resume.values():
            lines.append(f"\nInstitution: {institution['name']} ({institution['type']}) — {institution.get('city', '')}, {institution.get('state', '')}")

            for position in institution['positions'].values():
                lines.append(f"  Position: {position['title']} ({position['start_date']} to {position['end_date']})")
                lines.append(f"  Responsibilities: {position.get('responsibilities', '')}")

                for experience in position['experiences'].values():
                    lines.append(f"    Experience: {experience['name']} — {experience.get('description', '')}")

                    for skill in experience['skills'].values():
                        lines.append(f"      Skill: {skill['name']} (level {skill['skill_level']}/10)")

        return '\n'.join(lines)

    def getLLMRoles(self):
        rows = self.query("SELECT * FROM llm_roles")
        return {row['role']: row for row in rows}

    def insertRows(self, table, columns, values):
        # NOTE (HW2): only used by the old HW1 Write Expert. In Step 5 it will be
        # replaced by safe, allowed operations, and then removed.
        value_sql, bound_params = [], []
        for value in values:
            if isinstance(value, str) and value.strip().startswith("(SELECT"):
                value_sql.append(value)
            else:
                value_sql.append("?")
                bound_params.append(value)
        sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(value_sql)})"
        self.query(sql, tuple(bound_params))
