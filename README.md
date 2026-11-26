# StudySync — Smart Academic Task & Study Slot Manager

**StudySync** is a full-stack web application built for **HACK THE VIBE 2026 (Solo Vibe Coding Championship)** to help students organize courses, prioritize exams and assignments, schedule conflict-free study sessions strictly before deadlines, manage multi-format study materials, and get instant help from an integrated Student Assistant.

## Live Links & Submission Resources
- **Live Application (Render):** https://studysync-bscz.onrender.com/login
- **GitHub Repository:** https://github.com/rafiul-i02/studysync
- **YouTube Presentation & Demo:** `<YOUTUBE_URL>`

---

## Key Features
- **Course & Task Management:** Create courses and track exams/assignments with deadlines, priority levels (`high`, `medium`, `low`), estimated hours, status workflows, and search/multi-criteria filtering.
- **Today's Focus & Urgent Alerts:** Automatically surfaces overdue tasks and deadlines due within the next 24 hours at the top of the dashboard.
- **Conflict-Checked & Deadline-Strict Study Scheduler:**
  - Validates manual study slots against existing bookings, daily study limits, future-time rules, and linked task deadlines.
  - Suggests the nearest conflict-free slot strictly before the task deadline when a conflict occurs.
  - **Smart Auto-Scheduler:** Automatically allocates study blocks within configured daily study windows (`06:00–12:00` and `18:00–24:00`) sorted by priority and deadline, splitting into smaller chunks when windows are tight.
- **Multi-Format Study Resource Hub:** Upload, view/download, search, filter, and delete study resources—supporting **PDF** (`.pdf` with `%PDF-` header signature verification), **Images** (`.png`, `.jpg`, `.jpeg`, `.webp`), and **Documents** (`.docx`, `.doc`, `.txt`) up to 5 MB per file.
- **Built-in Student Assistant Chatbot:** Interactive floating assistant on the dashboard providing StudySync usage guidelines, safe arithmetic/percentage calculations (AST-parsed without `eval()`), and clear explanations of core academic subjects.
- **Role-Based Access Control (RBAC) & Security Audit Logs:** Strict ownership checks on every course, task, resource, and study slot (`student` vs. `admin`), with unauthorized access attempts logged in `/audit-logs`.

---

## Advanced Challenges & Edge Cases Implemented
1. **Challenge 1 — Conflict-Free & Deadline-Aware Auto-Scheduling (`A02`):**
   - Prevents overlapping study blocks, enforces user-defined daily study hour caps, restricts scheduling strictly prior to task deadlines, and dynamically splits tasks into smaller sub-blocks when full duration does not fit a single free window.
2. **Challenge 2 — Role-Based Ownership Enforcement, Audit Trail & File Security:**
   - Enforces per-user data isolation across all CRUD and file routes, logs allowed and blocked security events (`AuditLog`), sanitizes uploaded filenames, validates PDF magic bytes (`%PDF-`), and safely evaluates math expressions via Python's `ast` module.
3. **Edge Cases Handled:**
   - **Tight Free Window / Past Deadline:** If a task's deadline has passed or remaining free time before the deadline cannot fit the full estimated hours, the auto-scheduler schedules whatever valid chunk fits before the deadline and flags the exact reason (`deadline passed / tight free window / daily limit`).
   - **Conflicting Manual Slot:** Rejects overlapping or post-deadline slots and immediately recommends the next available conflict-free window before the deadline.

---

## Technology Stack
- **Backend:** Python 3, Flask, Flask-Login, Flask-SQLAlchemy, Gunicorn
- **Database:** PostgreSQL (Production on Render) / SQLite (Local Development)
- **Frontend:** HTML5, CSS3 (Responsive Dashboard & Floating Assistant Widget), Vanilla JavaScript
- **Deployment:** Render Web Service + Managed PostgreSQL

---

## Project Structure

```
studysync/
├── app.py                  # Flask application factory, routes, RBAC, and file handling
├── models.py               # SQLAlchemy models (User, Course, Task, TaskResource, StudySlot, AuditLog)
├── scheduler.py            # Conflict validation, free-slot finder, and deadline-aware auto-scheduler
├── assistant.py            # Safe AST math evaluator, subject explainer, and StudySync guide
├── requirements.txt        # Python dependencies
├── Procfile                # Gunicorn production start command
├── .gitignore              # Ignored local databases, uploads, and environment files
└── templates/
    ├── base.html           # Shared layout, navigation, and flash notifications
    ├── login.html          # User login page
    ├── register.html       # Student registration with daily study limit setup
    ├── dashboard.html      # Main workspace, tables, resource hub, and Student Assistant widget
    └── audit_logs.html     # Admin security and activity audit log viewer
```

Local Setup & Installation
1. Clone the repository:
   git clone [https://github.com/rafiul-i02/studysync.git](https://github.com/rafiul-i02/studysync.git)
   cd studysync
   
2. Create and activate a virtual environment (optional but recommended):
    python -m venv venv
    # Windows:
    venv\Scripts\activate
    # macOS/Linux:
    source venv/bin/activate

3. Install dependencies:
    pip install -r requirements.txt

4. Run the application locally:
    python app.py

5. Open http://127.0.0.1:5000 in your browser.
6. Register a student account,
7. Or sign in with the default seeded admin account (admin@studysync.local / Admin@123).   
