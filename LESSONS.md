# Lessons Learned — AI-Powered Study Platform

A running technical log of concepts covered while building this project. Each entry: the problem, the simplest version of the idea, why it mattered *here*, and what we actually implemented. Meant to be referenced in interviews, essays, or future projects — not just a changelog.

---

## Phase 1 — Basic Product

### 1. Pydantic models as a validation contract (not just a data container)

**Problem it solves:** Raw incoming JSON (from a frontend, or from an LLM) is untrusted and unstructured until proven otherwise. Without a contract, you're hoping the data is shaped correctly.

**Simplest version:** A class with typed attributes. Pydantic's `BaseModel` adds automatic validation (reject bad data) and serialization (convert to/from JSON) for free, just from type annotations.

**Why it mattered here:** FastAPI uses a Pydantic model on a route parameter to auto-validate every incoming request body — no manual JSON parsing anywhere in the app.

**Gotcha hit:** `correct_answer = str` (assignment) vs `correct_answer: str` (type annotation) — the colon is what tells Pydantic "this is a typed field." One misplaced `=` broke model construction entirely.

### 2. `Literal` types: constraining *content*, not just *shape*

**Problem it solves:** A field typed as plain `str` accepts *any* string. `question_type: str` allowed Gemini to return `"multiple-choice"` (hyphen) instead of `"multiple_choice"` (underscore) — valid by type, wrong by convention, and silently broke any code comparing against the expected value.

**Simplest version:** `Literal["a", "b"]` restricts a field to an exact closed set of values, enforced by Pydantic at validation time.

**Why it mattered here:** This was the fix for the hyphen/underscore bug — and it also became a formal constraint the LLM itself had to obey once passed through as a schema (see entry 4 below).

### 3. Separating request and response models

**Why:** `GenerateQuestionsRequest` (what the client sends) and `Question` (one unit of actual content) represent different concepts that happen to be involved in the same round trip. Keeping them as separate classes avoids awkward overloading as the API grows (e.g. adding a `session_id` to the request shouldn't touch the `Question` shape).

### 4. Structured output / schema-constrained generation

**Problem it solves:** Prompting an LLM to "please respond in JSON" is a soft request — the model can add preamble, deviate from the exact shape, or violate expected value sets. Downstream code that assumes a specific shape breaks the moment the model deviates.

**Simplest version:** Hand the model a formal schema (not just a description in English) and have the inference process itself be *constrained* to only generate tokens consistent with that schema.

**Mechanically, what happens (Gemini + `google-genai` SDK):**
1. A Pydantic model (e.g. `Question`) can generate a JSON Schema via `.model_json_schema()` — a formal description of required fields, types, and (via `Literal`) enums.
2. Passing `response_schema=list[Question]` to `generate_content()` hands this derived schema to the API.
3. Gemini applies **constrained decoding**: at each generation step, the model's token probability distribution is restricted to only tokens that keep the output a valid partial match against the schema. This is enforced at the inference/sampling level — not a request the model can choose to ignore, unlike prompt-based instructions.
4. `Literal["multiple_choice", "short_answer"]` becomes an `"enum"` in the schema — this is *why* schema-constrained generation fixed the hyphen bug: the model became structurally incapable of producing a disallowed string, not just less likely to.

**Important distinction — structure vs. correctness:** schema enforcement guarantees the *shape* of the data (right fields, right types, right allowed values) — it says nothing about whether the *content* is factually correct or a good question. A perfectly schema-valid question can still be wrong. This split is exactly what Phase 4 (validation) exists to address.

**Defense in depth:** even with schema enforcement, we still re-validate parsed data through Pydantic (`Question(**q)`) on our own side rather than trusting Gemini's guarantee as the only safety check — external systems' guarantees should be a strong signal, not your only line of defense.

### 5. Function scope and where code "lives"

**Gotcha hit:** Code written at module level (outside any `def`) runs exactly once, at import/startup time — not per-request. Early draft of the Gemini call sat outside `generate_questions()`, which meant it (a) only ran once ever, and (b) referenced `request`, a variable that only exists inside the route function's own scope, causing a `NameError`.

**Lesson:** Anything that needs to happen fresh per incoming request belongs *inside* the route function. Anything expensive that's safe to set up once (e.g. `genai.Client()`) belongs at module level, created once, reused across requests — not recreated on every call.

### 6. CORS — why the browser blocks your own frontend from calling your own backend

**Problem it solves:** by default, browsers enforce the "same-origin policy" — JavaScript running on one origin (e.g. a local HTML file, or `http://localhost:5173`) is blocked from making requests to a different origin (e.g. your FastAPI server at `http://127.0.0.1:8000`), even though you control both. This isn't FastAPI being difficult — it's the browser protecting users from malicious sites silently calling other sites' APIs using the user's cookies/session.

**Why it matters here:** your frontend and backend run as two separate processes on two different addresses/ports. Without explicitly allowing it, every `fetch()` call from the frontend to your API gets silently blocked by the browser with a CORS error in the console — even though the request is completely legitimate.

**Fix:** FastAPI's `CORSMiddleware`, explicitly listing which origins are allowed to call the API. In development this is often permissive (`allow_origins=["*"]`); in a real deployed product you'd lock this down to your actual frontend's real domain, not `*`.

### 7. Secrets management with `.env`

**Problem it solves:** Hardcoding an API key directly in source code means it ends up in git history permanently the moment it's committed — recoverable by anyone with repo access, forever, even after a later "fix."

**Implementation:** key stored in `.env` (git-ignored), loaded into `os.environ` at runtime via `python-dotenv`'s `load_dotenv()`. SDK clients (like `genai.Client()`) often check well-known environment variable names automatically, with no key passed explicitly in code.

### 8. Evaluation design: deterministic vs. LLM-graded branches

**Pattern used:** the evaluate route branches on `question_type`. Multiple choice is graded with plain Python string comparison — fast, free, perfectly reliable, no ambiguity to resolve. Short answer is graded via a second Gemini call, using the same schema-constrained-output pattern as question generation, but with a smaller purpose-built schema (`GradeResult: {is_correct, feedback}`) distinct from the question-generation schema.

**Why `GradeResult` is separate from what the API returns:** `GradeResult` is only what the LLM needs to produce (its judgment). What the route returns to the client is a different thing with different fields. Keeping "what the LLM outputs" separate from "what the API returns" avoids conflating two different concerns into one schema.

**Known gap found during testing (fixed in Phase 2):** `correct_answer` had to travel through the client between generate and evaluate steps, since nothing was persisted server-side — a real trust-boundary issue, not a logic bug.

### Phase 1 end-to-end test result

Full click-through (generate → answer → submit → results) worked cleanly, including both the deterministic and LLM-graded branches.

---

## Phase 2 — Persistent Performance

### 1. Why the app needs a database at all

**Problem it solves:** In Phase 1 nothing ever reaches the server's memory. Questions live only in the browser tab, so closing it loses everything: no question history, no performance tracking, no measurements over time. A database gives the *server* a permanent memory of its own.

### 2. SQLite vs. Postgres — the decision and why

**SQLite** is a library, not a server: the whole database is one file (`study.db`) that the Python process reads and writes directly. Nothing to install (the `sqlite3` module ships with Python), no ports, no passwords.

**Postgres** is a separate server process the app connects to over a network. Far more powerful (many concurrent users, permissions, extensions like `pgvector`), but needs to be run and configured (usually Docker).

**Choice for Phase 2: SQLite.** The app is single-user and local, Postgres's strengths solve problems we don't have yet, and the skill being learned (schema design) is identical in both. Switching later stays cheap if we use standard SQL and keep database access in one place.

**Deferred decision:** Postgres + `pgvector` is a common real-world RAG stack. Where *embeddings* should live is a Phase 3 question, and we'll decide it then with a real reason rather than guessing now.

### 3. The core relational ideas

- **Table:** like a spreadsheet with fixed, typed columns. Each row is one record.
- **Primary key:** a value that uniquely identifies each row (`id INTEGER PRIMARY KEY`). Also the "ticket number" that fixes the trust-boundary problem (see entry 6).
- **Foreign key:** a column holding another table's primary key (`REFERENCES courses(id)`).
- **The rule:** the foreign key lives on the **"many" side**, which is the same as the "belongs to" side. A question *belongs to* a material, a material *belongs to* a course, an attempt *belongs to* a question. Whichever table you'd describe with "belongs to" holds the key.
- **Common slip (hit repeatedly):** flipping the direction. The sentence test fixes it: a question row can say "I came from material 4," but a material row can't hold "I produced questions 7, 8, 9, 10…" in one cell.

### 4. Junction tables for many-to-many

**Problem:** a question can test many concepts, and a concept can be tested by many questions. A single `concept_id` column on `questions` can't hold multiple values.

**Fix:** a third table whose rows are the pairings themselves:

| question_id | concept_id |
|-------------|------------|
| 1 | 1 |
| 2 | 2 |
| 2 | 3 |

Question 2 simply gets two rows. Finding all questions for concept 3 is `SELECT question_id FROM question_concepts WHERE concept_id = 3;`, and a `JOIN` lines up rows across two tables wherever two columns match to get the question *text*.

**Status:** designed but **not built yet.** `concepts` and `question_concepts` only matter in Phase 5, so adding them now would be guessing.

### 5. The schema we built

```
courses → materials → questions → attempts
(each arrow: the right-hand table holds the ID of the left-hand one)
```

- `courses`: id, name, created_at
- `materials`: id, course_id, title, text, created_at
- `questions`: id, material_id, question_text, question_type, options, correct_answer
- `attempts`: id, question_id, student_answer, is_correct, feedback, attempted_at

**Design choices worth remembering:**
- **Attempts are append-only.** Each answer is a new row with a timestamp, never an overwrite, because "discover lapses in knowledge" needs history over time.
- **`feedback` is nullable** (no `NOT NULL`) so multiple choice can honestly store "nothing" instead of an `"N/A"` sentinel. The `"N/A"` hack is now gone from both backend and frontend.
- **`options` is nullable** because short-answer questions have none.
- **SQLite has no boolean type**, so `is_correct` is `INTEGER` (1 / 0).
- **"Don't repeat questions" needs no extra table.** It falls out of having `questions` and `attempts` separate: "questions not yet attempted" is just a query.
- **Order of `CREATE TABLE`:** parents first. SQLite is lenient about referencing a table that doesn't exist yet; Postgres is strict. Parents-first works everywhere.

### 6. The trust-boundary fix (coat-check model)

**The real problem was worse than "inspectable."** Phase 1's evaluate route accepted the whole `Question` from the client, including `correct_answer`. A student could not only *read* the answer but *write* it: send a question whose `correct_answer` equals their own wrong answer and the server marks it correct. The server never verified that the question it was grading was one it actually generated.

**Coat-check analogy:** the coat is `correct_answer` and stays in the back room (the database). The ticket is the `question_id`, which is all the browser holds. The server looks things up itself.

**Two moments:**
1. **Generation:** the LLM writes the question and its `correct_answer` once. The server saves them and returns questions to the browser with `id`s but **without** `correct_answer`.
2. **Evaluation:** the browser sends only `question_id` + `student_answer`. The server reads `correct_answer` from its own database and grades. (For short answer the LLM acts as a *grader* comparing two texts, not as the source of the answer.)

**Why a tampered id doesn't help:** changing id 7 to 12 just makes the server grade against question 12. The student controls *which ticket they present*, never what's in the back room.

**Caveat / later refinement:** a student could still choose to answer a different question than the one shown. A rule like "you can only answer questions that belong to your session" is a later hardening step.

### 7. Storing a list in one cell: JSON as text

**Problem:** `options` is a `list[str]` in Pydantic, but a database cell holds a single value.

**Fix:** store it as JSON text.
- Going in: `json.dumps(list)` (the "s" is for *string*: dump **to** a string).
- Coming out: `json.loads(text)` (load **from** a string).
- **Guard for `None`:** `json.dumps(None)` yields the text `"null"`, not a true empty cell. So:

```python
options_text = json.dumps(q.options) if q.options is not None else None
```

### 8. Using SQLite from Python (`database.py`)

```python
import sqlite3                       # built in, nothing to pip install
conn = sqlite3.connect("study.db")   # creates the file if missing; conn = the notebook
cursor = conn.cursor()               # the pen you write with
cursor.execute("CREATE TABLE IF NOT EXISTS ...")
conn.commit()                        # nothing is permanent until you commit
```

- **`IF NOT EXISTS`** makes the file safe to run repeatedly.
- **`commit()`** is the "save" button; changes are pending until it runs.
- **`main.py` does `from database import conn`.** Importing runs `database.py` once, which makes sure the tables exist and shares the same connection.
- **File location gotcha:** `connect("study.db")` is a relative path, so the file is created in whatever folder the server is started from. Start Uvicorn from `backend/` every time (or switch to an absolute path later) so there's only ever one `study.db`.
- **Mac gotcha:** the command is `python3`, not `python`, unless a virtual environment is active.

### 9. Two models per audience: `Question` vs. `QuestionOut`

**Problem:** the same question needs two shapes. Inside the server it includes `correct_answer`. Going to the browser it must not.

**Fix:** `Question` is the full shape (what Gemini generates and what we save). `QuestionOut` is the browser-safe shape: `id`, `question_text`, `question_type`, `options`, and no `correct_answer`.

**Why it's strong:** the safety is built into the *shape*. If a route returns `QuestionOut`, `correct_answer` can't leak, because the model has no field to carry it. Same idea as keeping `GradeResult` (what the LLM outputs) separate from what the API returns.

The browser-to-server direction mirrors it: `SubmittedAnswer` has only `question_id: int` and `student_answer: str`, with no question object inside.

### 10. Saving and the ticket: `INSERT`, placeholders, `lastrowid`

```python
cursor = conn.execute(
    "INSERT INTO courses (name, created_at) VALUES (?, ?)",
    ("Untitled course", datetime.now().isoformat())
)
course_id = cursor.lastrowid
```

- `INSERT INTO table (columns) VALUES (...)`: first half names the columns, second half holds the values, in the same order.
- **`?` placeholders** hold open one blank per value; the tuple fills them left to right. Never paste values into the SQL text: an apostrophe in a question would break the command, and someone could smuggle in SQL of their own (SQL injection). With placeholders, whatever fills a blank is treated purely as data.
- **Debug rule:** when an insert fails, count the columns, the `?` marks, and the tuple values. All three must be equal.
- **`cursor.lastrowid`** is the `id` the database just assigned to the new row. The chain is: save the course (get `course_id`), save the material with it (get `material_id`), save each question with it (get `question_id`, the ticket the browser holds).
- `datetime.now().isoformat()` is the timestamp text for every `created_at` / `attempted_at`.
- **The placeholder course:** `materials.course_id` is `NOT NULL`, and there's no course screen yet, so each generation creates an `"Untitled course"`. Real course management comes later.

### 11. Reading a row back: `SELECT`, `WHERE`, `fetchone`, and the 404 guard

```python
row = conn.execute(
    "SELECT question_text, question_type, correct_answer FROM questions WHERE id = ?",
    (submitted.question_id,)
).fetchone()
if row is None:
    raise HTTPException(status_code=404, detail=f"Question {submitted.question_id} not found")
question_text, question_type, correct_answer = row
```

- `fetchone()` returns one row as a tuple in the order of the `SELECT` columns, or `None` if nothing matched.
- A one-item tuple needs the trailing comma: `(submitted.question_id,)`.
- Inside `questions`, the browser's `question_id` is compared against the table's own `id` (primary key). The name `question_id` only exists in the request and in `attempts`.
- **Why a 404 and not a crash or a silent skip:** a bad id is the *client's* mistake. HTTP status codes encode that: **4xx = client error, 5xx = server error.** A crash would report a server bug (500) for something the server did correctly. Silently skipping would quietly corrupt the student's score.
- Tuple unpacking (`a, b, c = row`) gives named variables instead of `row[0]`, `row[1]`.

### 12. Append-only attempts and where `commit()` goes

Every graded answer inserts a **new** `attempts` row. Nothing is ever updated or overwritten. Submitting the same question twice creates two rows, which is exactly the history that Phase 5 needs.

`conn.commit()` goes **after** the loop, at the same indentation as `return`, so all attempts from one submission are saved together. Without it the inserts stay pending and vanish.

**What attempts can tell you that a score can't:**
- **Number of attempts** (per *concept*, once concepts exist) shows struggle. A repeat attempt right after seeing the answer is weaker evidence than a cold one.
- **Quality of the attempt** shows understanding. For multiple choice, `student_answer` records *which* wrong option was picked, which can point to a specific misconception. For short answer, `feedback` records why it was off.
- **Timestamps** show improvement over time and forgetting after a gap, the basis of spaced repetition.

### 13. Revealing the correct answer after grading

The server now returns `correct_answer` in the evaluate response, so the results screen can show it. That doesn't undo the trust-boundary fix: the coat stays in the back room until the student has committed an answer.

**Known caveat:** a student could resubmit the same question after seeing the answer. Harmless for a study tool, but Phase 5 mastery tracking should weigh a repeat attempt differently from a first try.

### 14. Refactoring pattern: build alongside, then replace

Instead of rewriting `/evaluate-answers` in place, we added `EvaluateAnswersRequest2` and `/evaluate-answers-v2`, tested it with real ids and fake ones, and only then deleted the old classes and route and renamed the new ones. The old behavior stayed available as a reference until the new one was proven. Temporary names (`2`, `-v2`) are a signal to clean up.

### 15. Bugs and gotchas hit this phase

- **Indentation = scope.** Pasting the insert code with only its first line indented under the `def` made later lines fall out of the function. They ran at module level where `request` and `course_id` don't exist, producing "X is not defined." When you see that error, ask whether the code using X is still inside the function that creates it.
- **`cursor` isn't imported.** It's a variable created by `conn.execute(...)`; only `conn` is imported.
- **Test with real data, and say when you haven't.** An empty `SELECT` result meant no questions had been generated yet since the saving code was added, not a broken database. Don't trust a test you didn't run.
- **`EvaluateAnswersRequest` vs. `GradeResult`:** the schema passed to Gemini must be the same class used to parse its reply (`GradeResult`).

### 16. Git hygiene

- **Never commit the database.** `study.db` is data, not code. `database.py` rebuilds it. It's in `.gitignore`.
- **`.gitignore` newline gotcha:** `echo "study.db" >> .gitignore` glued onto the last line (`.vscode/study.db`) because the file didn't end in a newline. Always check the file after appending.
- **Stage deliberately.** `git add .` is safe once ignores are right, but it only covers the current folder and below, so run it from the repo root and read `git status` before committing.
- **Verify assumptions with `ls`.** A file assumed to be a stray duplicate (`frontend_index.html`) turned out to be the real, never-committed frontend; `frontend/` was empty. It now lives at `frontend/index.html`.

### Status at end of Phase 2

- ✅ Schema designed, built (`database.py`), and understood
- ✅ `/generate-questions` saves course, material, and questions; returns `QuestionOut` (ids, no answers)
- ✅ `/evaluate-answers` takes `question_id` + `student_answer`, looks up ground truth server-side, grades (deterministic or Gemini), saves an attempt, and returns the correct answer
- ✅ Frontend updated and tested end to end with real notes (science and math)
- ⏭️ Deferred: `concepts` and `question_concepts` tables (Phase 5), real course management, session scoping on question ids, absolute path for `study.db`
- ⏭️ Known smell: routes are `async def` but the Gemini and SQLite calls are blocking; fine for one local user

---

## Phase 3 — Source-Grounded Generation / RAG (upcoming)
*(chunking, embeddings, vector similarity, retrieval — to be filled in)*

## Phase 4 — Question Validation (upcoming)

## Phase 5 — Concept Mastery (upcoming)
*(build `concepts` and `question_concepts` junction table here)*

## Phase 6 — Adaptive Practice (upcoming)

## Phase 7 — Evaluation (upcoming)
