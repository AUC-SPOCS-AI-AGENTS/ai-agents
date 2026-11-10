# Homework 2 — AI Resume Agent: search by meaning + approval before destructive changes

Built on my Homework 1 code (Flask, Flask-SocketIO, SQLite, OpenRouter).

## Setup

1. From the repository root, activate the virtual environment and install the requirements:
   ```powershell
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
2. Create a `.env` file in the repository root (see `.env.example` for every setting):
   - `OPENROUTER_API_KEY` — your OpenRouter key
   - `EMBEDDING_MODEL` — the embedding model announced by the course team
   - `MIN_SIMILARITY` — the "no match" cut-off for search by meaning (I use `0.50`)
   - `CHAT_MODEL` — optional, defaults to `openai/gpt-4o-mini`

## Run the app

### Run the app on the course test data

```powershell
cd "homework 2"
$env:DB_PATH = "demo_resume.db"
$env:SEED_FOLDER = "fixtures"
python app.py
```
To reset it: stop the app and `Remove-Item demo_resume.db`. Without these settings the app uses my own resume.

Open http://localhost:8080. At startup the terminal shows:
- `New database: ...` (first run) or `Existing database found: keeping resume data` (later runs)
- `Embeddings ready: {'embedded': ..., 'removed': ..., 'unchanged': ...}`

Every chat message prints a trace in the terminal: `[trace <id>] ...` with the route and reason,
search scores, experts and operations that ran, the approval state and the outcome.

## Run the tests (one command)

```powershell
cd "homework 2"
python tests/run_scenarios.py            # S1-S11, prints PASS / FAIL per scenario
python tests/run_scenarios.py --verbose  # also prints the trace of every scenario
```
The tests use the real OpenRouter API (marked `[API]`).

## Test data and how to reset it

- The course test data lives in `fixtures/` (Michigan State University, BRAINWORKS, CSE 847, ...,
  plus Machine Learning, Neural Networks and Public Speaking).
- The tests never touch my real resume: they load `fixtures/` into a separate file,
  `tests/test_resume.db`, and every scenario starts from a fresh copy. The test databases are
  deleted at the end of the run, so **the test data is reset automatically every time you run the tests**.
- To reset it by hand, delete the test database files:
  ```powershell
  Remove-Item tests\*.db, test_resume.db -ErrorAction SilentlyContinue
  ```
- Helper scripts that also rebuild the test database from `fixtures/` before running:
  `python try_search.py --test` (search scores), `python try_orchestrator.py --test` (routing),
  `python try_approval.py` (approval flows).

## Resetting my real data (only if I want to start over)

My own resume lives in `flask_app/database/resume.db`. Normal startup keeps it.
To reload it from the CSV files in `flask_app/database/initial_data/`, stop the app and delete the file:
```powershell
Remove-Item flask_app\database\resume.db
```
Prompts (`llm_roles.csv`) are reloaded on every start, so editing them only needs a restart.

## Where things are

| File | What it does |
|---|---|
| `flask_app/__init__.py` | startup: creates/keeps the database, then syncs the embeddings |
| `flask_app/utils/database.py` | tables, loading data once, queries |
| `flask_app/utils/embeddings.py` | embedding calls, validation, storage, sync, search by meaning |
| `flask_app/utils/llm.py` | Orchestrator (JSON plan, checked), experts, two-step requests, approvals, trace |
| `flask_app/utils/operations.py` | the allowed database operations and the approval check (the only code that writes) |
| `flask_app/utils/socket_events.py` | chat handler; remembers one pending action per user |
| `flask_app/database/create_tables/embeddings.sql` | the embeddings table |
| `flask_app/database/initial_data/llm_roles.csv` | the prompts |
| `tests/run_scenarios.py` | the one-command scenario tests |
| `DESIGN_AND_TESTING.md` | my design and testing report |
