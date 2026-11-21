# validation.py
# Job: decide whether a generated question is trustworthy BEFORE a student
# sees it. Phase 1's schema guarantees a question's SHAPE; it can't
# guarantee the question is TRUE or well-formed. That's what this file is for.
#
# Layer 1: cheap rule checks in plain code. Free, instant, and perfectly
#          reliable, the same principle as grading multiple choice with ==.
# Layer 2: a Gemini "judge" that checks the question against its source
#          chunk, for the things plain code can't check (meaning).

import time
from google.genai import errors
import json

from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel

load_dotenv()          # same reason as embeddings.py: find the API key
client = genai.Client()


# ---------------------------------------------------------------------------
# Layer 1: plain-code rules
# ---------------------------------------------------------------------------

def check_basic_rules(q):
    # q is any object with question_type, options, and correct_answer.
    # Returns a list of problems. An empty list means "passed".
    problems = []

    if q.question_type == "multiple_choice":
        if not q.options:
            problems.append("multiple choice question has no options")
        elif q.correct_answer not in q.options:
            # The grader compares with ==, so the answer key must match
            # one option EXACTLY or no student can ever get it right.
            problems.append("correct answer is not one of the options")

    return problems


# ---------------------------------------------------------------------------
# Layer 2: the LLM judge
# ---------------------------------------------------------------------------

# What the judge returns: its verdict and a short reason. Same pattern as
# GradeResult in main.py: a small schema, so the output shape is guaranteed.
class SupportVerdict(BaseModel):
    supported: bool
    reason: str


def judge_support(q, chunk_texts, attempts=3):
    # Ask Gemini: do these source passages support this question AND its
    # answer key? chunk_texts is a list of the chunk texts the question cited.
    passage = "\n\n".join(chunk_texts)

    for attempt in range(attempts):
        try:
            response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=(
                    "You are checking a quiz question against its source passage.\n"
                    "Use ONLY the passage. Do not use your own knowledge: a question "
                    "can be true in the real world and still be unsupported by this "
                    "passage, and that counts as NOT supported.\n"
                    "The question is supported only if the passage contains the "
                    "information needed to answer it AND the stated correct answer "
                    "agrees with the passage.\n\n"
                    f"Passage:\n{passage}\n\n"
                    f"Question: {q.question_text}\n"
                    f"Stated correct answer: {q.correct_answer}"
                ),
                config={
                    "response_mime_type": "application/json",
                    "response_schema": SupportVerdict,
                }
            )
            # Re-validate locally, the same defense-in-depth habit as everywhere else.
            return SupportVerdict(**json.loads(response.text))

        # Only retry errors that are the SERVER's fault (5xx, like the 503).
        # A 4xx (our request was bad) is a different error class, so it isn't
        # caught here and fails immediately: resending it would fail again.
        except errors.ServerError:
            if attempt == attempts - 1:
                raise                      # out of tries: let the caller handle it
            time.sleep(2 ** (attempt + 1)) # wait 2s, then 4s, between tries


# Self-test: two cases against the same passage (needs the API key; makes
# two Gemini calls).
if __name__ == "__main__":
    from types import SimpleNamespace  # a quick stand-in for a question

    chain_rule_chunk = (
        "The chain rule handles composite functions, where one function is "
        "nested inside another. If y = f(g(x)), then dy/dx = f'(g(x)) times "
        "g'(x). For example, the derivative of (3x + 1)^5 is "
        "15(3x + 1)^4."
    )

    # Case 1: the passage really does support this question.
    supported_q = SimpleNamespace(
        question_text="What is the derivative of (3x + 1)^5?",
        correct_answer="15(3x + 1)^4")

    # Case 2: a question about something the passage never mentions.
    unsupported_q = SimpleNamespace(
        question_text="What is the formula for the quotient rule?",
        correct_answer="[f'(x)g(x) - f(x)g'(x)] / [g(x)]^2")
    
    # Case 3: the question IS covered by the passage, but the answer key is
    # wrong. (The passage says 15(3x + 1)^4, not ^5.)
    wrong_key_q = SimpleNamespace(
        question_text="What is the derivative of (3x + 1)^5?",
        correct_answer="15(3x + 1)^5")

    print("supported:  ", judge_support(supported_q, [chain_rule_chunk]))
    print("unsupported:", judge_support(unsupported_q, [chain_rule_chunk]))
    print("wrong key:  ", judge_support(wrong_key_q, [chain_rule_chunk]))