# search.py
# Job: find the chunks whose meaning is closest to a topic.

import json
import math

from database import conn           # the same open database main.py uses
from embeddings import embed_text   # turns text into its list of numbers


def cosine_similarity(a, b):
    # (unchanged) near 1 = same meaning, near 0 = unrelated
    dot = sum(x * y for x, y in zip(a, b))
    length_a = math.sqrt(sum(x * x for x in a))
    length_b = math.sqrt(sum(y * y for y in b))
    return dot / (length_a * length_b)


def search_chunks(topic, material_id, top_k=3):
    # Step 1: embed the topic. It's new text, so this happens every time.
    # It MUST be the same embedding model the chunks were embedded with,
    # otherwise the two sets of numbers live on different maps.
    topic_embedding = embed_text(topic)

    # Step 2: load this material's saved chunks and their saved embeddings.
    # (Chunks from before we added embeddings have none, so we skip them.)
    rows = conn.execute(
        "SELECT id, text, embedding FROM chunks WHERE material_id = ? AND embedding IS NOT NULL",
        (material_id,)
    ).fetchall()

    # Step 3: score every chunk against the topic.
    scored = []
    for chunk_id, text, embedding_text in rows:
        # The embedding was saved as JSON text; json.loads turns it back
        # into a list of 3,072 numbers.
        embedding = json.loads(embedding_text)
        score = cosine_similarity(topic_embedding, embedding)
        scored.append((score, chunk_id, text))

    # Step 4: best first. Python sorts tuples by their first item, which
    # is the score. Higher score = closer in meaning = better match.
    scored.sort(reverse=True)

    # Keep only the top few.
    return scored[:top_k]


def spread_chunks(material_id, k=3):
    # For when the student gives NO topic: pick k chunks spaced evenly
    # across the whole material, so the questions cover all of it instead
    # of just the beginning. The prompt stays small however long the
    # material is, which is the whole point of chunking.

    # Load the chunks in their original order (chunk_index keeps it).
    rows = conn.execute(
        "SELECT id, text FROM chunks WHERE material_id = ? ORDER BY chunk_index",
        (material_id,)
    ).fetchall()

    # Few chunks? Just use them all, there's nothing to spread.
    if len(rows) <= k:
        return rows

    # Picture the material cut into k equal segments and take the first
    # chunk of each. i * len(rows) // k does that: multiply first, THEN
    # divide, so leftover chunks spread across the picks instead of
    # being dropped. 100 chunks, k=5 -> 0, 20, 40, 60, 80.
    # 5 chunks, k=3 -> 0, 1, 3.
    return [rows[i * len(rows) // k] for i in range(k)]






# Self-test: search the most recently saved material for "chain rule".
if __name__ == "__main__":
    # Find the newest material that has embedded chunks.
    material_id = conn.execute(
        "SELECT MAX(material_id) FROM chunks WHERE embedding IS NOT NULL"
    ).fetchone()[0]

    # Test the no-topic path: which chunks get picked?
    for chunk_id, text in spread_chunks(material_id, k=3):
        print(chunk_id, text[:60])