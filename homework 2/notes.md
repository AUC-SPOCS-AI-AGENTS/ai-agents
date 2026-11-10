# HW2 working notes (for DESIGN_AND_TESTING.md later)

## Before You Start: what I found in HW1

- Read question works ("List all my skills").
- "Add Rust to BRAINWORKS": the chat said "New Rust added to the skills table", but Rust did not appear in the list.
  Checking the database directly showed the row `(5, None, 'Rust', 5)`:
  the Write Expert's generated code could not find BRAINWORKS' experience_id, so it stored `None` (NULL),
  and the list query (JOIN with experiences) dropped the row. The reply claimed success anyway.
- `eval(plan_text)` in `llm.py` -> runs the Orchestrator's plan as Python code.
- `exec(generated_code, {"db": db, "NULL": None})` in `llm.py` -> runs the Write Expert's code.
  The `"NULL": None` mapping is why the missing ID silently became None.
- Restart test: Rust disappeared after restart because `createTables(purge=True)` wipes and reloads everything.

## Step 1 – keep data across restarts

- Resume tables (institutions, positions, experiences, skills) are loaded from CSV only when the database is new.
- llm_roles is deleted and reloaded from llm_roles.csv on every start, so prompt edits take effect.
- Why not just `purge=False`: the old seed ran on every start with INSERT OR IGNORE, so a deleted CSV row came back
  (its ID was free again) and an edited prompt was ignored (its ID already existed).
- Startup output, 1st run: "New database: loading resume data from CSV files"
- Startup output, 2nd run: "Existing database found: keeping resume data"

## Step 2 – embeddings

- Stored in SQLite table `embeddings(table_name, record_id, text, vector JSON, model)`.
- Text embedded: institutions = name + department + city + state; positions = title + responsibilities;
  experiences = name + description; skills = "Skill: <name>" only.
- `sync_embeddings()` at startup: embeds new/edited records, removes embeddings of deleted records,
  re-embeds if the model changes. A failed or all-zero vector raises EmbeddingError and is never stored.
- 1st run: `Embeddings ready: {'embedded': 17, 'removed': 0, 'unchanged': 0}`
- 2nd run (after restart): `Embeddings ready: {'embedded': 0, 'removed': 0, 'unchanged': 17}` -> embeddings survive a restart.

## Test data

- `fixtures/` was not in the course repo yet. Temporary copy: the original sample resume from
  `origin/main:homework 0/.../initial_data/` (Michigan State University, BRAINWORKS, CSE 847, ...)
  plus 3 extra skills: Machine Learning, Neural Networks, Public Speaking.
  Replace with the official fixtures when they are published.

## Step 3 – real scores (test data)

Command: `python try_search.py --test`

```
Test database: {'embedded': 20, 'removed': 0, 'unchanged': 0}
======================================================================
Question: 'MSU experience'   tables: ALL
  0.623  institutions  #1   Michigan State University, Computer Science, East Lansi
  0.271  experiences   #1   CSE 477, Taught an introductory course on web applicati
  0.247  experiences   #2   CSE 847, Taught a hands-on introduction to Natural Lang
  0.244  experiences   #6   CSE 491, Taught a hands-on introduction to AI Agents.
  0.243  skills        #1   Skill: Javascript
  0.222  skills        #5   Skill: Machine Learning
======================================================================
Question: 'AI skills'   tables: ['skills']
  0.623  skills        #5   Skill: Machine Learning
  0.594  skills        #6   Skill: Neural Networks
  0.473  skills        #1   Skill: Javascript
  0.449  skills        #2   Skill: Python
  0.433  skills        #3   Skill: HTML
  0.424  skills        #7   Skill: Public Speaking
======================================================================
Question: 'AI skills'   tables: ALL
  0.623  skills        #5   Skill: Machine Learning
  0.594  skills        #6   Skill: Neural Networks
  0.473  skills        #1   Skill: Javascript
  0.472  experiences   #6   CSE 491, Taught a hands-on introduction to AI Agents.
  0.449  skills        #2   Skill: Python
  0.433  skills        #3   Skill: HTML
======================================================================
Question: 'Harvard experience'   tables: ALL
  0.302  positions     #3   National Scholar, Helped the government plan the future
  0.274  skills        #7   Skill: Public Speaking
  0.272  institutions  #1   Michigan State University, Computer Science, East Lansi
  0.266  positions     #4   Associate Director, Used data science to assess corpora
  0.258  experiences   #2   CSE 847, Taught a hands-on introduction to Natural Lang
  0.255  experiences   #4   BRAINWORKS, Developed a platform to organize the scient
```

On my own resume (no MSU, no Harvard in the data), the highest wrong scores were 0.322 (MSU) and 0.362 (Harvard).

**Decision #2 – the "no match" cut-off:** chose `MIN_SIMILARITY = 0.50`.
Lowest correct match = 0.594 (Neural Networks); highest wrong match = 0.473 (Javascript for "AI skills");
"Harvard" tops out at 0.302 -> returns "not found".

**Decision #3 – which tables to search:** questions about skills search the `skills` table only.
Evidence: with ALL tables, the experience "CSE 491 ... AI Agents" (0.472) is mixed in between the skills;
on my own resume, the position "Intern at NAID" (0.482) even ranked above every skill.

## Step 4 – routing + two dependent steps (test data)

Command: `python try_orchestrator.py --test`
- Orchestrator plan is now JSON, read with json.loads() and checked (allowed experts, allowed tables, 1-4 steps). eval() removed.
- S1 "Find my MSU experience": route=semantic, tables=[institutions] -> Michigan State University 0.648 (next 0.215). PASS
- S2 "What AI skills do I have?": route=semantic, tables=[skills] -> Machine Learning 0.623, Neural Networks 0.594; Javascript 0.473 and below cut-off. PASS
- S3 "List all my skills": route=sql, reason "list everything, no fuzzy words" -> Database Read Expert. PASS
- S4 "What did I do at MSU?": route=semantic_then_sql. Step 1 resolved MSU -> Michigan State University; step 2 SQL used WHERE i.name = 'Michigan State University'. PASS
- S11 "Find my Harvard experience": best score 0.273 < 0.50 -> stopped, "NOT FOUND", no invented record. PASS
- Fixed in prompts: the HW1 Read Expert example used WHERE i.name = 'MSU' (exact-match bug); replaced with the full stored name.

## Step 5 – approval before destructive changes (test data)

Command: `python try_approval.py` (evidence: evidence_step5.txt)
- exec() removed. Write Expert returns JSON {"operation", "args"}; operations.py checks names/values and is the ONLY code that writes.
- Allowed operations: add_skill (safe), update_skill_level, delete_skill, delete_all_skills (destructive).
- The approval check is inside operations.execute(): a destructive action without approved=True raises ApprovalRequired, nothing runs.
- Pending action stored per user (socket request.sid) in socket_events.py.
- My rule: yes -> run the stored action exactly (model not asked again); no -> cancel; anything else -> cancel
  ("maybe" gets "I need a clear yes or no"; a new request is handled normally). A later "yes" never approves an old action.
- S6 PASS, S7 PASS (only Python deleted), S8a PASS, S8b PASS, S9 PASS (delete_all_skills paused, listed all 6 skills).
- Add skill: Rust -> experience_id 4 (BRAINWORKS), level 5 default stated in reply, embedding stored. HW1 bug (None) fixed.
- Decision: missing skill_level -> default 5 and say so (skills.skill_level is NOT NULL; HW1 silently invented it).
