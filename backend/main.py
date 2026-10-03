from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
from typing import Literal
from google import genai
from dotenv import load_dotenv
import json


load_dotenv()

app = FastAPI()
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



#print(response.text)

