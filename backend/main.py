from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
from typing import Literal
from google import genai
from dotenv import load_dotenv
import json
from fastapi.middleware.cors import CORSMiddleware



load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev only — lock this to a real domain before shipping
    allow_methods=["*"],
    allow_headers=["*"],
)


client = genai.Client()

#BaseModel is the whole trick. Any class that inherits from Pydantic's BaseModel 
# becomes something FastAPI can (a) validate 
# incoming JSON against, and (b) automatically 
# convert outgoing Python objects into JSON.
#  That's why we don't hand-write any json.dumps() or manual parsing anywhere — 
# it's all automatic once you type things this way.



# Request Model: What the frontend sends us
class GenerateQuestionsRequest(BaseModel):
    course_text: str
    num_questions: int

class Question(BaseModel):
    question_text: str
    question_type: Literal["multiple_choice", "short_answer"] # multiple choice or short answer
    options: Optional[list[str]] = None #only used for multiple choice 
    correct_answer: str

class EvaluateAnswer(BaseModel):
    question: Question
    student_answer: str

class EvaluateAnswersRequest(BaseModel):
    answers: list[EvaluateAnswer]

class AnswerResult(BaseModel):
    question: Question
    is_correct: bool
    feedback: Optional[str] = None

class GradeResult(BaseModel):
    is_correct: bool
    feedback: str

    

#Why Optional[list[str]] = None for options.
#  A short-answer question doesn't have multiple-choice options, but a multiple-choice question does. 
# Rather than lying and putting empty options on every question, we mark the field as optional — 
# it can be a list of strings, or it can be absent (None), and it defaults to None if you don't set it. 
# This is a small preview of a bigger theme: your data model has to account for real variation in the data (not every question is the same shape), not just the happy path.





@app.post("/generate-questions")
async def generate_questions(request: GenerateQuestionsRequest) -> list[Question]:
    
    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=f"Generate {request.num_questions} quiz questions based on the following course material:\n\n{request.course_text}",
        config={
            "response_mime_type": "application/json",
            "response_schema": list[Question],

        }   
    )
    questions_data = json.loads(response.text)
    questions = [Question(**q) for q in questions_data]
    return questions


@app.post("/evaluate-answers")
async def evaluate_answers(request: EvaluateAnswersRequest) -> list[AnswerResult]:
    results = []
    for answer in request.answers:
        if answer.question.question_type == "multiple_choice":
            is_correct = answer.student_answer == answer.question.correct_answer
            result = AnswerResult(question=answer.question, is_correct=is_correct, feedback="N/A")
            results.append(result)
        else:
            response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=f"Question: {answer.question.question_text}\nCorrect answer: {answer.question.correct_answer}\nStudent's answer: {answer.student_answer}\n\nDetermine if the student's answer is correct, and give brief feedback explaining why.",
                config={
                    "response_mime_type": "application/json",
                    "response_schema": GradeResult,
                }
            )
            grade_data = json.loads(response.text)
            grade = GradeResult(**grade_data)
            result = AnswerResult(question=answer.question, is_correct=grade.is_correct, feedback=grade.feedback)
            results.append(result)
    return results






#print(response.text)

