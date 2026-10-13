from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from typing import Literal
from google import genai
from dotenv import load_dotenv
import json
from fastapi.middleware.cors import CORSMiddleware
from database import conn
from datetime import datetime


load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev only — lock this to a real domain before shipping
    allow_methods=["*"],
    allow_headers=["*"],
)


client = genai.Client()

# BaseModel is the whole trick. Any class that inherits from Pydantic's BaseModel
# becomes something FastAPI can (a) validate incoming JSON against, and
# (b) automatically convert outgoing Python objects into JSON.
# That's why we don't hand-write any json.dumps() or manual parsing for requests/responses —
# it's all automatic once you type things this way.


# ---------------------------------------------------------------------------
# Models: the "front counter" — what is allowed to cross between browser and server
# ---------------------------------------------------------------------------

# What the browser sends to /generate-questions
class GenerateQuestionsRequest(BaseModel):
    course_text: str
    num_questions: int


# The FULL question, including the answer key. Used inside the server only:
# it's the shape Gemini generates and the shape we save in the database.
# Optional[list[str]] = None for options: short-answer questions have no options,
# so the field can be absent (None) rather than lying with an empty list.
class Question(BaseModel):
    question_text: str
    question_type: Literal["multiple_choice", "short_answer"]
    options: Optional[list[str]] = None
    correct_answer: str


# The browser-safe question: a ticket (id) and NO correct_answer.
# The safety is built into the shape — this model has no field to leak the answer with.
class QuestionOut(BaseModel):
    id: int
    question_text: str
    question_type: Literal["multiple_choice", "short_answer"]
    options: Optional[list[str]] = None


# What the browser sends back per answer: the ticket and what the student typed.
class SubmittedAnswer(BaseModel):
    question_id: int
    student_answer: str


class EvaluateAnswersRequest(BaseModel):
    answers: list[SubmittedAnswer]


# What Gemini produces when grading a short answer: its judgment only.
class GradeResult(BaseModel):
    is_correct: bool
    feedback: str


# ---------------------------------------------------------------------------
# Routes: the "staff" — they talk to the database and to Gemini
# ---------------------------------------------------------------------------

@app.post("/generate-questions")
async def generate_questions(request: GenerateQuestionsRequest) -> list[QuestionOut]:
    # 1. Save a placeholder course and the pasted text as a material
    cursor = conn.execute(
        "INSERT INTO courses (name, created_at) VALUES (?, ?)",
        ("Untitled course", datetime.now().isoformat())
    )
    course_id = cursor.lastrowid

    cursor = conn.execute(
        "INSERT INTO materials (course_id, title, text, created_at) VALUES (?, ?, ?, ?)",
        (course_id, None, request.course_text, datetime.now().isoformat())
    )
    material_id = cursor.lastrowid

    # 2. Ask Gemini for questions (schema-constrained structured output)
    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=f"Generate {request.num_questions} quiz questions based on the following course material:\n\n{request.course_text}",
        config={
            "response_mime_type": "application/json",
            "response_schema": list[Question],
        }
    )
    questions_data = json.loads(response.text)
    questions = [Question(**q) for q in questions_data]  # defense in depth: re-validate

    # 3. Save each question (with its correct_answer) in the back room,
    #    and build the browser-safe version (ticket, no coat)
    questions_out = []
    for q in questions:
        options_text = json.dumps(q.options) if q.options is not None else None
        cursor = conn.execute(
            "INSERT INTO questions (material_id, question_text, question_type, options, correct_answer) VALUES (?, ?, ?, ?, ?)",
            (material_id, q.question_text, q.question_type, options_text, q.correct_answer)
        )
        question_id = cursor.lastrowid
        questions_out.append(QuestionOut(
            id=question_id,
            question_text=q.question_text,
            question_type=q.question_type,
            options=q.options,
        ))

    # 4. Make everything permanent, then return only the safe version
    conn.commit()
    return questions_out


@app.post("/evaluate-answers")
async def evaluate_answers(request: EvaluateAnswersRequest):
    results = []
    for submitted in request.answers:
        # Look up the answer key ourselves — the browser never supplies it
        row = conn.execute(
            "SELECT question_text, question_type, correct_answer FROM questions WHERE id = ?",
            (submitted.question_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Question {submitted.question_id} not found")
        question_text, question_type, correct_answer = row

        if question_type == "multiple_choice":
            # Deterministic: plain comparison, no LLM needed
            is_correct = submitted.student_answer == correct_answer
            feedback = None
        else:
            # Short answer: Gemini judges semantic correctness
            response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=f"Question: {question_text}\nCorrect answer: {correct_answer}\nStudent's answer: {submitted.student_answer}\n\nDetermine if the student's answer is correct, and give brief feedback explaining why.",
                config={
                    "response_mime_type": "application/json",
                    "response_schema": GradeResult,
                }
            )
            grade = GradeResult(**json.loads(response.text))
            is_correct = grade.is_correct
            feedback = grade.feedback

        # Save this attempt (append-only: a new row every time, never overwritten)
        conn.execute(
            "INSERT INTO attempts (question_id, student_answer, is_correct, feedback, attempted_at) VALUES (?, ?, ?, ?, ?)",
            (submitted.question_id, submitted.student_answer, is_correct, feedback, datetime.now().isoformat())
        )

        results.append({
            "question_id": submitted.question_id,
            "is_correct": is_correct,
            "feedback": feedback,
            "correct_answer": correct_answer
        })

    conn.commit()
    return results