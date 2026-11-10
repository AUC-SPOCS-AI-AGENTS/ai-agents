# My Homework 2: setup, run and test

## 1. Setup (fresh copy)

From the repo root (`ai-agents/`), once:

```bash
bash setup.sh                 # creates venv/ and installs requirements.txt
```

Create `.env` in the repo root (copy `homework 2/.env.example`) and fill in every value:

| Setting | Meaning | Value I used |
|---|---|---|
| `OPENROUTER_API_KEY` | your OpenRouter key (never commit it) | (secret) |
| `CHAT_MODEL` | model for the Orchestrator and experts | `openai/gpt-4o-mini` |
| `EMBEDDING_MODEL` | model for search by meaning | `openai/text-embedding-3-small` |
| `SEARCH_MIN_SCORE` | cut-off for institutions / positions / experiences | `0.35` |
| `SKILL_MIN_SCORE` | cut-off when only skills are searched | `0.25` |

## 2. Run the app

```powershell
cd "homework 2"
..\venv\Scripts\Activate.ps1        # Windows (macOS/Linux: source ../venv/bin/activate)
python app.py                        # open http://localhost:8080/resume
```

- Data lives in `flask_app/database/resume.db` and **survives restarts**. The resume CSVs are loaded only when the database is new; `llm_roles.csv` is reloaded at every start so prompt edits take effect.
- Every record has an embedding, stored in the `embeddings` table. New, edited or deleted records are synced at startup and after every change.
- Every chat message prints a trace in the terminal: request ID, route and reason, steps, search scores, approval state, outcome.

## 3. Test data (never touches my own resume)

Reset the test database from `fixtures/`:

```powershell
python reset_test_data.py            # rebuilds flask_app/database/test.db + embeddings
```

Run the app on the test data instead of my resume (PowerShell, current terminal only):

```powershell
$env:DB_PATH = "flask_app/database/test.db"
python app.py
```

## 4. Run all scenarios (S1-S11) with one command

Stop the app first, then:

```powershell
python tests/run_scenarios.py
```

It resets the test data, runs S1-S11 through the same code the chat uses, and prints each ID with PASS or FAIL. All scenarios call the real OpenRouter API (marked `[API]`). S10 makes the embedding call fail on purpose with a wrong embedding model name set only for that test. Full traces are saved to `tests/last_run_traces.txt`.

## 5. Safety rules for changes

- The Write Expert can only choose one of these operations (as JSON): `add_skill`, `delete_skill`, `delete_all_skills`, `update_skill_level`. Nothing else can change the data, and no model output goes to `eval()` or `exec()`.
- Deleting or changing data pauses and shows the exact action: *"This will delete skill 'Python' from experience 'CSE 847'. Reply yes or no."*
- `yes` runs exactly that stored action; `no` cancels; any other reply cancels too (a short unclear reply like `maybe` just cancels, a longer message is answered as a new request). A later `yes` approves nothing.
- The approval check is inside `perform_action()` in `flask_app/utils/write_actions.py`, the only function that writes.
