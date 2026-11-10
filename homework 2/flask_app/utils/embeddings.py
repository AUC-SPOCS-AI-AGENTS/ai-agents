"""
embeddings.py — HW2 Step 2: create, validate and store embeddings.

WHAT IS AN EMBEDDING?
  A list of numbers that captures the MEANING of a piece of text.
  Texts with similar meaning get similar lists of numbers, so
  "MSU experience" ends up close to "Michigan State University".

WHAT THIS FILE DOES:
  1. get_embeddings(texts)   -> calls the embedding model through OpenRouter
  2. is_valid_vector(vec)    -> rejects empty / all-zero / broken vectors
  3. record_text(table, row) -> decides WHICH text represents each record
  4. sync_embeddings(db)     -> makes the embeddings table match the data:
                                  * new records      -> embedded
                                  * edited records   -> re-embedded (text changed)
                                  * deleted records  -> embedding removed
                                  * model changed    -> re-embedded
  5. embed_record / delete_embedding -> keep one record in sync right after a change
  6. search(db, question)    -> HW2 Step 3: search by meaning, ranked results

DESIGN DECISIONS (explain these in DESIGN_AND_TESTING.md):
  - Embeddings live in SQLite (table `embeddings`) so they survive restarts.
  - Vectors are stored as JSON text: simple, readable, no extra libraries.
  - We store the exact text that was embedded, so we can tell when a record
    was edited (stored text != current text -> re-embed).
  - A failed embedding is NEVER stored or used: we raise EmbeddingError instead.
"""

import os
import json
import math
import requests

EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"

# Primary key column of every table we embed
ID_COLUMNS = {
    'institutions': 'inst_id',
    'positions':    'position_id',
    'experiences':  'experience_id',
    'skills':       'skill_id',
}


class EmbeddingError(Exception):
    """Raised when we could not get a REAL embedding. Never silently ignored."""


# ----------------------------------------------------------------------
# 1. Calling the embedding model
# ----------------------------------------------------------------------

def get_embedding_model():
    """The model name comes from .env (EMBEDDING_MODEL), never hard-coded."""
    model = os.getenv('EMBEDDING_MODEL')
    if not model:
        raise EmbeddingError("EMBEDDING_MODEL is not set in .env")
    return model


def is_valid_vector(vec):
    """A real embedding is a non-empty list of numbers that are not all zero."""
    if not isinstance(vec, list) or len(vec) == 0:
        return False
    if not all(isinstance(x, (int, float)) for x in vec):
        return False
    return any(x != 0 for x in vec)


def get_embeddings(texts, model=None, api_key=None):
    """
    Embed a list of texts in ONE request (batching = faster and cheaper).

    Returns: a list of vectors, in the same order as `texts`.
    Raises:  EmbeddingError if anything is wrong. It never returns a fake vector.

    model / api_key can be passed in by the tests (S10: force a failure).
    """
    if not texts:
        return []

    model = model or get_embedding_model()
    api_key = api_key or os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        raise EmbeddingError("OPENROUTER_API_KEY is not set in .env")

    try:
        response = requests.post(
            EMBEDDINGS_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model, "input": texts},
            timeout=60,
        )
        result = response.json()
    except Exception as error:   # no internet, timeout, response is not JSON ...
        raise EmbeddingError(f"embedding request failed: {error}")

    if response.status_code != 200 or 'error' in result:
        message = result.get('error', {}).get('message', result) if isinstance(result, dict) else result
        raise EmbeddingError(f"embedding API error ({response.status_code}): {message}")

    data = result.get('data')
    if not isinstance(data, list) or len(data) != len(texts):
        raise EmbeddingError("embedding API returned the wrong number of vectors")

    # The API may return items in any order; 'index' tells us which text each one belongs to
    vectors = [None] * len(texts)
    for item in data:
        vectors[item.get('index', 0)] = item.get('embedding')

    for i, vec in enumerate(vectors):
        if not is_valid_vector(vec):
            raise EmbeddingError(f"invalid (empty or all-zero) vector for: {texts[i][:50]!r}")

    lengths = {len(v) for v in vectors}
    if len(lengths) != 1:
        raise EmbeddingError("vectors have different lengths")

    return vectors


# ----------------------------------------------------------------------
# 2. Which text represents each record?
# ----------------------------------------------------------------------

def _clean(*parts):
    """Join the non-empty parts with ', '."""
    return ", ".join(str(p).strip() for p in parts if p not in (None, '', 'NULL'))


def record_text(table, row):
    """
    The text we embed for one record. More context = better meaning,
    but too much unrelated text can drown out the important words.
    """
    if table == 'institutions':
        # "Michigan State University, Computer Science, East Lansing, Michigan"
        return _clean(row.get('name'), row.get('department'), row.get('city'), row.get('state'))
    if table == 'positions':
        return _clean(row.get('title'), row.get('responsibilities'))
    if table == 'experiences':
        return _clean(row.get('name'), row.get('description'))
    if table == 'skills':
        # Only the skill name: the experience text would make every skill
        # of the same experience look alike (the S2 problem).
        return _clean("Skill: " + str(row.get('name') or ''))
    raise ValueError(f"unknown table: {table}")


# ----------------------------------------------------------------------
# 3. Keeping the embeddings table in sync with the data
# ----------------------------------------------------------------------

def _save(db, table, record_id, text, vector, model):
    db.query(
        "INSERT OR REPLACE INTO embeddings (table_name, record_id, text, vector, model) "
        "VALUES (?, ?, ?, ?, ?)",
        (table, record_id, text, json.dumps(vector), model),
    )


def delete_embedding(db, table, record_id):
    """Call this right after a record is deleted."""
    db.query("DELETE FROM embeddings WHERE table_name = ? AND record_id = ?", (table, record_id))


def embed_record(db, table, record_id):
    """Call this right after a record is added or edited."""
    id_col = ID_COLUMNS[table]
    rows = db.query(f"SELECT * FROM {table} WHERE {id_col} = ?", (record_id,))
    if not rows:
        delete_embedding(db, table, record_id)
        return
    text = record_text(table, rows[0])
    model = get_embedding_model()
    vector = get_embeddings([text], model=model)[0]   # raises EmbeddingError on failure
    _save(db, table, record_id, text, vector, model)


def sync_embeddings(db):
    """
    Run at startup. Brings the embeddings table up to date with ALL records,
    whichever way they were added, edited or deleted.

    Returns a small summary dict (useful for the trace and the tests).
    """
    model = get_embedding_model()
    summary = {'embedded': 0, 'removed': 0, 'unchanged': 0}

    # What is stored right now?
    stored = {
        (r['table_name'], r['record_id']): r
        for r in db.query("SELECT table_name, record_id, text, model FROM embeddings")
    }

    # What should be stored?
    to_embed = []           # (table, record_id, text)
    current_keys = set()
    for table, id_col in ID_COLUMNS.items():
        for row in db.query(f"SELECT * FROM {table}"):
            key = (table, row[id_col])
            current_keys.add(key)
            text = record_text(table, row)
            old = stored.get(key)
            if old and old['text'] == text and old['model'] == model:
                summary['unchanged'] += 1
            else:
                to_embed.append((table, row[id_col], text))

    # Records that no longer exist -> remove their embedding
    for (table, record_id) in stored.keys() - current_keys:
        delete_embedding(db, table, record_id)
        summary['removed'] += 1

    # Embed everything new/changed in one batch request
    if to_embed:
        vectors = get_embeddings([t for _, _, t in to_embed], model=model)
        for (table, record_id, text), vector in zip(to_embed, vectors):
            _save(db, table, record_id, text, vector, model)
        summary['embedded'] = len(to_embed)

    return summary


# ----------------------------------------------------------------------
# 4. Search by meaning (HW2 Step 3)
# ----------------------------------------------------------------------

def get_min_score():
    """
    The "no match" cut-off. Results below it are thrown away.
    Chosen from REAL scores (see try_search.py), stored in .env so it can be tuned.
    """
    try:
        return float(os.getenv('MIN_SIMILARITY', '0.40'))
    except ValueError:
        return 0.40


def cosine_similarity(a, b):
    """How close two vectors are: about 1.0 = same meaning, about 0 = unrelated."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def search(db, question, tables=None, top_k=5, min_score=None):
    """
    Search by meaning.

    Args:
        question:  the user's words, e.g. "MSU experience"
        tables:    which tables to compare against, e.g. ['skills'].
                   None = all tables. (A skills question should search skills only,
                   otherwise experiences that mention "AI" push the skills out - S2.)
        top_k:     how many results to return at most
        min_score: cut-off; None = use MIN_SIMILARITY from .env. Pass 0 to see everything.

    Returns: a list of dicts, best first:
        {'table': 'institutions', 'record_id': 1,
         'text': 'Michigan State University, ...', 'score': 0.60}
        An empty list means "not found".

    Raises: EmbeddingError if the question could not be embedded
            (so a failure is never mistaken for "not found").
    """
    if min_score is None:
        min_score = get_min_score()

    model = get_embedding_model()
    question_vector = get_embeddings([question], model=model)[0]   # raises on failure

    sql = "SELECT table_name, record_id, text, vector FROM embeddings WHERE model = ?"
    params = [model]
    if tables:
        sql += f" AND table_name IN ({', '.join('?' for _ in tables)})"
        params += list(tables)

    results = []
    for row in db.query(sql, tuple(params)):
        vector = json.loads(row['vector'])
        if not is_valid_vector(vector) or len(vector) != len(question_vector):
            continue   # never match against a broken or old-model vector
        score = cosine_similarity(question_vector, vector)
        results.append({
            'table': row['table_name'],
            'record_id': row['record_id'],
            'text': row['text'],
            'score': round(score, 3),
        })

    results.sort(key=lambda r: r['score'], reverse=True)
    return [r for r in results if r['score'] >= min_score][:top_k]
