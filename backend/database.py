# sqlite3 is built into Python, so there's nothing to install.
# It lets Python talk to a SQLite database file.
import sqlite3

# Open a connection to the database file "study.db".
# If the file doesn't exist yet, SQLite creates an empty one.
# Think of `conn` as the notebook: it's the open database.
conn = sqlite3.connect("study.db")

# A cursor is the "pen" you use to write into the notebook.
# You'll use it to run SQL commands like CREATE TABLE and INSERT.
cursor = conn.cursor()


cursor.execute("""
CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
)
""")


cursor.execute("""
CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY,
    course_id INTEGER NOT NULL REFERENCES courses(id),
    title TEXT,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
)
""")


# chunks: one row per piece of a material, cut by chunking.py.
# embedding holds the chunk's meaning as a list of numbers, stored as
# JSON text (json.dumps going in, json.loads coming out), the same trick
# as questions.options.
cursor.execute("""
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    material_id INTEGER NOT NULL REFERENCES materials(id),
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    embedding TEXT
)
""")


# questions: validation_status records whether the question passed our
# checks ('approved', 'flagged', or 'unchecked' for questions saved
# before validation existed). Defaulting to 'unchecked' is the honest
# choice: we never claim a question passed a check it didn't go through.
# validation_reason says why a flagged question was rejected, which
# Phase 7 will use to measure how well the judge works.
cursor.execute("""
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY,
    material_id INTEGER NOT NULL REFERENCES materials(id),
    question_text TEXT NOT NULL,
    question_type TEXT NOT NULL,
    options TEXT,
    correct_answer TEXT NOT NULL,
    validation_status TEXT NOT NULL DEFAULT 'unchecked',
    validation_reason TEXT
)
""")


# question_chunks: which chunks each question was written from.
# Many-to-many (a question can draw on several chunks, and a chunk can
# inspire several questions), so each row is ONE pairing.
cursor.execute("""
CREATE TABLE IF NOT EXISTS question_chunks (
    question_id INTEGER NOT NULL REFERENCES questions(id),
    chunk_id INTEGER NOT NULL REFERENCES chunks(id)
)
""")


cursor.execute("""
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY,
    question_id INTEGER NOT NULL REFERENCES questions(id),
    student_answer TEXT NOT NULL,
    is_correct INTEGER NOT NULL,
    feedback TEXT,
    attempted_at TEXT NOT NULL
)
""")


conn.commit()