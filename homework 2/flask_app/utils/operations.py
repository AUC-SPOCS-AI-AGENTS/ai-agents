"""
operations.py — HW2 Step 5: the ONLY way the agent can change the database.

WHY THIS FILE EXISTS
  In HW1 the Write Expert wrote Python code and we ran it with exec().
  The model could write anything (even DELETE FROM skills) and it ran at once.
  Now the model can only CHOOSE one operation from the list below and fill in
  its values (JSON). This file checks every value, and performs the change itself.

HOW THE SAFETY CHECK WORKS
  1. propose(db, name, args)  -> checks the operation name and every value,
                                 finds the exact rows it would touch, and builds
                                 an Action with a human description
                                 ("This will delete skill 'Python' from experience 'CSE 847'.")
  2. execute(db, action, approved=False)
                              -> THE approval check lives HERE, inside the code
                                 that writes. A destructive action without
                                 approved=True raises ApprovalRequired and nothing
                                 runs. No expert, prompt or wording can skip it,
                                 because there is no other code path that writes.
  3. On "yes", the chat handler calls execute(db, SAME action, approved=True):
     exactly the rows that were shown are changed, nothing else, and the model
     is NOT asked again.

  An operation is destructive because of what it DOES (delete / overwrite),
  not because of the words the user typed. "Clean up my skills so the list is
  empty" still becomes delete_all_skills -> destructive -> paused (S9).
"""

import sqlite3
import uuid

from flask_app.utils.embeddings import embed_record, delete_embedding, EmbeddingError


class OperationError(Exception):
    """The request can't be done (unknown operation, bad value, record not found...)."""


class ApprovalRequired(Exception):
    """Raised by execute() when a destructive action has not been approved."""
    def __init__(self, action):
        self.action = action
        super().__init__(action.description)


# A skill must have a level (the skills table says NOT NULL). When the user
# doesn't give one we use this default and SAY SO in the reply, instead of
# silently inventing a value (HW1's Write Expert silently made one up).
DEFAULT_SKILL_LEVEL = 5

# ----------------------------------------------------------------------
# The allowed operations
# ----------------------------------------------------------------------
OPERATIONS = {
    "add_skill": {
        "destructive": False,
        "required": ["skill_name", "experience_name"],
        "optional": ["skill_level"],
    },
    "update_skill_level": {          # overwrites a value -> destructive
        "destructive": True,
        "required": ["skill_name", "experience_name", "skill_level"],
        "optional": [],
    },
    "delete_skill": {
        "destructive": True,
        "required": ["skill_name", "experience_name"],
        "optional": [],
    },
    "delete_all_skills": {
        "destructive": True,
        "required": [],
        "optional": [],
    },
}


class Action:
    """One checked, ready-to-run operation. Stored while waiting for 'yes'."""
    def __init__(self, name, args, targets, description):
        self.id = uuid.uuid4().hex[:6]
        self.name = name
        self.args = args
        self.targets = targets          # the exact rows/values found at proposal time
        self.description = description
        self.destructive = OPERATIONS[name]["destructive"]

    def summary(self):
        values = ", ".join(f"{k}={v!r}" for k, v in self.args.items())
        return f"{self.name}({values})"


# ----------------------------------------------------------------------
# Checking values
# ----------------------------------------------------------------------

def _check_args(name, args):
    if name not in OPERATIONS:
        raise OperationError(f"'{name}' is not an allowed operation.")
    if not isinstance(args, dict):
        raise OperationError("the operation values must be a JSON object.")

    spec = OPERATIONS[name]
    allowed = set(spec["required"]) | set(spec["optional"])
    unknown = set(args) - allowed
    if unknown:
        raise OperationError(f"unexpected values for {name}: {sorted(unknown)}")

    for key in spec["required"]:
        if key not in args or args[key] in (None, ""):
            raise OperationError(f"{name} needs '{key}'.")

    clean = {}
    for key, value in args.items():
        if key == "skill_level":
            if value is None:
                continue
            try:
                level = int(value)
            except (TypeError, ValueError):
                raise OperationError("skill_level must be a whole number from 1 to 10.")
            if not 1 <= level <= 10:
                raise OperationError("skill_level must be from 1 to 10.")
            clean[key] = level
        else:
            if not isinstance(value, str) or not value.strip() or len(value) > 100:
                raise OperationError(f"'{key}' must be a short piece of text.")
            clean[key] = value.strip()
    return clean


def _find_experience(db, name):
    rows = db.query(
        "SELECT experience_id, name FROM experiences WHERE LOWER(name) = LOWER(?)", (name,)
    )
    if not rows:
        known = ", ".join(r["name"] for r in db.query("SELECT name FROM experiences"))
        raise OperationError(f"experience '{name}' was not found. Known experiences: {known}.")
    if len(rows) > 1:
        raise OperationError(f"more than one experience is called '{name}'.")
    return rows[0]


def _find_skill(db, skill_name, experience):
    rows = db.query(
        "SELECT skill_id, name, skill_level FROM skills "
        "WHERE LOWER(name) = LOWER(?) AND experience_id = ?",
        (skill_name, experience["experience_id"]),
    )
    return rows[0] if rows else None


# ----------------------------------------------------------------------
# 1. propose: check everything and describe exactly what would happen
# ----------------------------------------------------------------------

def propose(db, name, args):
    args = _check_args(name, args)

    if name == "add_skill":
        exp = _find_experience(db, args["experience_name"])
        if _find_skill(db, args["skill_name"], exp):
            raise OperationError(f"skill '{args['skill_name']}' already exists in '{exp['name']}'.")
        level = args.get("skill_level")
        level_note = f"level {level}" if level else f"level {DEFAULT_SKILL_LEVEL} (default; ask me to change it)"
        targets = {"experience_id": exp["experience_id"], "skill_name": args["skill_name"],
                   "skill_level": level or DEFAULT_SKILL_LEVEL}
        return Action(name, args, targets,
                      f"Add skill '{args['skill_name']}' to experience '{exp['name']}', {level_note}.")

    if name in ("delete_skill", "update_skill_level"):
        exp = _find_experience(db, args["experience_name"])
        skill = _find_skill(db, args["skill_name"], exp)
        if not skill:
            raise OperationError(f"skill '{args['skill_name']}' was not found in '{exp['name']}'.")
        if name == "delete_skill":
            return Action(name, args, {"skill_ids": [skill["skill_id"]]},
                          f"This will delete skill '{skill['name']}' from experience '{exp['name']}'.")
        return Action(name, args, {"skill_id": skill["skill_id"], "new_level": args["skill_level"]},
                      f"This will change the level of skill '{skill['name']}' in '{exp['name']}' "
                      f"from {skill['skill_level']} to {args['skill_level']}.")

    if name == "delete_all_skills":
        skills = db.query("SELECT skill_id, name FROM skills ORDER BY skill_id")
        if not skills:
            raise OperationError("there are no skills to delete.")
        names = ", ".join(s["name"] for s in skills)
        return Action(name, args, {"skill_ids": [s["skill_id"] for s in skills]},
                      f"This will delete ALL {len(skills)} skills: {names}.")

    raise OperationError(f"'{name}' is not an allowed operation.")   # not reachable


# ----------------------------------------------------------------------
# 2. execute: the ONLY function that writes, with the approval check inside
# ----------------------------------------------------------------------

def execute(db, action, approved=False):
    if not isinstance(action, Action) or action.name not in OPERATIONS:
        raise OperationError("unknown action.")

    # >>> THE APPROVAL CHECK <<<  Nothing below runs for a destructive action without 'yes'.
    if OPERATIONS[action.name]["destructive"] and not approved:
        raise ApprovalRequired(action)

    try:
        return _perform(db, action)
    except sqlite3.Error as error:
        # A database error is reported, never a crash and never a false "Done".
        raise OperationError(f"the database refused the change ({error}).")


def _perform(db, action):
    """Does the actual write. Only called from execute(), after the approval check."""
    t = action.targets

    if action.name == "add_skill":
        db.query("INSERT INTO skills (experience_id, name, skill_level) VALUES (?, ?, ?)",
                 (t["experience_id"], t["skill_name"], t["skill_level"]))
        new = db.query("SELECT skill_id FROM skills WHERE experience_id = ? AND name = ? "
                       "ORDER BY skill_id DESC LIMIT 1", (t["experience_id"], t["skill_name"]))
        outcome = action.description.replace("Add skill", "Added skill", 1)
        try:
            embed_record(db, "skills", new[0]["skill_id"])
        except EmbeddingError as error:
            # The row is saved; the embedding will be created at the next startup sync.
            outcome += f" (Warning: its embedding could not be created yet: {error})"
        return outcome

    if action.name in ("delete_skill", "delete_all_skills"):
        deleted = 0
        for skill_id in t["skill_ids"]:          # exactly the rows that were shown
            if db.query("SELECT skill_id FROM skills WHERE skill_id = ?", (skill_id,)):
                db.query("DELETE FROM skills WHERE skill_id = ?", (skill_id,))
                delete_embedding(db, "skills", skill_id)
                deleted += 1
        return f"Done. Deleted {deleted} skill(s)."

    if action.name == "update_skill_level":
        db.query("UPDATE skills SET skill_level = ? WHERE skill_id = ?", (t["new_level"], t["skill_id"]))
        return f"Done. {action.description.replace('This will change', 'Changed', 1)}"

    raise OperationError("unknown action.")
