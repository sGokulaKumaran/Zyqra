# 🧠 SmartLearn AI — Setup Guide

## What's in this app
- **Authentication** — Sign up / sign in with username + password
- **Persistent Chat History** — All chats saved to a local SQLite database, survives restarts
- **Quiz Tab** — Generate quizzes, answer, submit, get instant evaluation + explanations
- **Dashboard Tab** — Performance analytics (per session AND overall across all sessions)
- **Dark / Light Theme** — Toggle in sidebar
- **All original modes** — Free Chat, Study Module, Roadmap, Adaptive Suggestions, Document Analysis, Voice Questions
- **Visual Search** — When you ask for diagrams, AI gives a search query to find the best image

---

## Database Setup (Automatic!)

The app uses **SQLite** — no external database server needed.

When you run the app for the first time, it automatically creates `smartlearn.db` in the same folder.

**What's stored:**
| Table | What it saves |
|-------|--------------|
| `users` | Username + hashed password |
| `sessions` | Each chat session per user |
| `messages` | All messages in every session |
| `quiz_results` | Every quiz result for analytics |

> ⚠️ **Important:** Never delete `smartlearn.db` — that's where all user data lives.
> For production, use PostgreSQL or MySQL instead.

---

## Installation & Running

### Step 1 — Install Python packages
```bash
pip install -r requirements.txt
```

### Step 2 — Run the app
```bash
streamlit run app.py
```

### Step 3 — Open in browser
Go to: `http://localhost:8501`

---

## First Time Setup
1. Click **"Create Account"** tab on the login screen
2. Choose a username and password (min. 6 characters)
3. Sign in
4. Open **⚙️ Settings** in the sidebar
5. Paste your **Google Gemini API key** (get it free at https://aistudio.google.com)
6. Start learning!

---

## Features Guide

### 💬 Chat Tab
- **Free Chat** — Ask anything, continuous conversation with memory
- **Generate Study Module** — Full structured study notes on any topic
- **Create Learning Roadmap** — 4-week plan with daily goals
- **Adaptive Suggestions** — Personalized tips based on your quiz weak areas
- **Explain Document** — Upload PDF/TXT and ask questions about it
- **Voice Question** — Record and ask verbally

### 📝 Quiz Tab
- Enter a topic, choose number of questions + difficulty
- Answer all questions, then submit
- Instant results with score, explanations, and what you got wrong
- Results are **automatically saved** to the dashboard
- Retake the same quiz or generate a new one on the same topic

### 📊 Dashboard Tab
- Toggle between **This Session** or **All Sessions** analytics
- Charts: Accuracy over time, Score by topic, Performance distribution
- Full quiz history table
- Updates immediately after every quiz submission

---

## Production Database (Optional Upgrade)

If you want to deploy this for multiple users on a server, replace SQLite with PostgreSQL:

```bash
pip install psycopg2-binary sqlalchemy
```

Then replace the `get_db()` function with a PostgreSQL connection using SQLAlchemy.
See: https://docs.sqlalchemy.org/en/20/dialects/postgresql.html

---

## Folder Structure
```
smartlearn_app/
├── app.py              ← Main application file
├── requirements.txt    ← Python dependencies
├── README.md           ← This file
└── smartlearn.db       ← Auto-created on first run (SQLite database)
```
