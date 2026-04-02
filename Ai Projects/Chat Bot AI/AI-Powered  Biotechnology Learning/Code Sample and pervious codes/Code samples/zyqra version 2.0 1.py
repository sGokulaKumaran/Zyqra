# ============================================================
# ZYQRA SMART LEARN AI — Full Rebuild (Bug-Fixed, Claude-Like UI)
# Python 3.x + Streamlit + Google Gemini
#
# SECTIONS:
#   1.  Imports & Page Config
#   2.  Database Setup & Schema
#   3.  Auth Helpers
#   4.  DB Helper Functions
#   5.  Session State Initialisation
#   6.  CSS / Theme Engine
#   7.  System Prompt
#   8.  Utility Helpers
#   9.  Login / Registration Screen
#   10. Post-Login Bootstrap
#   11. Sidebar
#   12. API Gate
#   13. Main Tabs
#       13a. Chat Tab
#       13b. Quiz Tab
#       13c. Flashcards Tab
#       13d. Notes Tab
#       13e. Focus Timer Tab
#       13f. Dashboard Tab
# ============================================================


# ============================================================
# SECTION 1 — IMPORTS & PAGE CONFIG
# ============================================================
import streamlit as st
import google.generativeai as genai
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import re, json, datetime, tempfile, os, hashlib, sqlite3, time
from pathlib import Path

st.set_page_config(
    page_title="Zyqra — Smart Learn AI",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# SECTION 2 — DATABASE SETUP & SCHEMA
# ============================================================
DB_PATH = Path("zyqra.db")


def get_db():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            streak       INTEGER DEFAULT 0,
            last_active  DATE
        );
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            session_key  TEXT NOT NULL,
            session_name TEXT NOT NULL,
            section      TEXT DEFAULT 'chat',
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, session_key)
        );
        CREATE TABLE IF NOT EXISTS messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id   INTEGER NOT NULL,
            role         TEXT NOT NULL,
            content      TEXT NOT NULL,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
        );
        CREATE TABLE IF NOT EXISTS quiz_sessions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            topic        TEXT NOT NULL,
            difficulty   TEXT NOT NULL,
            num_q        INTEGER NOT NULL,
            questions    TEXT NOT NULL,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS quiz_results (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            quiz_id      INTEGER NOT NULL,
            topic        TEXT NOT NULL,
            score        INTEGER NOT NULL,
            total        INTEGER NOT NULL,
            accuracy     REAL NOT NULL,
            weak_topics  TEXT,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (quiz_id) REFERENCES quiz_sessions(id)
        );
        CREATE TABLE IF NOT EXISTS flashcards (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            topic        TEXT NOT NULL,
            front        TEXT NOT NULL,
            back         TEXT NOT NULL,
            source       TEXT DEFAULT 'generated',
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS notes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            title        TEXT NOT NULL,
            content      TEXT NOT NULL,
            color        TEXT DEFAULT '#10a37f',
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """)


init_db()


# ============================================================
# SECTION 3 — AUTH HELPERS
# ============================================================
def hash_pw(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()


def create_user(username: str, password: str):
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, display_name) VALUES (?,?,?)",
                (username.strip().lower(), hash_pw(password), username.strip()),
            )
        return True, "Account created! Please sign in."
    except sqlite3.IntegrityError:
        return False, "Username already taken."


def verify_user(username: str, password: str):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username=? AND password_hash=?",
            (username.strip().lower(), hash_pw(password)),
        ).fetchone()
    if not row:
        return None
    user = dict(row)
    today = datetime.date.today()
    streak = user.get("streak", 0) or 0
    last = user.get("last_active")
    if last:
        try:
            delta = (today - datetime.date.fromisoformat(str(last))).days
            streak = streak + 1 if delta == 1 else (streak if delta == 0 else 1)
        except Exception:
            streak = 1
    else:
        streak = 1
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET streak=?, last_active=? WHERE id=?",
            (streak, today.isoformat(), user["id"]),
        )
    user["streak"] = streak
    return user


def update_display_name(user_id: int, new_name: str):
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET display_name=? WHERE id=?", (new_name.strip(), user_id)
        )


def update_password(user_id: int, new_pw: str):
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET password_hash=? WHERE id=?", (hash_pw(new_pw), user_id)
        )


# ============================================================
# SECTION 4 — DB HELPER FUNCTIONS
# ============================================================

# ── Sessions ──
def db_get_sessions(user_id, section=None):
    with get_db() as conn:
        if section:
            rows = conn.execute(
                "SELECT * FROM chat_sessions WHERE user_id=? AND section=? ORDER BY created_at DESC",
                (user_id, section),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM chat_sessions WHERE user_id=? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def db_create_session(user_id, session_key, session_name, section="chat"):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO chat_sessions (user_id,session_key,session_name,section)"
            " VALUES (?,?,?,?)",
            (user_id, session_key, session_name, section),
        )
        if cur.lastrowid:
            return cur.lastrowid
        row = conn.execute(
            "SELECT id FROM chat_sessions WHERE user_id=? AND session_key=?",
            (user_id, session_key),
        ).fetchone()
        return row["id"]


def db_rename_session(session_id, new_name):
    with get_db() as conn:
        conn.execute(
            "UPDATE chat_sessions SET session_name=? WHERE id=?", (new_name, session_id)
        )


def db_delete_session(session_id):
    with get_db() as conn:
        conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM chat_sessions WHERE id=?", (session_id,))


# ── Messages ──
def db_get_messages(session_id):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id=? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def db_add_message(session_id, role, content):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?,?,?)",
            (session_id, role, content),
        )


# ── Quiz ──
def db_save_quiz_session(user_id, topic, difficulty, num_q, questions_json):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO quiz_sessions (user_id,topic,difficulty,num_q,questions)"
            " VALUES (?,?,?,?,?)",
            (user_id, topic, difficulty, num_q, questions_json),
        )
        return cur.lastrowid


def db_save_quiz_result(user_id, quiz_id, topic, score, total, accuracy, weak_topics):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO quiz_results (user_id,quiz_id,topic,score,total,accuracy,weak_topics)"
            " VALUES (?,?,?,?,?,?,?)",
            (user_id, quiz_id, topic, score, total, accuracy, weak_topics),
        )


def db_get_quiz_results(user_id):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM quiz_results WHERE user_id=? ORDER BY created_at ASC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Flashcards ──
def db_save_flashcards(user_id, topic, cards, source="generated"):
    with get_db() as conn:
        for c in cards:
            conn.execute(
                "INSERT INTO flashcards (user_id,topic,front,back,source) VALUES (?,?,?,?,?)",
                (user_id, topic, c.get("front", ""), c.get("back", ""), source),
            )


def db_get_flashcards(user_id):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM flashcards WHERE user_id=? ORDER BY created_at DESC", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def db_delete_flashcard(card_id):
    with get_db() as conn:
        conn.execute("DELETE FROM flashcards WHERE id=?", (card_id,))


# ── Notes ──
def db_add_note(user_id, title, content, color="#10a37f"):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO notes (user_id,title,content,color) VALUES (?,?,?,?)",
            (user_id, title, content, color),
        )


def db_get_notes(user_id):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM notes WHERE user_id=? ORDER BY created_at DESC", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def db_update_note(note_id, title, content, color):
    with get_db() as conn:
        conn.execute(
            "UPDATE notes SET title=?, content=?, color=? WHERE id=?",
            (title, content, color, note_id),
        )


def db_delete_note(note_id):
    with get_db() as conn:
        conn.execute("DELETE FROM notes WHERE id=?", (note_id,))


# ============================================================
# SECTION 5 — SESSION STATE INITIALISATION
# ============================================================
DEFAULTS = {
    "logged_in": False,
    "user": None,
    # Chat
    "chat_session_id": None,
    "chat_session_name": "New Chat",
    # Quiz
    "quiz_state": None,
    "quiz_submitted": False,
    "quiz_id": None,
    # Flashcards
    "fc_index": 0,
    "fc_flipped": {},
    # Notes
    "editing_note_id": None,
    # Focus Timer
    "timer_end": None,
    "timer_mode": "focus",
    # Settings / UI
    "theme": "light",
    "rename_sid": None,
    "settings_open": False,
    "acct_open": False,
    # API / model params
    "api_key": "",
    "temperature": 0.7,
    "academic_level": "School",
}

for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ============================================================
# SECTION 6 — CSS / THEME ENGINE
# ============================================================
def _theme_vars(theme: str) -> str:
    if theme == "dark":
        return """
        :root {
            --bg:           #0f1117;
            --surface:      #1a1d27;
            --panel:        #1e2130;
            --border:       rgba(255,255,255,0.08);
            --border-h:     rgba(255,255,255,0.16);
            --text:         #ececf1;
            --sub:          #8e8ea0;
            --muted:        #565869;
            --accent:       #10a37f;
            --accent-h:     #1abc95;
            --accent-bg:    rgba(16,163,127,0.12);
            --danger:       #ef4444;
            --warn:         #f59e0b;
            --input-bg:     #1a1d27;
            --shadow:       rgba(0,0,0,0.4);
        }"""
    return """
    :root {
        --bg:           #f7f7f8;
        --surface:      #ffffff;
        --panel:        #ffffff;
        --border:       rgba(0,0,0,0.09);
        --border-h:     rgba(0,0,0,0.18);
        --text:         #1a1a1a;
        --sub:          #555;
        --muted:        #888;
        --accent:       #10a37f;
        --accent-h:     #0d8a6b;
        --accent-bg:    rgba(16,163,127,0.10);
        --danger:       #dc2626;
        --warn:         #d97706;
        --input-bg:     #ffffff;
        --shadow:       rgba(0,0,0,0.07);
    }"""


def inject_css():
    st.markdown(
        f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
{_theme_vars(st.session_state.theme)}

/* ── Reset & Base ── */
*,*::before,*::after{{box-sizing:border-box}}
html,body,[class*="css"]{{
    background:var(--bg)!important;
    color:var(--text)!important;
    font-family:'Plus Jakarta Sans',sans-serif!important;
}}
.stApp{{background:var(--bg)!important}}
#MainMenu,footer,.stDeployButton{{visibility:hidden!important;display:none!important}}
.block-container{{padding:0!important;max-width:100%!important}}

/* ── Global text colour ── */
p,span,li,td,th,div,label,
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] span,
[data-testid="stChatMessage"] p,
[data-testid="stChatMessage"] li,
[data-testid="stChatMessage"] span{{color:var(--text)!important}}

/* ── Sidebar ── */
[data-testid="stSidebar"]{{
    background:var(--surface)!important;
    border-right:1px solid var(--border)!important;
    width:240px!important;min-width:240px!important;
}}
[data-testid="stSidebar"]>div{{padding:0!important}}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] div{{color:var(--text)!important}}

/* BUG FIX: Hide the default Streamlit sidebar toggle arrow that overlaps text */
[data-testid="collapsedControl"]{{
    position:fixed!important;left:0!important;top:50%!important;
    transform:translateY(-50%)!important;z-index:9999!important;
    background:var(--surface)!important;
    border:1px solid var(--border)!important;
    border-left:none!important;
    border-radius:0 6px 6px 0!important;
    width:16px!important;height:40px!important;
    display:flex!important;align-items:center!important;justify-content:center!important;
}}
[data-testid="collapsedControl"] span,
[data-testid="collapsedControl"] p{{display:none!important}}
[data-testid="collapsedControl"] svg{{width:10px!important;height:10px!important;fill:var(--sub)!important}}

/* ── Buttons ── */
div.stButton>button{{
    background:transparent!important;
    border:1px solid var(--border)!important;
    color:var(--sub)!important;
    font-family:'Plus Jakarta Sans',sans-serif!important;
    font-size:0.82rem!important;
    border-radius:7px!important;
    padding:0.4rem 0.75rem!important;
    transition:all 0.18s!important;
    width:100%!important;
}}
div.stButton>button:hover{{
    background:var(--accent-bg)!important;
    border-color:var(--accent)!important;
    color:var(--accent)!important;
}}
div.stButton>button:disabled{{
    opacity:.45!important;cursor:not-allowed!important;
}}

/* ── Inputs ── */
[data-baseweb="input"] input,
[data-baseweb="textarea"] textarea{{
    background:var(--input-bg)!important;
    border:1px solid var(--border)!important;
    color:var(--text)!important;
    font-family:'Plus Jakarta Sans',sans-serif!important;
    font-size:0.9rem!important;border-radius:8px!important;
}}
[data-baseweb="input"] input::placeholder,
[data-baseweb="textarea"] textarea::placeholder{{color:var(--muted)!important}}
[data-baseweb="input"] input:focus,
[data-baseweb="textarea"] textarea:focus{{
    border-color:var(--accent)!important;
    box-shadow:0 0 0 2px rgba(16,163,127,.15)!important;
}}

/* ── Select ── */
[data-baseweb="select"]>div{{
    background:var(--input-bg)!important;
    border:1px solid var(--border)!important;
    color:var(--text)!important;border-radius:8px!important;
}}
[data-baseweb="select"] [data-baseweb="value"],
[data-baseweb="select"] [data-baseweb="single-value"]{{color:var(--text)!important}}
[data-baseweb="popover"] [data-baseweb="menu"]{{
    background:var(--surface)!important;border:1px solid var(--border)!important;
}}
[data-baseweb="menu"] [role="option"]{{
    color:var(--text)!important;background:var(--surface)!important;
    font-family:'Plus Jakarta Sans',sans-serif!important;
}}
[data-baseweb="menu"] [role="option"]:hover{{
    background:var(--accent-bg)!important;color:var(--accent)!important;
}}

/* ── Labels ── */
label,.stTextInput label,.stTextArea label,.stSelectbox label,
.stRadio label,.stSlider label,.stFileUploader label{{
    font-size:0.73rem!important;font-weight:600!important;
    text-transform:uppercase!important;letter-spacing:.05em!important;
    color:var(--sub)!important;font-family:'Plus Jakarta Sans',sans-serif!important;
}}

/* ── Radio ── */
[data-testid="stRadio"] label,
[data-testid="stRadio"]>div>label>div>p{{
    font-size:0.88rem!important;color:var(--text)!important;
}}

/* ── Expander (Settings inside sidebar) ── */
[data-testid="stExpander"]{{
    background:transparent!important;
    border:none!important;
    border-top:1px solid var(--border)!important;
    border-radius:0!important;
}}
[data-testid="stExpander"] summary{{
    padding:0.7rem 1rem!important;
    display:flex!important;align-items:center!important;
    white-space:nowrap!important;overflow:hidden!important;
    font-size:0.85rem!important;color:var(--sub)!important;
}}
[data-testid="stExpander"] summary span,
[data-testid="stExpander"] summary p{{
    color:var(--text)!important;
    font-family:'Plus Jakarta Sans',sans-serif!important;
    font-size:0.85rem!important;
}}

/* ── BUG FIX: Sticky chat input via stBottom ── */
[data-testid="stBottom"]{{
    position:fixed!important;bottom:0!important;right:0!important;
    left:241px!important;z-index:9000!important;
    background:var(--bg)!important;
    border-top:1px solid var(--border)!important;
    padding:0.5rem 1.5rem 0.8rem!important;
    box-shadow:0 -4px 20px var(--shadow)!important;
}}
[data-testid="stSidebar"][aria-expanded="false"]~[data-testid="stMain"]
    [data-testid="stBottom"]{{left:0!important}}
section[data-testid="stMain"] .block-container{{padding-bottom:120px!important}}

/* ── Chat Input Widget ── */
[data-testid="stChatInput"]{{
    background:var(--input-bg)!important;
    border:1px solid var(--border)!important;
    border-radius:12px!important;
}}
[data-testid="stChatInput"] textarea{{color:var(--text)!important;background:var(--input-bg)!important}}
[data-testid="stChatInput"] textarea::placeholder{{color:var(--muted)!important}}
[data-testid="stChatInput"]:focus-within{{
    border-color:var(--accent)!important;
    box-shadow:0 0 0 2px rgba(16,163,127,.12)!important;
}}
/* File upload & voice inside bottom bar — left and right of textarea */
[data-testid="stBottom"] [data-testid="stFileUploaderDropzone"]{{display:none!important}}
[data-testid="stBottom"] .file-icon-btn,
[data-testid="stBottom"] .voice-icon-btn{{
    background:transparent!important;border:none!important;
    color:var(--muted)!important;cursor:pointer!important;
    font-size:1.1rem!important;padding:0.3rem!important;
}}

/* ── Chat Messages ── */
[data-testid="stChatMessage"]{{background:transparent!important;border:none!important;padding:0!important}}

/* ── Tabs ── */
[data-testid="stTabs"] [data-baseweb="tab-list"]{{
    background:transparent!important;
    border-bottom:1px solid var(--border)!important;
    gap:0!important;padding:0 1.5rem!important;
}}
[data-testid="stTabs"] [data-baseweb="tab"]{{
    background:transparent!important;color:var(--muted)!important;
    font-family:'Plus Jakarta Sans',sans-serif!important;font-size:0.84rem!important;
    font-weight:500!important;border:none!important;
    border-bottom:2px solid transparent!important;
    padding:0.8rem 1rem!important;transition:all .2s!important;
}}
[data-testid="stTabs"] [aria-selected="true"]{{
    color:var(--accent)!important;border-bottom:2px solid var(--accent)!important;
}}
[data-testid="stTabs"] [data-baseweb="tab-highlight"]{{display:none!important}}
[data-testid="stTabs"]>div:first-child{{
    position:sticky!important;top:0!important;z-index:200!important;
    background:var(--bg)!important;
}}

/* ── Container borders ── */
[data-testid="stVerticalBlockBorderWrapper"]{{
    background:var(--panel)!important;
    border:1px solid var(--border)!important;
    border-radius:10px!important;
    box-shadow:0 1px 6px var(--shadow)!important;
}}

/* ── Alerts ── */
[data-testid="stAlert"]{{
    background:var(--panel)!important;border:1px solid var(--border)!important;
    border-radius:8px!important;color:var(--text)!important;font-size:0.85rem!important;
}}
[data-testid="stAlert"] p{{color:var(--text)!important}}

/* ── DataFrame ── */
[data-testid="stDataFrame"]{{background:var(--panel)!important}}
[data-testid="stDataFrame"] th,
[data-testid="stDataFrame"] td{{color:var(--text)!important;background:var(--panel)!important}}

/* ── File uploader ── */
[data-testid="stFileUploader"]{{
    background:var(--panel)!important;
    border:1px dashed var(--border)!important;border-radius:8px!important;
}}
[data-testid="stFileUploader"] span,
[data-testid="stFileUploader"] p{{color:var(--sub)!important}}

/* ── Audio input ── */
[data-testid="stAudioInput"]{{
    background:var(--panel)!important;border:1px solid var(--border)!important;border-radius:8px!important;
}}

/* ── Captions ── */
.stCaption,[data-testid="stCaptionContainer"] p{{color:var(--muted)!important}}

/* ── Slider ── */
[data-baseweb="slider"] [data-testid="stThumb"]{{background:var(--accent)!important;border:none!important}}
[data-baseweb="slider"] [data-testid="stTrackHighlight"]{{background:var(--accent)!important}}

/* ── Spinner ── */
.stSpinner>div>div{{border-top-color:var(--accent)!important}}

hr{{border:none!important;border-top:1px solid var(--border)!important;margin:.8rem 0!important}}

/* ── Scrollbar ── */
::-webkit-scrollbar{{width:4px;height:4px}}
::-webkit-scrollbar-track{{background:transparent}}
::-webkit-scrollbar-thumb{{background:var(--border);border-radius:2px}}
::-webkit-scrollbar-thumb:hover{{background:var(--accent)}}

/* ── Mode bar (sticky top in Chat) ── */
.mode-bar{{
    position:sticky!important;top:0!important;z-index:400!important;
    background:var(--bg)!important;border-bottom:1px solid var(--border)!important;
    padding:0.6rem 1.5rem!important;
}}

/* ── Component classes ── */
.metric-card{{
    background:var(--panel);border:1px solid var(--border);
    border-radius:10px;padding:1.1rem;text-align:center;
}}
.metric-val{{font-size:1.8rem;font-weight:700;color:var(--accent);font-family:'Plus Jakarta Sans',sans-serif}}
.metric-lbl{{font-size:0.7rem;color:var(--sub);text-transform:uppercase;letter-spacing:.05em;margin-top:.25rem}}

.score-banner{{
    background:var(--accent-bg);border:1px solid var(--accent);
    border-radius:12px;padding:1.8rem;text-align:center;margin:1rem 0;
}}
.score-num{{font-size:2.8rem;font-weight:700;color:var(--accent);font-family:'Plus Jakarta Sans',sans-serif}}

.progress-bar{{height:4px;background:var(--border);border-radius:2px;margin-bottom:1rem;overflow:hidden}}
.progress-fill{{height:100%;background:var(--accent);border-radius:2px;transition:width .4s ease}}

.flashcard{{
    background:var(--panel);border:1px solid var(--border);border-radius:16px;
    padding:2rem;min-height:200px;display:flex;align-items:center;
    justify-content:center;text-align:center;
    box-shadow:0 4px 20px var(--shadow);transition:all .25s ease;
}}
.flashcard:hover{{transform:translateY(-3px);border-color:var(--accent)}}
.flashcard-text{{font-size:1.05rem;font-weight:600;color:var(--text);line-height:1.6}}

.streak-badge{{
    background:linear-gradient(135deg,#f59e0b,#ef4444);border-radius:20px;
    padding:.25rem .7rem;font-size:.75rem;font-weight:700;color:white;
    display:inline-flex;align-items:center;gap:.25rem;
}}
.search-redirect{{
    background:var(--accent-bg);border:1px solid var(--accent);
    border-radius:10px;padding:1rem 1.4rem;margin:.5rem 0;
}}
.search-redirect a{{color:var(--accent)!important;text-decoration:none;font-weight:500;font-size:.8rem}}

.pomo-display{{
    font-size:3.5rem;font-weight:700;color:var(--accent);
    font-family:'JetBrains Mono',monospace;text-align:center;letter-spacing:.05em;
}}
.pomo-label{{font-size:.72rem;text-transform:uppercase;letter-spacing:.1em;color:var(--sub);text-align:center;margin-top:.3rem}}

.note-card{{
    border-left:4px solid;border-radius:0 8px 8px 0;
    padding:.9rem 1rem;margin-bottom:.6rem;background:var(--panel);
    border-right:1px solid var(--border);border-top:1px solid var(--border);border-bottom:1px solid var(--border);
}}
</style>
""",
        unsafe_allow_html=True,
    )


inject_css()


# ============================================================
# SECTION 7 — SYSTEM PROMPT
# ============================================================
SYSTEM_PROMPT = """You are Zyqra — an adaptive, encouraging AI learning assistant for ALL subjects.

Core guidelines:
- Adapt explanations to the student's academic level (School / Undergraduate / Postgraduate).
- Use clear Markdown: headings (##), bullet points, bold key terms, code blocks when needed.
- Be patient, thorough, and encouraging. Build on prior context in the conversation.
- Never refuse academic questions. Handle science, humanities, math, coding, arts equally.

VISUAL REQUEST RULE:
If the user asks for a diagram, chart, flowchart, graph, or any visual:
- Do NOT produce ASCII art or long text diagrams.
- Output ONLY this line:  SEARCH_QUERY: <4-8 word descriptive image search query>

For all other queries, provide structured, helpful explanations."""


# ============================================================
# SECTION 8 — UTILITY HELPERS
# ============================================================
def render_ai_response(text: str):
    """Render AI response — handles visual search redirects cleanly."""
    sq = re.search(r"SEARCH_QUERY:\s*(.+)", text)
    if sq:
        q = sq.group(1).strip()
        enc = q.replace(" ", "+")
        st.markdown(
            f"""<div class="search-redirect">
            <div style="font-size:.7rem;font-weight:600;text-transform:uppercase;
                        letter-spacing:.05em;color:var(--accent);margin-bottom:.4rem;">
                🔍 Visual Search
            </div>
            <div style="font-size:.92rem;font-weight:600;color:var(--text);margin-bottom:.5rem;">
                "{q}"
            </div>
            <a href="https://www.google.com/search?tbm=isch&q={enc}" target="_blank">Google Images ↗</a>
            &nbsp;&nbsp;
            <a href="https://www.youtube.com/results?search_query={enc}" target="_blank">YouTube ↗</a>
            </div>""",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(text)


def new_session_key():
    return f"s_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"


def style_chart(fig, ax):
    """Apply consistent, theme-aware style to matplotlib axes."""
    dark = st.session_state.theme == "dark"
    bg = "#1e2130" if dark else "#ffffff"
    tc = "#8e8ea0" if dark else "#555555"
    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)
    ax.tick_params(colors=tc, labelsize=8)
    for side in ["bottom", "left"]:
        ax.spines[side].set_color((1, 1, 1, 0.08) if dark else (0, 0, 0, 0.08))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.xaxis.label.set_color(tc)
    ax.yaxis.label.set_color(tc)
    fig.tight_layout()


# ============================================================
# SECTION 9 — LOGIN / REGISTRATION SCREEN
# ============================================================
if not st.session_state.logged_in:
    _, col, _ = st.columns([1, 1.1, 1])
    with col:
        st.markdown(
            """<div style="text-align:center;padding:2.5rem 0 1.5rem">
            <div style="font-size:2.6rem">🧠</div>
            <div style="font-size:1.9rem;font-weight:700;color:var(--accent);margin-top:.4rem">Zyqra</div>
            <div style="font-size:.85rem;color:var(--sub);margin-top:.2rem">
                Adaptive AI learning, powered by Gemini
            </div>
            </div>""",
            unsafe_allow_html=True,
        )
        tab_in, tab_up = st.tabs(["  Sign In  ", "  Create Account  "])

        with tab_in:
            with st.container(border=True):
                uname = st.text_input("Username", key="li_u", placeholder="Your username")
                pw = st.text_input("Password", type="password", key="li_p", placeholder="Password")
                st.markdown("<div style='height:.3rem'></div>", unsafe_allow_html=True)
                if st.button("Sign In →", key="li_btn", use_container_width=True):
                    if uname and pw:
                        user = verify_user(uname, pw)
                        if user:
                            st.session_state.logged_in = True
                            st.session_state.user = user
                            st.rerun()
                        else:
                            st.error("Incorrect username or password.")
                    else:
                        st.warning("Please fill in both fields.")

        with tab_up:
            with st.container(border=True):
                nu = st.text_input("Username", key="su_u", placeholder="Choose a username")
                np1 = st.text_input("Password", type="password", key="su_p1", placeholder="Min. 6 characters")
                np2 = st.text_input("Confirm password", type="password", key="su_p2", placeholder="Repeat password")
                st.markdown("<div style='height:.3rem'></div>", unsafe_allow_html=True)
                if st.button("Create Account →", key="su_btn", use_container_width=True):
                    if not (nu and np1 and np2):
                        st.warning("Fill in all fields.")
                    elif len(np1) < 6:
                        st.warning("Password must be at least 6 characters.")
                    elif np1 != np2:
                        st.error("Passwords do not match.")
                    else:
                        ok, msg = create_user(nu, np1)
                        if ok:
                            st.success(f"✅ {msg}")
                        else:
                            st.error(msg)
    st.stop()


# ============================================================
# SECTION 10 — POST-LOGIN BOOTSTRAP
# ============================================================
user = st.session_state.user
user_id = user["id"]

# Refresh user record from DB on each run
with get_db() as conn:
    fresh = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if fresh:
        user = dict(fresh)
        st.session_state.user = user

# Ensure at least one chat session exists
chat_sessions = db_get_sessions(user_id, section="chat")
if not chat_sessions:
    sid = db_create_session(user_id, new_session_key(), "New Chat", "chat")
    chat_sessions = db_get_sessions(user_id, section="chat")

# Validate active chat session
valid_chat_ids = [s["id"] for s in chat_sessions]
if st.session_state.chat_session_id not in valid_chat_ids:
    st.session_state.chat_session_id = chat_sessions[0]["id"]
    st.session_state.chat_session_name = chat_sessions[0]["session_name"]

current_chat_sid = st.session_state.chat_session_id
streak = user.get("streak", 0) or 0
display_name = user.get("display_name") or user.get("username", "User")


# ============================================================
# SECTION 11 — SIDEBAR
# ============================================================
with st.sidebar:
    # ── Header: App name + toggle ──
    st.markdown(
        f"""<div style="padding:1rem 1rem .6rem;border-bottom:1px solid var(--border)">
        <div style="display:flex;align-items:center;justify-content:space-between">
            <div style="display:flex;align-items:center;gap:.6rem">
                <div style="font-size:1.4rem">🧠</div>
                <div>
                    <div style="font-size:1rem;font-weight:700;color:var(--text)">Zyqra</div>
                    <div style="font-size:.68rem;color:var(--muted)">Smart Learn AI</div>
                </div>
            </div>
        </div>
        <div style="margin-top:.7rem;display:flex;align-items:center;justify-content:space-between">
            <div style="background:var(--accent-bg);border-radius:6px;padding:.3rem .7rem;
                        font-size:.76rem;color:var(--accent);font-weight:600">
                👤 {display_name}
            </div>
            <div class="streak-badge">🔥 {streak}d</div>
        </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # ── New Chat button ──
    if st.button("＋  New Chat", key="sb_new_chat", use_container_width=True):
        sid = db_create_session(user_id, new_session_key(), "New Chat", "chat")
        st.session_state.chat_session_id = sid
        st.session_state.chat_session_name = "New Chat"
        st.session_state.quiz_state = None
        st.session_state.quiz_submitted = False
        st.rerun()

    # ── Chat history ──
    st.markdown(
        "<div style='font-size:.68rem;font-weight:600;text-transform:uppercase;"
        "letter-spacing:.06em;color:var(--muted);padding:.6rem 0 .2rem .3rem'>Chat History</div>",
        unsafe_allow_html=True,
    )

    for sess in chat_sessions:
        s_id = sess["id"]
        s_name = sess["session_name"]
        is_active = s_id == st.session_state.chat_session_id

        if st.session_state.rename_sid == s_id:
            new_n = st.text_input("", value=s_name, key=f"ren_inp_{s_id}", label_visibility="collapsed")
            rc1, rc2 = st.columns(2)
            with rc1:
                if st.button("Save", key=f"ren_save_{s_id}", use_container_width=True):
                    new_n = new_n.strip() or s_name
                    db_rename_session(s_id, new_n)
                    if s_id == st.session_state.chat_session_id:
                        st.session_state.chat_session_name = new_n
                    st.session_state.rename_sid = None
                    st.rerun()
            with rc2:
                if st.button("Cancel", key=f"ren_cancel_{s_id}", use_container_width=True):
                    st.session_state.rename_sid = None
                    st.rerun()
        else:
            active_bg = "background:var(--accent-bg);border-radius:6px;" if is_active else ""
            name_col = "var(--accent)" if is_active else "var(--text)"
            msg_count = len(db_get_messages(s_id))
            st.markdown(
                f"""<div style="{active_bg}padding:.4rem .5rem;margin-bottom:1px">
                <div style="font-size:.82rem;color:{name_col};font-weight:{'600' if is_active else '400'};
                            white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
                    {'💬 ' if is_active else ''}{s_name}
                </div>
                <div style="font-size:.66rem;color:var(--muted)">{msg_count} messages</div>
                </div>""",
                unsafe_allow_html=True,
            )
            co, cr, cd = st.columns([3, 1, 1])
            with co:
                if st.button("● Active" if is_active else "Open", key=f"open_s_{s_id}",
                             use_container_width=True, disabled=is_active):
                    st.session_state.chat_session_id = s_id
                    st.session_state.chat_session_name = s_name
                    st.session_state.quiz_state = None
                    st.session_state.quiz_submitted = False
                    st.rerun()
            with cr:
                if st.button("✎", key=f"ren_s_{s_id}", use_container_width=True):
                    st.session_state.rename_sid = s_id
                    st.rerun()
            with cd:
                if len(chat_sessions) > 1:
                    if st.button("✕", key=f"del_s_{s_id}", use_container_width=True):
                        db_delete_session(s_id)
                        remaining = [s for s in chat_sessions if s["id"] != s_id]
                        if remaining:
                            st.session_state.chat_session_id = remaining[0]["id"]
                            st.session_state.chat_session_name = remaining[0]["session_name"]
                        st.session_state.quiz_state = None
                        st.rerun()

    st.markdown("<hr>", unsafe_allow_html=True)

    # ── Settings expander ──
    with st.expander("⚙️  Settings", expanded=False):
        api_in = st.text_input(
            "Gemini API Key", type="password",
            placeholder="AIza…", key="api_key_input",
            value=st.session_state.api_key,
        )
        if api_in != st.session_state.api_key:
            st.session_state.api_key = api_in

        temp = st.slider("Temperature", 0.0, 1.0, st.session_state.temperature,
                         step=0.05, key="temp_slider")
        st.session_state.temperature = temp

        lvl = st.selectbox("Academic Level",
                           ["School", "Undergraduate", "Postgraduate"],
                           index=["School", "Undergraduate", "Postgraduate"].index(
                               st.session_state.academic_level),
                           key="lvl_select")
        st.session_state.academic_level = lvl

        th_label = "Switch to Light Mode" if st.session_state.theme == "dark" else "Switch to Dark Mode"
        if st.button(th_label, key="theme_btn", use_container_width=True):
            st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"
            st.rerun()

        st.markdown("<div style='font-size:.75rem;font-weight:600;color:var(--sub);"
                    "text-transform:uppercase;letter-spacing:.04em;margin:.6rem 0 .3rem'>"
                    "Account Settings</div>", unsafe_allow_html=True)
        new_dn = st.text_input("New display name", placeholder=display_name, key="new_dn_inp")
        new_pw_a = st.text_input("New password", type="password", placeholder="Leave blank to keep", key="new_pw_a")
        new_pw_b = st.text_input("Confirm new password", type="password", placeholder="Repeat", key="new_pw_b")
        if st.button("Save Account Changes", key="save_acct_btn", use_container_width=True):
            changed = False
            if new_dn.strip():
                update_display_name(user_id, new_dn.strip())
                changed = True
            if new_pw_a:
                if new_pw_a != new_pw_b:
                    st.error("Passwords don't match.")
                elif len(new_pw_a) < 6:
                    st.error("Password must be at least 6 chars.")
                else:
                    update_password(user_id, new_pw_a)
                    changed = True
            if changed:
                st.success("Saved!")
                st.rerun()

    # ── Sign out ──
    if st.button("← Sign Out", key="signout_btn", use_container_width=True):
        for k in list(DEFAULTS.keys()):
            st.session_state.pop(k, None)
        st.rerun()


# ============================================================
# SECTION 12 — API GATE
# ============================================================
api_key = st.session_state.api_key
if not api_key:
    st.markdown(
        """<div style="display:flex;flex-direction:column;align-items:center;
                    justify-content:center;min-height:72vh;text-align:center;gap:1rem;padding:2rem">
        <div style="font-size:3rem">🧠</div>
        <div style="font-size:1.5rem;font-weight:700;color:var(--accent)">Almost there!</div>
        <div style="font-size:.9rem;color:var(--sub);max-width:360px;line-height:1.7">
            Open <strong style="color:var(--text)">⚙️ Settings</strong> in the sidebar
            and enter your <strong style="color:var(--text)">Google Gemini API key</strong>
            to start learning.
        </div>
        <div style="background:var(--accent-bg);border:1px solid var(--accent);
                    border-radius:8px;padding:.7rem 1.4rem;font-size:.8rem;color:var(--accent)">
            ↖ Expand ⚙️ Settings in the sidebar
        </div>
        <div style="font-size:.75rem;color:var(--muted);margin-top:.5rem">
            Your previous chat history is visible and safe — no API needed to read it.
        </div>
        </div>""",
        unsafe_allow_html=True,
    )
    st.stop()

genai.configure(api_key=api_key)
try:
    ai_model = genai.GenerativeModel(
        "gemini-2.0-flash",
        generation_config={"temperature": st.session_state.temperature},
    )
except Exception:
    ai_model = genai.GenerativeModel(
        "gemini-1.5-flash",
        generation_config={"temperature": st.session_state.temperature},
    )

level = st.session_state.academic_level


# ============================================================
# STICKY PAGE HEADER (shown above tabs)
# ============================================================
st.markdown(
    f"""<div style="position:sticky;top:0;z-index:300;
                background:var(--bg);border-bottom:1px solid var(--border);
                padding:.9rem 1.8rem .7rem;
                display:flex;align-items:center;justify-content:space-between">
    <div style="display:flex;align-items:center;gap:.7rem">
        <div style="font-size:1.3rem">🧠</div>
        <div>
            <div style="font-size:1rem;font-weight:700;color:var(--text)">
                {st.session_state.chat_session_name}
            </div>
            <div style="font-size:.7rem;color:var(--muted)">
                {level} · {'🌙 Dark' if st.session_state.theme == 'dark' else '☀️ Light'}
            </div>
        </div>
    </div>
    <div style="font-size:.78rem;color:var(--sub)">👤 {display_name}</div>
    </div>""",
    unsafe_allow_html=True,
)


# ============================================================
# SECTION 13 — MAIN TABS
# ============================================================
(
    tab_chat,
    tab_quiz,
    tab_fc,
    tab_notes,
    tab_timer,
    tab_dash,
) = st.tabs([
    "  💬 Chat  ",
    "  📝 Quiz  ",
    "  🃏 Flashcards  ",
    "  📒 Notes  ",
    "  ⏱️ Focus  ",
    "  📊 Dashboard  ",
])


# ============================================================
# SECTION 13a — CHAT TAB
# ============================================================
with tab_chat:
    # ── Mode selector (sticky) ──
    st.markdown("<div class='mode-bar'>", unsafe_allow_html=True)
    chat_mode = st.selectbox(
        "Chat mode",
        [
            "💬 Free Chat",
            "📚 Study Module",
            "🗺️ Learning Roadmap",
            "💡 Adaptive Suggestions",
            "📄 Explain Document",
            "🎙️ Voice Question",
        ],
        key="chat_mode_sel",
        label_visibility="collapsed",
    )
    st.markdown("</div>", unsafe_allow_html=True)

    # ── Message history ──
    messages = db_get_messages(current_chat_sid)
    if messages:
        for m in messages:
            with st.chat_message(m["role"]):
                if m["role"] == "assistant":
                    render_ai_response(m["content"])
                else:
                    st.markdown(m["content"])
    else:
        st.markdown(
            f"""<div style="text-align:center;padding:4rem 1rem">
            <div style="font-size:2.2rem;margin-bottom:.8rem">👋</div>
            <div style="font-size:1rem;font-weight:600;color:var(--sub)">
                Hello, {display_name}!
            </div>
            <div style="font-size:.82rem;color:var(--muted);margin-top:.4rem;max-width:380px;margin-inline:auto">
                Ask me anything across Science, Maths, History, Literature, Coding and more.
                Select a mode above to get started.
            </div>
            </div>""",
            unsafe_allow_html=True,
        )

    # ── Input area ──
    if chat_mode == "💬 Free Chat":
        # File upload + voice in columns above the sticky chat_input
        up_col, _, voice_col = st.columns([1, 4, 1])
        with up_col:
            uploaded_file = st.file_uploader(
                "📎", type=["pdf", "txt", "csv", "png", "jpg", "jpeg"],
                key="chat_file_upload", label_visibility="collapsed",
            )
        with voice_col:
            audio_rec = st.audio_input("🎙️", key="chat_audio_quick", label_visibility="collapsed")

        user_input = st.chat_input("Ask anything…", key="free_chat_input")

        if user_input or uploaded_file or audio_rec:
            prompt_text = user_input or ""
            display_text = prompt_text

            if uploaded_file:
                display_text = f"📎 **{uploaded_file.name}**" + (f" — {prompt_text}" if prompt_text else "")
            if audio_rec and not uploaded_file:
                display_text = "🎙️ Voice question" + (f" — {prompt_text}" if prompt_text else "")

            db_add_message(current_chat_sid, "user", display_text)

            with st.spinner("Thinking…"):
                try:
                    history = db_get_messages(current_chat_sid)[-12:]
                    history_text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in history[:-1])
                    base_prompt = f"{SYSTEM_PROMPT}\nAcademic Level: {level}\n"

                    if uploaded_file:
                        ext = uploaded_file.name.rsplit(".", 1)[-1].lower()
                        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
                            tmp.write(uploaded_file.getvalue())
                            tmp_path = tmp.name
                        gf = genai.upload_file(tmp_path)
                        parts = [gf, f"{base_prompt}User: {prompt_text or 'Please explain this file.'}"]
                        resp = ai_model.generate_content(parts)
                        genai.delete_file(gf.name)
                        os.remove(tmp_path)
                    elif audio_rec:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                            tmp.write(audio_rec.getvalue())
                            tmp_path = tmp.name
                        gf = genai.upload_file(tmp_path)
                        resp = ai_model.generate_content(
                            [gf, f"{base_prompt}Listen and answer the student's question clearly."]
                        )
                        genai.delete_file(gf.name)
                        os.remove(tmp_path)
                    else:
                        full_prompt = (
                            f"{base_prompt}"
                            f"Conversation so far:\n{history_text}\n\n"
                            f"User: {prompt_text}"
                        )
                        resp = ai_model.generate_content(full_prompt)

                    db_add_message(current_chat_sid, "assistant", resp.text)
                except Exception as e:
                    db_add_message(current_chat_sid, "assistant", f"❌ Error: {e}")
            st.rerun()

    elif chat_mode in ["📄 Explain Document", "🎙️ Voice Question"]:
        with st.container(border=True):
            st.markdown(
                f"<div style='font-size:.78rem;font-weight:600;color:var(--sub);margin-bottom:.5rem'>"
                f"{chat_mode}</div>",
                unsafe_allow_html=True,
            )
            if chat_mode == "📄 Explain Document":
                doc_file = st.file_uploader(
                    "Upload PDF / TXT / CSV", type=["pdf", "txt", "csv"], key="doc_upload"
                )
                doc_q = st.text_input("Your question about this file", placeholder="Summarise the key points…", key="doc_q")
                if st.button("Analyse →", key="doc_go", use_container_width=True):
                    if not doc_file:
                        st.warning("Please upload a file.")
                    elif not doc_q:
                        st.warning("Enter your question.")
                    else:
                        db_add_message(current_chat_sid, "user", f"📄 **{doc_file.name}** — {doc_q}")
                        with st.spinner("Analysing…"):
                            try:
                                ext = doc_file.name.rsplit(".", 1)[-1]
                                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
                                    tmp.write(doc_file.getvalue())
                                    tmp_path = tmp.name
                                gf = genai.upload_file(tmp_path)
                                resp = ai_model.generate_content(
                                    [gf, f"{SYSTEM_PROMPT}\nLevel:{level}\n{doc_q}"]
                                )
                                genai.delete_file(gf.name)
                                os.remove(tmp_path)
                                db_add_message(current_chat_sid, "assistant", resp.text)
                            except Exception as e:
                                db_add_message(current_chat_sid, "assistant", f"❌ Error: {e}")
                        st.rerun()
            else:
                audio = st.audio_input("Record your question", key="voice_input")
                if st.button("Send Voice →", key="voice_go", use_container_width=True):
                    if not audio:
                        st.warning("Record audio first.")
                    else:
                        db_add_message(current_chat_sid, "user", "🎙️ Voice question")
                        with st.spinner("Processing audio…"):
                            try:
                                with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                                    tmp.write(audio.getvalue())
                                    tmp_path = tmp.name
                                gf = genai.upload_file(tmp_path)
                                resp = ai_model.generate_content(
                                    [gf, f"{SYSTEM_PROMPT}\nAnswer the student's spoken question clearly."]
                                )
                                genai.delete_file(gf.name)
                                os.remove(tmp_path)
                                db_add_message(current_chat_sid, "assistant", resp.text)
                            except Exception as e:
                                db_add_message(current_chat_sid, "assistant", f"❌ Error: {e}")
                        st.rerun()

    else:
        # Study Module / Roadmap / Adaptive
        with st.container(border=True):
            st.markdown(
                f"<div style='font-size:.78rem;font-weight:600;color:var(--sub);margin-bottom:.5rem'>"
                f"{chat_mode}</div>",
                unsafe_allow_html=True,
            )
            topic = st.text_input(
                "Topic", placeholder="e.g. Photosynthesis, Linear Algebra, French Revolution…",
                key="gen_topic_inp",
            )
            if st.button("Generate →", key="gen_mode_go", use_container_width=True):
                if not topic.strip():
                    st.warning("Please enter a topic.")
                else:
                    db_add_message(current_chat_sid, "user", f"{chat_mode}: **{topic}**")
                    with st.spinner("Generating…"):
                        try:
                            if "Study Module" in chat_mode:
                                p = (
                                    f"{SYSTEM_PROMPT}\nLevel: {level}\nTopic: {topic}\n"
                                    "Create a comprehensive study module: overview, key concepts, "
                                    "examples, practice questions, and a quick summary."
                                )
                            elif "Roadmap" in chat_mode:
                                p = (
                                    f"{SYSTEM_PROMPT}\nLevel: {level}\nTopic: {topic}\n"
                                    "Create a 4-week learning roadmap with weekly goals, "
                                    "daily tasks, recommended resources, and milestones."
                                )
                            else:  # Adaptive
                                results = db_get_quiz_results(user_id)
                                weak = (
                                    ", ".join([r["weak_topics"] for r in results if r.get("weak_topics")])
                                    or "general topics"
                                )
                                p = (
                                    f"{SYSTEM_PROMPT}\nLevel: {level}\nTopic: {topic}\n"
                                    f"Student weak areas: {weak}\n"
                                    "Suggest targeted exercises and strategies to improve weak areas."
                                )
                            resp = ai_model.generate_content(p)
                            db_add_message(current_chat_sid, "assistant", resp.text)
                        except Exception as e:
                            db_add_message(current_chat_sid, "assistant", f"❌ Error: {e}")
                    st.rerun()


# ============================================================
# SECTION 13b — QUIZ TAB
# ============================================================
with tab_quiz:
    st.markdown("<div style='padding:1.2rem 1.5rem 0'>", unsafe_allow_html=True)

    if not st.session_state.quiz_state:
        # ── Quiz generator ──
        with st.container(border=True):
            st.markdown(
                "<div style='font-size:.95rem;font-weight:700;color:var(--text);"
                "margin-bottom:.7rem'>📝 Generate a Quiz</div>",
                unsafe_allow_html=True,
            )
            qc1, qc2, qc3 = st.columns([3, 1, 1])
            with qc1:
                quiz_topic = st.text_input("Topic", placeholder="e.g. Newton's Laws, Python, WW2…", key="q_topic")
            with qc2:
                num_q = st.selectbox("Questions", [3, 5, 7, 10], index=1, key="q_num")
            with qc3:
                difficulty = st.selectbox("Difficulty", ["Easy", "Medium", "Hard"], index=1, key="q_diff")

            if st.button("Generate Quiz →", key="gen_quiz_btn", use_container_width=True):
                if not quiz_topic.strip():
                    st.warning("Enter a topic first.")
                else:
                    with st.spinner("Building quiz…"):
                        try:
                            p = (
                                f"{SYSTEM_PROMPT}\nLevel: {level}, Difficulty: {difficulty}\n"
                                f"Topic: {quiz_topic}\n"
                                f"Generate exactly {num_q} multiple-choice questions.\n"
                                "Return ONLY a valid JSON array with no markdown fences:\n"
                                '[{"question":"...","options":["A","B","C","D"],"answer":"exact correct option","explanation":"brief reason"}]'
                            )
                            resp = ai_model.generate_content(p)
                            clean = re.sub(r"```(?:json)?|```", "", resp.text).strip()
                            quiz_data = json.loads(clean)
                            qid = db_save_quiz_session(
                                user_id, quiz_topic, difficulty, num_q, json.dumps(quiz_data)
                            )
                            st.session_state.quiz_state = {
                                "questions": quiz_data,
                                "answers": {},
                                "topic": quiz_topic,
                                "difficulty": difficulty,
                                "num_q": num_q,
                            }
                            st.session_state.quiz_id = qid
                            st.session_state.quiz_submitted = False
                        except Exception as e:
                            st.error(f"Failed to generate quiz: {e}")
                    st.rerun()

    elif not st.session_state.quiz_submitted:
        # ── Quiz in progress ──
        qs = st.session_state.quiz_state
        questions = qs["questions"]
        total = len(questions)
        answered = len(qs["answers"])
        pct = int(answered / total * 100)

        st.markdown(
            f"""<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.8rem">
            <div>
                <div style="font-size:1rem;font-weight:700;color:var(--text)">📝 {qs['topic']}</div>
                <div style="font-size:.73rem;color:var(--sub)">{qs['difficulty']} · {level} · {total} questions</div>
            </div>
            <div style="font-size:.8rem;color:var(--accent);font-weight:600">{answered}/{total} answered</div>
            </div>
            <div class="progress-bar"><div class="progress-fill" style="width:{pct}%"></div></div>""",
            unsafe_allow_html=True,
        )

        for i, q in enumerate(questions):
            with st.container(border=True):
                st.markdown(
                    f"<div style='font-size:.68rem;color:var(--muted);text-transform:uppercase;"
                    f"letter-spacing:.05em;margin-bottom:.3rem'>Question {i+1} / {total}</div>"
                    f"<div style='font-size:.94rem;font-weight:600;color:var(--text);"
                    f"margin-bottom:.8rem;line-height:1.5'>{q['question']}</div>",
                    unsafe_allow_html=True,
                )
                sel = st.radio(
                    f"q{i}", q["options"],
                    key=f"q_ans_{current_chat_sid}_{i}",
                    label_visibility="collapsed",
                    index=None,
                )
                if sel is not None:
                    qs["answers"][i] = sel

        answered_now = len(qs["answers"])
        all_done = answered_now == total
        sb_col, rs_col = st.columns([3, 1])
        with sb_col:
            lbl = "Submit Quiz →" if all_done else f"Answer all questions to submit ({answered_now}/{total})"
            if st.button(lbl, key="submit_quiz", use_container_width=True, disabled=not all_done):
                score = sum(1 for i, q in enumerate(questions) if qs["answers"].get(i) == q["answer"])
                accuracy = round(score / total * 100, 1)
                wrong = [q["question"][:50] for i, q in enumerate(questions)
                         if qs["answers"].get(i) != q["answer"]]
                db_save_quiz_result(
                    user_id, st.session_state.quiz_id,
                    qs["topic"], score, total, accuracy,
                    "; ".join(wrong[:3]) if wrong else "None",
                )
                st.session_state.quiz_submitted = True
                st.rerun()
        with rs_col:
            if st.button("Reset", key="reset_quiz", use_container_width=True):
                qs["answers"] = {}
                st.rerun()

    else:
        # ── Quiz results ──
        qs = st.session_state.quiz_state
        questions = qs["questions"]
        total = len(questions)
        score = sum(1 for i, q in enumerate(questions) if qs["answers"].get(i) == q["answer"])
        pct = round(score / total * 100, 1)
        grade = "🏆 Excellent!" if pct >= 80 else "👍 Good Work!" if pct >= 60 else "📚 Keep Practising"
        grade_col = "var(--accent)" if pct >= 80 else "var(--warn)" if pct >= 60 else "var(--danger)"

        if pct >= 80:
            st.balloons()

        st.markdown(
            f"""<div class="score-banner">
            <div class="score-num">{score}<span style="font-size:1.4rem;color:var(--sub)">/{total}</span></div>
            <div style="font-size:.78rem;color:var(--sub);text-transform:uppercase;
                        letter-spacing:.05em;margin-top:.3rem">Final Score · {pct}%</div>
            <div style="font-size:.95rem;font-weight:700;margin-top:.6rem;color:{grade_col}">{grade}</div>
            </div>""",
            unsafe_allow_html=True,
        )

        # Save wrong answers as flashcards
        fc_col, new_col, diff_col = st.columns(3)
        with fc_col:
            if st.button("🃏 Save Wrong → Flashcards", key="save_fc_wrong", use_container_width=True):
                wrong_cards = [
                    {
                        "front": q["question"],
                        "back": f"✅ {q['answer']}\n\n💡 {q.get('explanation', '')}",
                    }
                    for i, q in enumerate(questions)
                    if qs["answers"].get(i) != q["answer"]
                ]
                if wrong_cards:
                    db_save_flashcards(user_id, qs["topic"], wrong_cards, source="quiz_wrong")
                    st.success(f"✅ Saved {len(wrong_cards)} flashcard(s)!")
                else:
                    st.info("Perfect score — no wrong answers to save.")

        # Save ALL answers as flashcards
        with new_col:
            if st.button("🃏 Save All → Flashcards", key="save_fc_all", use_container_width=True):
                all_cards = [
                    {"front": q["question"], "back": f"✅ {q['answer']}\n\n💡 {q.get('explanation','')}"}
                    for q in questions
                ]
                db_save_flashcards(user_id, qs["topic"], all_cards, source="quiz_all")
                st.success(f"✅ Saved {len(all_cards)} flashcard(s)!")

        with diff_col:
            if st.button("+ New Quiz", key="new_quiz_btn", use_container_width=True):
                st.session_state.quiz_state = None
                st.session_state.quiz_submitted = False
                st.rerun()

        # Detailed review
        st.markdown(
            "<div style='font-size:.75rem;font-weight:600;text-transform:uppercase;"
            "letter-spacing:.05em;color:var(--sub);margin:.9rem 0 .4rem'>Detailed Review</div>",
            unsafe_allow_html=True,
        )
        for i, q in enumerate(questions):
            user_ans = qs["answers"].get(i, "—")
            correct = q["answer"]
            ok = user_ans == correct
            with st.container(border=True):
                st.markdown(
                    f"""<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:.8rem">
                    <div style="flex:1">
                        <div style="font-size:.68rem;color:var(--muted);text-transform:uppercase;
                                    letter-spacing:.05em;margin-bottom:.25rem">Q{i+1}</div>
                        <div style="font-size:.92rem;font-weight:600;color:var(--text);
                                    margin-bottom:.4rem;line-height:1.5">{q['question']}</div>
                        <div style="font-size:.82rem">
                            <span style="color:var(--sub)">Your answer: </span>
                            <span style="color:{'var(--accent)' if ok else 'var(--danger)'};font-weight:600">{user_ans}</span>
                        </div>
                        {f'<div style="font-size:.82rem;margin-top:.15rem"><span style="color:var(--sub)">Correct: </span><span style="color:var(--accent);font-weight:600">{correct}</span></div>' if not ok else ''}
                    </div>
                    <div style="font-size:1.3rem">{'✅' if ok else '❌'}</div>
                    </div>""",
                    unsafe_allow_html=True,
                )
                if q.get("explanation"):
                    st.markdown(
                        f"""<div style="background:var(--accent-bg);border-left:3px solid var(--accent);
                                    border-radius:0 6px 6px 0;padding:.45rem .8rem;margin-top:.4rem;
                                    font-size:.8rem;color:var(--sub);line-height:1.6">
                        💡 {q['explanation']}</div>""",
                        unsafe_allow_html=True,
                    )

        if st.button("↺ Retake Same Quiz", key="retake_btn", use_container_width=True):
            qs["answers"] = {}
            st.session_state.quiz_submitted = False
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


# ============================================================
# SECTION 13c — FLASHCARDS TAB
# ============================================================
with tab_fc:
    st.markdown("<div style='padding:1.2rem 1.5rem 0'>", unsafe_allow_html=True)
    fc_gen_tab, fc_review_tab = st.tabs(["➕ Generate New", "📖 Review Cards"])

    with fc_gen_tab:
        with st.container(border=True):
            st.markdown(
                "<div style='font-size:.92rem;font-weight:700;color:var(--text);margin-bottom:.6rem'>"
                "Generate Flashcards with AI</div>",
                unsafe_allow_html=True,
            )
            fc_topic = st.text_input("Topic", placeholder="e.g. Cell Biology, Algebra…", key="fc_topic")
            fc_num = st.selectbox("Number of cards", [5, 10, 15, 20], index=1, key="fc_num")
            if st.button("Generate →", key="gen_fc_btn", use_container_width=True):
                if not fc_topic.strip():
                    st.warning("Enter a topic.")
                else:
                    with st.spinner("Creating flashcards…"):
                        try:
                            p = (
                                f"{SYSTEM_PROMPT}\nLevel: {level}\nTopic: {fc_topic}\n"
                                f"Generate {fc_num} flashcards for memorisation.\n"
                                "Return ONLY valid JSON array:\n"
                                '[{"front":"Question or term","back":"Answer or definition"}]'
                            )
                            resp = ai_model.generate_content(p)
                            clean = re.sub(r"```(?:json)?|```", "", resp.text).strip()
                            cards = json.loads(clean)
                            db_save_flashcards(user_id, fc_topic, cards, source="generated")
                            st.success(f"✅ {len(cards)} flashcards created for '{fc_topic}'!")
                            st.session_state.fc_index = 0
                            st.session_state.fc_flipped = {}
                        except Exception as e:
                            st.error(f"Error: {e}")
                    st.rerun()

    with fc_review_tab:
        all_cards = db_get_flashcards(user_id)
        if not all_cards:
            st.markdown(
                """<div style="text-align:center;padding:3rem 1rem">
                <div style="font-size:2rem">🃏</div>
                <div style="font-size:.88rem;color:var(--muted);margin-top:.6rem">
                    No flashcards yet.<br>Generate some above or save quiz answers as flashcards.
                </div></div>""",
                unsafe_allow_html=True,
            )
        else:
            topics = list(dict.fromkeys([c["topic"] for c in all_cards]))
            sel_topic = st.selectbox("Filter by topic", ["All Topics"] + topics, key="fc_filter")
            filtered = all_cards if sel_topic == "All Topics" else [c for c in all_cards if c["topic"] == sel_topic]

            if filtered:
                idx = st.session_state.fc_index % len(filtered)
                card = filtered[idx]
                flip_key = card["id"]
                flipped = st.session_state.fc_flipped.get(flip_key, False)

                st.markdown(
                    f"<div style='text-align:center;font-size:.73rem;color:var(--muted);margin-bottom:.8rem'>"
                    f"Card {idx+1} / {len(filtered)} · {card['topic']} "
                    f"{'(Quiz source)' if card.get('source','').startswith('quiz') else ''}"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                content = card["back"] if flipped else card["front"]
                label = "💡 Answer" if flipped else "❓ Question"
                txt_col = "var(--accent)" if flipped else "var(--text)"

                st.markdown(
                    f"""<div class="flashcard">
                    <div>
                        <div style="font-size:.68rem;color:var(--muted);text-transform:uppercase;
                                    letter-spacing:.06em;margin-bottom:.5rem">{label}</div>
                        <div class="flashcard-text" style="color:{txt_col}">{content}</div>
                    </div></div>""",
                    unsafe_allow_html=True,
                )

                cf, cp, cn, cd = st.columns([2, 1, 1, 1])
                with cf:
                    if st.button("🔄 Flip", key=f"flip_{flip_key}", use_container_width=True):
                        st.session_state.fc_flipped[flip_key] = not flipped
                        st.rerun()
                with cp:
                    if st.button("← Prev", key="fc_prev", use_container_width=True):
                        st.session_state.fc_index = (idx - 1) % len(filtered)
                        st.session_state.fc_flipped = {}
                        st.rerun()
                with cn:
                    if st.button("Next →", key="fc_next", use_container_width=True):
                        st.session_state.fc_index = (idx + 1) % len(filtered)
                        st.session_state.fc_flipped = {}
                        st.rerun()
                with cd:
                    if st.button("🗑️", key=f"del_fc_{flip_key}", use_container_width=True):
                        db_delete_flashcard(flip_key)
                        st.session_state.fc_index = max(0, idx - 1)
                        st.session_state.fc_flipped = {}
                        st.rerun()

                done_pct = int((idx + 1) / len(filtered) * 100)
                st.markdown(
                    f"""<div class="progress-bar" style="margin-top:1rem">
                    <div class="progress-fill" style="width:{done_pct}%"></div></div>
                    <div style="text-align:center;font-size:.7rem;color:var(--muted)">{done_pct}% through deck</div>""",
                    unsafe_allow_html=True,
                )

    st.markdown("</div>", unsafe_allow_html=True)


# ============================================================
# SECTION 13d — NOTES TAB
# ============================================================
NOTE_COLORS = {
    "🟢 Green":  "#10a37f",
    "🟡 Yellow": "#f59e0b",
    "🔴 Red":    "#ef4444",
    "🟣 Purple": "#8b5cf6",
    "🔵 Blue":   "#3b82f6",
}

with tab_notes:
    st.markdown("<div style='padding:1.2rem 1.5rem 0'>", unsafe_allow_html=True)
    nc_left, nc_right = st.columns([1, 2])

    with nc_left:
        with st.container(border=True):
            editing_id = st.session_state.editing_note_id
            editing_note = None
            if editing_id:
                notes_all = db_get_notes(user_id)
                editing_note = next((n for n in notes_all if n["id"] == editing_id), None)

            st.markdown(
                f"<div style='font-size:.88rem;font-weight:700;color:var(--text);margin-bottom:.5rem'>"
                f"{'✏️ Edit Note' if editing_note else '📝 New Note'}</div>",
                unsafe_allow_html=True,
            )
            note_title = st.text_input(
                "Title",
                value=editing_note["title"] if editing_note else "",
                placeholder="Note title…",
                key="note_title",
            )
            note_content = st.text_area(
                "Content",
                value=editing_note["content"] if editing_note else "",
                placeholder="Write your note…",
                height=140,
                key="note_content",
            )
            color_pick = st.selectbox(
                "Colour",
                list(NOTE_COLORS.keys()),
                key="note_color_sel",
            )
            note_color = NOTE_COLORS[color_pick]

            if editing_note:
                sc1, sc2 = st.columns(2)
                with sc1:
                    if st.button("Update", key="update_note_btn", use_container_width=True):
                        if note_title and note_content:
                            db_update_note(editing_id, note_title, note_content, note_color)
                            st.session_state.editing_note_id = None
                            st.success("Updated!")
                            st.rerun()
                        else:
                            st.warning("Fill title and content.")
                with sc2:
                    if st.button("Cancel", key="cancel_edit_btn", use_container_width=True):
                        st.session_state.editing_note_id = None
                        st.rerun()
            else:
                if st.button("Save Note →", key="save_note_btn", use_container_width=True):
                    if note_title and note_content:
                        db_add_note(user_id, note_title, note_content, note_color)
                        st.success("Saved!")
                        st.rerun()
                    else:
                        st.warning("Fill title and content.")

    with nc_right:
        notes = db_get_notes(user_id)
        if not notes:
            st.markdown(
                """<div style="text-align:center;padding:2.5rem 1rem">
                <div style="font-size:1.8rem">📒</div>
                <div style="font-size:.85rem;color:var(--muted);margin-top:.5rem">
                    No notes yet. Add your first note!
                </div></div>""",
                unsafe_allow_html=True,
            )
        else:
            for note in notes:
                with st.container(border=True):
                    st.markdown(
                        f"""<div class="note-card" style="border-left-color:{note['color']}">
                        <div style="font-size:.88rem;font-weight:700;color:var(--text)">{note['title']}</div>
                        <div style="font-size:.68rem;color:var(--muted);margin-bottom:.4rem">
                            {datetime.datetime.fromisoformat(note['created_at']).strftime('%b %d, %H:%M')}
                        </div>
                        <div style="font-size:.83rem;color:var(--sub);line-height:1.6">{note['content']}</div>
                        </div>""",
                        unsafe_allow_html=True,
                    )
                    ne_col, nd_col = st.columns(2)
                    with ne_col:
                        if st.button("✎ Edit", key=f"edit_note_{note['id']}", use_container_width=True):
                            st.session_state.editing_note_id = note["id"]
                            st.rerun()
                    with nd_col:
                        if st.button("🗑️ Delete", key=f"del_note_{note['id']}", use_container_width=True):
                            db_delete_note(note["id"])
                            if st.session_state.editing_note_id == note["id"]:
                                st.session_state.editing_note_id = None
                            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


# ============================================================
# SECTION 13e — FOCUS TIMER TAB
# ============================================================
with tab_timer:
    st.markdown("<div style='padding:1.5rem 2rem'>", unsafe_allow_html=True)

    st.markdown(
        """<div style="text-align:center;margin-bottom:1.2rem">
        <div style="font-size:1.1rem;font-weight:700;color:var(--text)">⏱️ Focus Timer</div>
        <div style="font-size:.8rem;color:var(--sub);margin-top:.2rem">
            Pomodoro technique — stay focused, take breaks, stay sharp.
        </div></div>""",
        unsafe_allow_html=True,
    )

    _, tc, _ = st.columns([1, 2, 1])
    with tc:
        DURATIONS = {
            "🎯 Focus (25 min)":      25 * 60,
            "☕ Short Break (5 min)":  5 * 60,
            "🌿 Long Break (15 min)": 15 * 60,
        }
        mode_sel = st.radio("Timer mode", list(DURATIONS.keys()), key="timer_mode_radio")
        selected_secs = DURATIONS[mode_sel]

        now = datetime.datetime.now()
        timer_end = st.session_state.timer_end

        if timer_end and now < timer_end:
            remaining = int((timer_end - now).total_seconds())
            mins, secs = divmod(remaining, 60)
            pct = int((1 - remaining / selected_secs) * 100)

            st.markdown(
                f"""<div class="pomo-display">{mins:02d}:{secs:02d}</div>
                <div class="pomo-label">⚡ Focusing — stay with it!</div>
                <div class="progress-bar" style="margin-top:1rem">
                    <div class="progress-fill" style="width:{pct}%"></div>
                </div>""",
                unsafe_allow_html=True,
            )
            col_pause, col_stop = st.columns(2)
            with col_pause:
                if st.button("⏸ Pause & Reset", key="pomo_pause", use_container_width=True):
                    st.session_state.timer_end = None
                    st.rerun()
            with col_stop:
                if st.button("⏹ Stop Timer", key="pomo_stop", use_container_width=True):
                    st.session_state.timer_end = None
                    st.rerun()
            # Real-time countdown — sleep 1s then rerun
            time.sleep(1)
            st.rerun()

        else:
            if timer_end and now >= timer_end:
                label = "Focus" if "Focus" in mode_sel else "Break"
                st.success(f"✅ {label} session complete! Great work.")
                st.session_state.timer_end = None

            mins_d, secs_d = divmod(selected_secs, 60)
            st.markdown(
                f"""<div class="pomo-display">{mins_d:02d}:{secs_d:02d}</div>
                <div class="pomo-label">Ready to start</div>""",
                unsafe_allow_html=True,
            )
            if st.button("▶ Start Timer", key="pomo_start", use_container_width=True):
                st.session_state.timer_end = now + datetime.timedelta(seconds=selected_secs)
                st.rerun()

        st.markdown("<hr>", unsafe_allow_html=True)
        st.markdown(
            """<div style="background:var(--panel);border:1px solid var(--border);
                        border-radius:10px;padding:1.2rem;text-align:center">
            <div style="font-size:.83rem;font-weight:600;color:var(--text);margin-bottom:.5rem">
                💡 Pomodoro Tips
            </div>
            <div style="font-size:.78rem;color:var(--sub);line-height:1.9">
                🎯 Work for 25 minutes without distractions<br>
                ☕ Take a 5-minute break after each session<br>
                🌿 Take a 15-minute break after 4 sessions<br>
                📵 Put your phone away during focus time
            </div></div>""",
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)


# ============================================================
# SECTION 13f — DASHBOARD TAB
# ============================================================
with tab_dash:
    st.markdown("<div style='padding:1.2rem 1.5rem 0'>", unsafe_allow_html=True)

    scope = st.radio(
        "View", ["This Session", "All Time (Overall)"],
        horizontal=True, key="dash_scope",
    )
    results = db_get_quiz_results(user_id)

    if not results:
        st.markdown(
            """<div style="text-align:center;padding:4rem 1rem">
            <div style="font-size:2.2rem">📊</div>
            <div style="font-size:.92rem;font-weight:600;color:var(--sub);margin-top:.8rem">
                No data yet
            </div>
            <div style="font-size:.8rem;color:var(--muted);margin-top:.3rem">
                Complete a quiz to see your performance analytics here.
            </div></div>""",
            unsafe_allow_html=True,
        )
    else:
        df = pd.DataFrame(results)
        df["created_at"] = pd.to_datetime(df["created_at"])

        avg_acc = df["accuracy"].mean()
        best = df["accuracy"].max()
        total_q = len(df)
        total_fc = len(db_get_flashcards(user_id))
        total_notes = len(db_get_notes(user_id))

        st.markdown(
            f"<div style='font-size:.72rem;font-weight:600;text-transform:uppercase;"
            f"letter-spacing:.05em;color:var(--sub);margin-bottom:.8rem'>"
            f"{'Session Overview' if scope == 'This Session' else 'Overall Performance'} — {display_name}</div>",
            unsafe_allow_html=True,
        )

        k1, k2, k3, k4, k5, k6 = st.columns(6)
        metrics = [
            (f"{avg_acc:.0f}%", "Avg Accuracy"),
            (f"{best:.0f}%",    "Best Score"),
            (str(total_q),      "Quizzes Done"),
            (f"🔥 {streak}",    "Day Streak"),
            (str(total_fc),     "Flashcards"),
            (str(total_notes),  "Notes"),
        ]
        for col, (val, lbl) in zip([k1, k2, k3, k4, k5, k6], metrics):
            with col:
                st.markdown(
                    f'<div class="metric-card"><div class="metric-val">{val}</div>'
                    f'<div class="metric-lbl">{lbl}</div></div>',
                    unsafe_allow_html=True,
                )

        st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

        # ── Row 1: Line chart + Bar chart ──
        c1, c2 = st.columns(2)

        with c1:
            with st.container(border=True):
                st.markdown(
                    "<div style='font-size:.75rem;font-weight:600;color:var(--sub);"
                    "text-transform:uppercase;letter-spacing:.05em;padding:.2rem 0 .5rem'>"
                    "Accuracy Over Time</div>",
                    unsafe_allow_html=True,
                )
                dfs = df.sort_values("created_at")
                fig, ax = plt.subplots(figsize=(5, 3))
                ax.fill_between(range(len(dfs)), dfs["accuracy"], alpha=0.12, color="#10a37f")
                ax.plot(range(len(dfs)), dfs["accuracy"], marker="o", color="#10a37f",
                        lw=2, ms=5, markeredgewidth=0)
                ax.axhline(dfs["accuracy"].mean(), color="#f59e0b", ls="--", lw=1, alpha=0.6)
                ax.set_ylim(0, 110)
                ax.set_ylabel("Accuracy %", fontsize=8)
                ax.set_xticks(range(len(dfs)))
                ax.set_xticklabels(
                    [d.strftime("%m/%d") for d in dfs["created_at"]],
                    rotation=30, fontsize=7,
                )
                style_chart(fig, ax)
                st.pyplot(fig)
                plt.close(fig)

        with c2:
            with st.container(border=True):
                st.markdown(
                    "<div style='font-size:.75rem;font-weight:600;color:var(--sub);"
                    "text-transform:uppercase;letter-spacing:.05em;padding:.2rem 0 .5rem'>"
                    "Score by Topic</div>",
                    unsafe_allow_html=True,
                )
                topic_avg = df.groupby("topic")["accuracy"].mean().sort_values(ascending=False).head(8)
                fig2, ax2 = plt.subplots(figsize=(5, 3))
                bar_colors = [
                    "#10a37f" if v >= 70 else "#f59e0b" if v >= 50 else "#ef4444"
                    for v in topic_avg.values
                ]
                topic_avg.plot(kind="bar", ax=ax2, color=bar_colors, width=0.55, edgecolor="none")
                ax2.set_ylabel("Accuracy %", fontsize=8)
                ax2.set_ylim(0, 120)
                for bar in ax2.patches:
                    h = bar.get_height()
                    c = "#10a37f" if h >= 70 else "#f59e0b" if h >= 50 else "#ef4444"
                    ax2.text(bar.get_x() + bar.get_width() / 2, h + 2, f"{h:.0f}%",
                             ha="center", fontsize=7, color=c)
                ax2.tick_params(axis="x", rotation=30)
                style_chart(fig2, ax2)
                st.pyplot(fig2)
                plt.close(fig2)

        # ── Row 2: Pie + Table ──
        c3, c4 = st.columns(2)

        with c3:
            with st.container(border=True):
                st.markdown(
                    "<div style='font-size:.75rem;font-weight:600;color:var(--sub);"
                    "text-transform:uppercase;letter-spacing:.05em;padding:.2rem 0 .5rem'>"
                    "Performance Distribution</div>",
                    unsafe_allow_html=True,
                )
                perf = df["accuracy"].apply(
                    lambda x: "Excellent ≥80%" if x >= 80 else "Good 50–79%" if x >= 50 else "Needs Work <50%"
                ).value_counts()
                pie_colors = {
                    "Excellent ≥80%": "#10a37f",
                    "Good 50–79%": "#f59e0b",
                    "Needs Work <50%": "#ef4444",
                }
                fig3, ax3 = plt.subplots(figsize=(4, 3))
                dark = st.session_state.theme == "dark"
                ec = "#1e2130" if dark else "#ffffff"
                wedges, texts, autotexts = ax3.pie(
                    perf, labels=perf.index, autopct="%1.0f%%",
                    colors=[pie_colors.get(k, "#888") for k in perf.index],
                    startangle=90, pctdistance=0.75,
                    wedgeprops=dict(edgecolor=ec, linewidth=2),
                )
                tc_pie = "#8e8ea0" if dark else "#555"
                for t in texts:
                    t.set_fontsize(7); t.set_color(tc_pie)
                for a in autotexts:
                    a.set_fontsize(7); a.set_color("#fff"); a.set_fontweight("bold")
                fig3.patch.set_facecolor("#1e2130" if dark else "#fff")
                fig3.tight_layout()
                st.pyplot(fig3)
                plt.close(fig3)

        with c4:
            with st.container(border=True):
                st.markdown(
                    "<div style='font-size:.75rem;font-weight:600;color:var(--sub);"
                    "text-transform:uppercase;letter-spacing:.05em;padding:.2rem 0 .5rem'>"
                    "Quiz History</div>",
                    unsafe_allow_html=True,
                )
                disp = df[["topic", "score", "total", "accuracy", "created_at"]].copy()
                disp["created_at"] = disp["created_at"].dt.strftime("%m/%d %H:%M")
                disp["result"] = disp.apply(lambda r: f"{int(r['score'])}/{int(r['total'])}", axis=1)
                disp["accuracy"] = disp["accuracy"].apply(lambda x: f"{x:.0f}%")
                disp = disp[["topic", "result", "accuracy", "created_at"]].rename(columns={
                    "topic": "Topic", "result": "Score",
                    "accuracy": "Accuracy", "created_at": "Date",
                })
                st.dataframe(disp, use_container_width=True, hide_index=True, height=220)

    st.markdown("</div>", unsafe_allow_html=True)
