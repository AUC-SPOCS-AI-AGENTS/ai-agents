"""
semantic_search.py - search the resume by MEANING instead of exact words.

How it works:
  1. turn the user's question into an embedding (a meaning vector)
  2. compare it with every stored embedding using cosine similarity
  3. return the best matches, ranked from most to least similar
"""

import json
import math
import os

from flask_app.utils.embeddings import get_embedding

SEARCHABLE_TABLES = ['institutions', 'positions', 'experiences', 'skills']


def cosine_similarity(a, b):
    """
    How similar two vectors are, from -1 (opposite) to 1 (same direction).
    For text embeddings: higher = closer in meaning.
    """
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def semantic_search(db, query, tables=None, top_k=5, min_score=None):
    """
    Find the records whose meaning is closest to `query`.

    Args:
        db        : the database object
        query     : the user's words, e.g. "MSU experience"
        tables    : which tables to search (default: all four)
        top_k     : how many results to return at most
        min_score : results below this score count as "no match"
                    (default: SEARCH_MIN_SCORE from .env)

    Returns:
        (matches, all_scored)
        matches    : results >= min_score, best first, at most top_k
        all_scored : every result with its score, best first (for the trace)
        Each result: {'table', 'id', 'text', 'score'}

    Raises:
        EmbeddingError if the question can't be embedded. We never
        search with a fake vector.
    """
    tables = tables or SEARCHABLE_TABLES
    unknown = [t for t in tables if t not in SEARCHABLE_TABLES]
    if unknown:
        raise ValueError(f"Unknown table(s): {unknown}")

    if min_score is None:
        if tables == ['skills']:
            # Skill records are just a short name, so their scores run lower.
            # Measured: Machine Learning 0.381, NLP 0.267, Public Speaking 0.178.
            min_score = float(os.getenv('SKILL_MIN_SCORE', '0.25'))
        else:
            # Measured: MSU 0.620 vs best unrelated (Harvard query) 0.298.
            min_score = float(os.getenv('SEARCH_MIN_SCORE', '0.35'))

    query_vector = get_embedding(query)     # may raise EmbeddingError     # may raise EmbeddingError

    placeholders = ', '.join('?' for _ in tables)
    rows = db.query(
        f"SELECT source_table, record_id, text, vector FROM embeddings "
        f"WHERE source_table IN ({placeholders})",
        tuple(tables),
    )

    all_scored = []
    for row in rows:
        score = cosine_similarity(query_vector, json.loads(row['vector']))
        all_scored.append({
            'table': row['source_table'],
            'id': row['record_id'],
            'text': row['text'],
            'score': round(score, 3),
        })
    all_scored.sort(key=lambda r: r['score'], reverse=True)

    matches = [r for r in all_scored if r['score'] >= min_score][:top_k]
    return matches, all_scored
