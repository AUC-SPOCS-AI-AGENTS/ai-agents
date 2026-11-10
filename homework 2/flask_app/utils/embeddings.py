"""
embeddings.py - turn text into embedding vectors through OpenRouter.

An embedding is a list of numbers that represents the MEANING of a text.
Texts with similar meaning get similar lists of numbers.
"""

import os
import requests

EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"


class EmbeddingError(Exception):
    """Raised when an embedding can't be created. We never return a fake vector."""


def get_embedding(text, model=None):
    """
    Return the embedding of `text` as a list of floats.
    Raises EmbeddingError if anything goes wrong, so a failed call can
    never be mistaken for a real embedding (README Step 2).
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    model = model or os.getenv("EMBEDDING_MODEL")
    if not api_key:
        raise EmbeddingError("OPENROUTER_API_KEY is missing from .env")
    if not model:
        raise EmbeddingError("EMBEDDING_MODEL is missing from .env")
    if not text or not text.strip():
        raise EmbeddingError("Cannot embed empty text")

    try:
        response = requests.post(
            EMBEDDINGS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "input": text},
            timeout=30,
        )
        result = response.json()
    except Exception as error:
        raise EmbeddingError(f"Embedding request failed: {error}")

    if "error" in result:
        raise EmbeddingError(f"OpenRouter error: {result['error']}")

    try:
        vector = result["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError):
        raise EmbeddingError(f"Unexpected response from OpenRouter: {str(result)[:200]}")

    # Never accept a vector that only LOOKS valid
    if not isinstance(vector, list) or len(vector) == 0:
        raise EmbeddingError("OpenRouter returned an empty embedding")
    if not all(isinstance(x, (int, float)) for x in vector):
        raise EmbeddingError("Embedding contains values that are not numbers")
    if all(x == 0 for x in vector):
        raise EmbeddingError("OpenRouter returned an all-zero embedding")

    return [float(x) for x in vector]