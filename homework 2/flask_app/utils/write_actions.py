"""
write_actions.py - the ONLY code in the app that changes resume data.

Why this file exists (HW2, Step 5):
  In HW1 the Write Expert wrote Python and we ran it with exec().
  That meant the model could run ANY code, including a deletion.
  Now the Write Expert only CHOOSES one operation from a short list and
  fills in its values as JSON. Our code checks everything, then runs
  fixed, parameterized SQL. No model output is ever executed.

The three stages:
  1. parse_action(text)        read the model's JSON and check its shape
  2. prepare_action(db, ...)   look up the real records and build an Action
                               with a human-readable description
  3. perform_action(db, ...)   do the write. THE APPROVAL CHECK LIVES HERE:
                               a destructive action refuses to run unless it
                               is the exact Action the user approved.
"""

import json
import re
from dataclasses import dataclass


class ActionError(ValueError):
    """The request can't become a valid action (bad JSON, unknown name, ...)."""


class NotApprovedError(PermissionError):
    """Someone tried to run a destructive action without the user's yes."""


# --------------------------------------------------------------------------
# The allowed operations (the whole list - nothing else can ever run)
# --------------------------------------------------------------------------

OPERATIONS = {
    # name:               (destructive?, allowed value names)
    "add_skill":          (False, {"skill_name", "skill_level", "experience_name"}),
    "delete_skill":       (True,  {"skill_name", "experience_name"}),
    "delete_all_skills":  (True,  set()),
    "update_skill_level": (True,  {"skill_name", "skill_level", "experience_name"}),
}


@dataclass(frozen=True)          # frozen = can't be changed after it is created
class Action:
    operation: str
    skill_ids: tuple             # the exact rows this action touches
    params: tuple                # extra values (name, level, experience id)
    description: str             # exactly what we show the user
    destructive: bool


# --------------------------------------------------------------------------
# 1. Read the model's JSON as data and check its shape
# --------------------------------------------------------------------------

def parse_action(text):
    """Return (operation, values) or raise ActionError."""
    try:
        data = json.loads(text)
    except ValueError:
        raise ActionError("the Write Expert did not return JSON")
    if not isinstance(data, dict):
        raise ActionError("the action must be a JSON object")

    operation = data.get("operation")
    values = data.get("values") or {}
    if operation == "none":
        raise ActionError("I can only add a skill, delete a skill, delete all skills, "
                          "or change a skill's level.")
    if operation not in OPERATIONS:
        raise ActionError(f"unknown operation {operation!r}")
    if not isinstance(values, dict):
        raise ActionError("values must be a JSON object")

    allowed = OPERATIONS[operation][1]
    unknown = set(values) - allowed
    if unknown:
        raise ActionError(f"unexpected values {sorted(unknown)} for {operation}")

    for key in ("skill_name", "experience_name"):
        if key in values and not isinstance(values[key], str):
            raise ActionError(f"{key} must be text")
    if operation != "delete_all_skills" and not str(values.get("skill_name", "")).strip():
        raise ActionError(f"{operation} needs a skill_name")
    if "skill_level" in values:
        level = values["skill_level"]
        if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 10:
            raise ActionError("skill_level must be a whole number from 1 to 10")
    if operation == "update_skill_level" and "skill_level" not in values:
        raise ActionError("update_skill_level needs a skill_level")

    return operation, values


# --------------------------------------------------------------------------
# 2. Look up the real records and describe exactly what will happen
# --------------------------------------------------------------------------

def _clean(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def find_experience(db, name):
    """One experience whose name matches `name`, or raise ActionError."""
    name = _clean(name)
    rows = db.query("SELECT experience_id, name FROM experiences "
                    "WHERE LOWER(name) LIKE LOWER(?)", (f"%{name}%",))
    exact = [r for r in rows if r["name"].lower() == name.lower()]
    rows = exact or rows
    if not rows:
        raise ActionError(f"no experience matches '{name}'")
    if len(rows) > 1:
        names = ", ".join(f"'{r['name']}'" for r in rows)
        raise ActionError(f"'{name}' matches several experiences ({names}); please be more specific")
    return rows[0]


def find_skills(db, skill_name, experience_name=""):
    """All skills with this exact name (any case), optionally in one experience."""
    sql = ("SELECT s.skill_id, s.name, s.skill_level, e.name AS experience "
           "FROM skills s LEFT JOIN experiences e ON s.experience_id = e.experience_id "
           "WHERE LOWER(s.name) = LOWER(?)")
    params = [_clean(skill_name)]
    if _clean(experience_name):
        experience = find_experience(db, experience_name)
        sql += " AND s.experience_id = ?"
        params.append(experience["experience_id"])
    return db.query(sql + " ORDER BY s.skill_id", tuple(params))


def _where(row):
    return f"experience '{row['experience']}'" if row["experience"] else "no experience"


def prepare_action(db, operation, values):
    """Turn checked values into an Action that names the exact records."""
    destructive = OPERATIONS[operation][0]
    skill_name = _clean(values.get("skill_name"))
    experience_name = _clean(values.get("experience_name"))

    if operation == "add_skill":
        level = values.get("skill_level", 5)
        experience_id, where = None, "no experience"
        if experience_name:
            experience = find_experience(db, experience_name)
            experience_id, where = experience["experience_id"], f"experience '{experience['name']}'"
        return Action(operation, (), (skill_name, level, experience_id),
                      f"Add skill '{skill_name}' (level {level}) to {where}.", destructive)

    if operation == "delete_all_skills":
        rows = db.query("SELECT skill_id, name FROM skills ORDER BY skill_id")
        if not rows:
            raise ActionError("there are no skills to delete")
        names = ", ".join(r["name"] for r in rows)
        return Action(operation, tuple(r["skill_id"] for r in rows), (),
                      f"This will delete ALL {len(rows)} skills: {names}.", destructive)

    rows = find_skills(db, skill_name, experience_name)
    if not rows:
        where = f" in experience '{experience_name}'" if experience_name else ""
        raise ActionError(f"no skill named '{skill_name}' was found{where}")

    if operation == "delete_skill":
        if len(rows) == 1:
            text = f"This will delete skill '{rows[0]['name']}' from {_where(rows[0])}."
        else:
            listed = ", ".join(f"'{r['name']}' ({_where(r)})" for r in rows)
            text = f"This will delete {len(rows)} skills: {listed}."
        return Action(operation, tuple(r["skill_id"] for r in rows), (), text, destructive)

    # update_skill_level: overwriting data counts as destructive too
    if len(rows) > 1:
        raise ActionError(f"'{skill_name}' appears in several experiences; say which one")
    row, level = rows[0], values["skill_level"]
    return Action(operation, (row["skill_id"],), (level,),
                  f"This will change skill '{row['name']}' ({_where(row)}) "
                  f"from level {row['skill_level']} to level {level}.", destructive)


# --------------------------------------------------------------------------
# 3. Do the write - with the approval check right here
# --------------------------------------------------------------------------

def perform_action(db, action, approved=None):
    """
    Run one prepared Action and return the message for the user.

    THE APPROVAL CHECK: a destructive action only runs when `approved` is
    the very same Action object that was shown to the user and answered
    with "yes". No expert, prompt or wording can get past this line,
    because every change to the data goes through this function.
    """
    if not isinstance(action, Action) or action.operation not in OPERATIONS:
        raise ActionError("not an allowed action")
    if action.destructive and approved is not action:
        raise NotApprovedError(f"'{action.operation}' needs the user's yes first")

    if action.operation == "add_skill":
        name, level, experience_id = action.params
        existing = db.query("SELECT skill_id FROM skills WHERE LOWER(name) = LOWER(?) "
                            "AND experience_id IS ?", (name, experience_id))
        if existing:
            return f"'{name}' is already in the skills table there. Nothing was changed."
        db.query("INSERT INTO skills (experience_id, name, skill_level) VALUES (?, ?, ?)",
                 (experience_id, name, level))
        outcome = f"Added skill '{name}' (level {level})."

    elif action.operation in ("delete_skill", "delete_all_skills"):
        marks = ", ".join("?" for _ in action.skill_ids)
        db.query(f"DELETE FROM skills WHERE skill_id IN ({marks})", action.skill_ids)
        count = len(action.skill_ids)
        outcome = f"Done. Deleted {count} skill{'s' if count != 1 else ''}."

    else:  # update_skill_level
        db.query("UPDATE skills SET skill_level = ? WHERE skill_id = ?",
                 (action.params[0], action.skill_ids[0]))
        outcome = f"Done. The skill level is now {action.params[0]}."

    db.syncEmbeddings()      # new record -> new embedding; deleted -> embedding removed
    return outcome


# --------------------------------------------------------------------------
# Reading the user's answer to "Reply yes or no"
# --------------------------------------------------------------------------

def classify_reply(text):
    """'yes', 'no' or 'other'. Only a clear yes counts as yes."""
    word = re.sub(r"[^a-z ]", "", text.lower()).strip()
    if word in ("yes", "y"):
        return "yes"
    if word in ("no", "n", "cancel"):
        return "no"
    return "other"
