# embeddings.py
# Job: turn a piece of text into its embedding, a list of numbers that
# says what the text MEANS (pin location on the map of meaning).
# This is the same call as try_embedding.py, wrapped in a reusable function.

from dotenv import load_dotenv
from google import genai

# main.py imports this file BEFORE it calls load_dotenv(), so we load the
# .env file here too. Otherwise genai.Client() wouldn't find the API key.
load_dotenv()

# Created once at module level and reused (same Phase 1 lesson as in main.py).
client = genai.Client()

# The model name lives in one place, so changing it later is a one-line edit.
EMBEDDING_MODEL = "gemini-embedding-2"


def embed_text(text):
    # Send the text to the embedding model (a different model from the one
    # that writes questions) and get back its coordinates.
    result = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
    )
    # result.embeddings is a list with one entry per text we sent. We sent
    # one text, so we take entry 0, then pull out its list of numbers.
    return result.embeddings[0].values


# Quick self-test: only runs when you run this file directly.
if __name__ == "__main__":
    print(len(embed_text("enzyme")))