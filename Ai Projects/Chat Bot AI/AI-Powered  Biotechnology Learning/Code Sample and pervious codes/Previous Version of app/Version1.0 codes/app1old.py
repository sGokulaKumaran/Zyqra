# ============================================================
# 🧠 Zyqra — Fixed + Enhanced Platform
# Fixes: Sidebar always visible, toggle button, all bugs fixed
# New: Pomodoro Timer, Flashcards, Notes, Study Streak,
#      Better charts, Confetti on quiz, Progress indicators
# ============================================================

import streamlit as st
import google.generativeai as genai
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import re, json, datetime, tempfile, os, hashlib, sqlite3
from collections import Counter
from pathlib import Path

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="Zyqra Smart Learn AI",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"   # ✅ FIX: always start expanded
)

# ============================================================
# DATABASE SETUP
# ============================================================
DB_PATH = Path("smartlearn.db")

def get_db():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            streak INTEGER DEFAULT 0,
            last_active DATE
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            session_key TEXT NOT NULL,
            session_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, session_key)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE TABLE IF NOT EXISTS quiz_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            session_id INTEGER NOT NULL,
            topic TEXT NOT NULL,
            score INTEGER NOT NULL,
            total INTEGER NOT NULL,
            accuracy REAL NOT NULL,
            weak_topics TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            session_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            color TEXT DEFAULT '#10a37f',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE TABLE IF NOT EXISTS flashcards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            topic TEXT NOT NULL,
            front TEXT NOT NULL,
            back TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """)

init_db()

# ============================================================
# AUTH HELPERS
# ============================================================
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def create_user(username: str, password: str) -> tuple:
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username.strip().lower(), hash_password(password))
            )
        return True, "Account created!"
    except sqlite3.IntegrityError:
        return False, "Username already exists."

def verify_user(username: str, password: str):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username=? AND password_hash=?",
            (username.strip().lower(), hash_password(password))
        ).fetchone()
    if row:
        # Update streak
        today = datetime.date.today()
        user = dict(row)
        last = user.get("last_active")
        streak = user.get("streak", 0) or 0
        if last:
            try:
                last_date = datetime.date.fromisoformat(str(last))
                delta = (today - last_date).days
                if delta == 1:
                    streak += 1
                elif delta > 1:
                    streak = 1
            except Exception:
                streak = 1
        else:
            streak = 1
        with get_db() as conn:
            conn.execute(
                "UPDATE users SET streak=?, last_active=? WHERE id=?",
                (streak, today.isoformat(), user["id"])
            )
        user["streak"] = streak
        return user
    return None

# ============================================================
# DB CHAT HELPERS
# ============================================================
def db_get_sessions(user_id: int) -> list:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE user_id=? ORDER BY created_at ASC",
            (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]

def db_create_session(user_id: int, session_key: str, session_name: str) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO sessions (user_id, session_key, session_name) VALUES (?,?,?)",
            (user_id, session_key, session_name)
        )
        if cur.lastrowid:
            return cur.lastrowid
        row = conn.execute(
            "SELECT id FROM sessions WHERE user_id=? AND session_key=?",
            (user_id, session_key)
        ).fetchone()
        return row["id"]

def db_rename_session(session_id: int, new_name: str):
    with get_db() as conn:
        conn.execute("UPDATE sessions SET session_name=? WHERE id=?", (new_name, session_id))

def db_delete_session(session_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM quiz_results WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM notes WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))

def db_get_messages(session_id: int) -> list:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id=? ORDER BY created_at ASC",
            (session_id,)
        ).fetchall()
    return [dict(r) for r in rows]

def db_add_message(session_id: int, role: str, content: str):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?,?,?)",
            (session_id, role, content)
        )

def db_save_quiz_result(user_id, session_id, topic, score, total, accuracy, weak_topics):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO quiz_results (user_id, session_id, topic, score, total, accuracy, weak_topics)
               VALUES (?,?,?,?,?,?,?)""",
            (user_id, session_id, topic, score, total, accuracy, weak_topics)
        )

def db_get_quiz_results(user_id: int, session_id: int = None) -> list:
    with get_db() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM quiz_results WHERE user_id=? AND session_id=? ORDER BY created_at ASC",
                (user_id, session_id)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM quiz_results WHERE user_id=? ORDER BY created_at ASC",
                (user_id,)
            ).fetchall()
    return [dict(r) for r in rows]

def db_add_note(user_id, session_id, title, content, color="#10a37f"):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO notes (user_id, session_id, title, content, color) VALUES (?,?,?,?,?)",
            (user_id, session_id, title, content, color)
        )

def db_get_notes(user_id: int, session_id: int = None) -> list:
    with get_db() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM notes WHERE user_id=? AND session_id=? ORDER BY created_at DESC",
                (user_id, session_id)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM notes WHERE user_id=? ORDER BY created_at DESC",
                (user_id,)
            ).fetchall()
    return [dict(r) for r in rows]

def db_delete_note(note_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM notes WHERE id=?", (note_id,))

def db_save_flashcards(user_id, topic, cards):
    with get_db() as conn:
        for card in cards:
            conn.execute(
                "INSERT INTO flashcards (user_id, topic, front, back) VALUES (?,?,?,?)",
                (user_id, topic, card.get("front",""), card.get("back",""))
            )

def db_get_flashcards(user_id: int) -> list:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM flashcards WHERE user_id=? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]

def db_delete_flashcard(card_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM flashcards WHERE id=?", (card_id,))

# ============================================================
# SESSION STATE INIT
# ============================================================
def init_session_state():
    defaults = {
        "logged_in": False,
        "user": None,
        "current_session_id": None,
        "current_session_name": "New Chat",
        "quiz_state": None,
        "quiz_submitted": False,
        "theme": "dark",
        "rename_id": None,
        "auth_tab": "login",
        "sidebar_open": True,       # ✅ FIX: track sidebar state
        "flip_card": {},
        "fc_index": 0,
        "pomodoro_end": None,
        "pomodoro_mode": "focus",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session_state()

# ============================================================
# THEME CSS — FIXED sidebar always visible
# ============================================================
def get_theme_css(theme: str) -> str:
    if theme == "dark":
        return """
        :root {
            --bg: #0f1117;
            --surface: #1a1d27;
            --panel: #1e2130;
            --border: rgba(255,255,255,0.08);
            --border-hover: rgba(255,255,255,0.16);
            --text: #ececf1;
            --text-secondary: #8e8ea0;
            --text-muted: #565869;
            --accent: #10a37f;
            --accent-hover: #1abc95;
            --accent-light: rgba(16,163,127,0.12);
            --danger: #ef4444;
            --warn: #f59e0b;
            --user-bubble: #2a2d3e;
            --ai-bubble: #1e2130;
            --input-bg: #1a1d27;
            --shadow: rgba(0,0,0,0.4);
        }
        """
    else:
        return """
        :root {
            --bg: #f7f7f8;
            --surface: #ffffff;
            --panel: #ffffff;
            --border: rgba(0,0,0,0.08);
            --border-hover: rgba(0,0,0,0.16);
            --text: #202123;
            --text-secondary: #6e6e80;
            --text-muted: #acacbe;
            --accent: #10a37f;
            --accent-hover: #0d8a6b;
            --accent-light: rgba(16,163,127,0.08);
            --danger: #ef4444;
            --warn: #f59e0b;
            --user-bubble: #f0f0f0;
            --ai-bubble: #ffffff;
            --input-bg: #ffffff;
            --shadow: rgba(0,0,0,0.08);
        }
        """

def inject_css():
    theme_vars = get_theme_css(st.session_state.theme)
    bg_color   = "#0f1117" if st.session_state.theme == "dark" else "#f7f7f8"
    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

    {theme_vars}

    *, *::before, *::after {{ box-sizing: border-box; }}

    html, body, [class*="css"] {{
        background-color: var(--bg) !important;
        color: var(--text) !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
    }}

    .stApp {{ background-color: var(--bg) !important; }}
    #MainMenu, footer {{ visibility: hidden; }}
    /* ✅ FIX: Show the streamlit header so collapse button is accessible */
    header {{ visibility: visible !important; }}
    .block-container {{ padding: 0 !important; max-width: 100% !important; }}

    /* ✅ FIX: Force sidebar to always be reachable — show the collapse/expand arrow */
    [data-testid="collapsedControl"] {{
        display: flex !important;
        visibility: visible !important;
        opacity: 1 !important;
        background: var(--accent) !important;
        color: white !important;
        border-radius: 0 8px 8px 0 !important;
        width: 28px !important;
        height: 40px !important;
        cursor: pointer !important;
        z-index: 9999 !important;
        position: fixed !important;
        left: 0 !important;
        top: 50% !important;
        transform: translateY(-50%) !important;
        align-items: center !important;
        justify-content: center !important;
        box-shadow: 2px 0 12px rgba(16,163,127,0.35) !important;
    }}
    [data-testid="collapsedControl"] svg {{
        fill: white !important;
        color: white !important;
    }}

    /* ── SIDEBAR ── */
    [data-testid="stSidebar"] {{
        background-color: var(--surface) !important;
        border-right: 1px solid var(--border) !important;
    }}
    [data-testid="stSidebar"] > div {{ padding: 0 !important; }}

    /* ✅ FIX: Make the sidebar close button visible and styled */
    [data-testid="stSidebar"] [data-testid="baseButton-headerNoPadding"] {{
        background: var(--accent-light) !important;
        color: var(--accent) !important;
        border-radius: 6px !important;
    }}

    /* ── BUTTONS ── */
    div.stButton > button {{
        background: transparent !important;
        border: 1px solid var(--border) !important;
        color: var(--text-secondary) !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        font-size: 0.82rem !important;
        border-radius: 6px !important;
        padding: 0.42rem 0.8rem !important;
        transition: all 0.18s ease !important;
        width: 100%;
    }}
    div.stButton > button:hover {{
        background: var(--accent-light) !important;
        border-color: var(--accent) !important;
        color: var(--accent) !important;
    }}

    /* ── INPUTS ── */
    [data-baseweb="input"] input,
    [data-baseweb="textarea"] textarea {{
        background: var(--input-bg) !important;
        border: 1px solid var(--border) !important;
        color: var(--text) !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        font-size: 0.9rem !important;
        border-radius: 8px !important;
    }}
    [data-baseweb="input"] input:focus,
    [data-baseweb="textarea"] textarea:focus {{
        border-color: var(--accent) !important;
        box-shadow: 0 0 0 2px rgba(16,163,127,0.15) !important;
    }}

    /* ── SELECTBOX ── */
    [data-baseweb="select"] > div {{
        background: var(--input-bg) !important;
        border: 1px solid var(--border) !important;
        color: var(--text) !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        border-radius: 8px !important;
    }}
    [data-baseweb="popover"] [data-baseweb="menu"] {{
        background: var(--surface) !important;
        border: 1px solid var(--border) !important;
    }}
    [data-baseweb="menu"] [role="option"] {{
        color: var(--text) !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
    }}
    [data-baseweb="menu"] [role="option"]:hover {{
        background: var(--accent-light) !important;
    }}

    /* ── CHAT INPUT ── */
    [data-testid="stChatInput"] {{
        background: var(--input-bg) !important;
        border: 1px solid var(--border) !important;
        border-radius: 12px !important;
    }}
    [data-testid="stChatInput"]:focus-within {{
        border-color: var(--accent) !important;
        box-shadow: 0 0 0 2px rgba(16,163,127,0.12) !important;
    }}

    /* ── FIXED BOTTOM: Streamlit wraps chat_input in stBottom ── */
    [data-testid="stBottom"] {{
        position: fixed !important;
        bottom: 0 !important;
        right: 0 !important;
        z-index: 999 !important;
        background: var(--bg) !important;
        border-top: 1px solid var(--border) !important;
        padding: 0.8rem 1.5rem 1rem !important;
        /* left is controlled by sidebar width dynamically */
    }}

    /* Give enough bottom padding so messages aren't hidden behind fixed input */
    section[data-testid="stMain"] .block-container {{
        padding-bottom: 120px !important;
    }}

    /* ── CHAT MESSAGES ── */
    [data-testid="stChatMessage"] {{
        background: transparent !important;
        border: none !important;
        padding: 0 !important;
    }}

    /* ── TABS ── */
    [data-testid="stTabs"] [data-baseweb="tab-list"] {{
        background: transparent !important;
        border-bottom: 1px solid var(--border) !important;
        gap: 0 !important;
        padding: 0 1.5rem !important;
    }}
    [data-testid="stTabs"] [data-baseweb="tab"] {{
        background: transparent !important;
        color: var(--text-muted) !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        font-size: 0.85rem !important;
        font-weight: 500 !important;
        border: none !important;
        border-bottom: 2px solid transparent !important;
        padding: 0.9rem 1.2rem !important;
        transition: all 0.2s !important;
    }}
    [data-testid="stTabs"] [aria-selected="true"] {{
        color: var(--accent) !important;
        border-bottom: 2px solid var(--accent) !important;
    }}
    [data-testid="stTabs"] [data-baseweb="tab-highlight"] {{ display: none !important; }}

    /* ── STICKY TAB BAR ── */
    [data-testid="stTabs"] > div:first-child {{
        position: sticky !important;
        top: 0 !important;
        z-index: 200 !important;
        background: var(--bg) !important;
    }}

    /* ── CONTAINERS ── */
    [data-testid="stVerticalBlockBorderWrapper"] {{
        background: var(--panel) !important;
        border: 1px solid var(--border) !important;
        border-radius: 10px !important;
        box-shadow: 0 1px 8px var(--shadow) !important;
    }}

    /* ── RADIO ── */
    [data-testid="stRadio"] label {{
        font-size: 0.88rem !important;
        color: var(--text) !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
    }}

    /* ── LABELS ── */
    label, .stTextInput label, .stTextArea label, .stSelectbox label {{
        font-size: 0.75rem !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.05em !important;
        color: var(--text-secondary) !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
    }}

    /* ── ALERTS ── */
    [data-testid="stAlert"] {{
        background: var(--panel) !important;
        border: 1px solid var(--border) !important;
        border-radius: 8px !important;
        color: var(--text) !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        font-size: 0.85rem !important;
    }}

    /* ── SCROLLBAR ── */
    ::-webkit-scrollbar {{ width: 4px; height: 4px; }}
    ::-webkit-scrollbar-track {{ background: transparent; }}
    ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 2px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: var(--accent); }}

    /* ── SLIDER ── */
    [data-baseweb="slider"] [data-testid="stThumb"] {{
        background: var(--accent) !important;
        border: none !important;
    }}
    [data-baseweb="slider"] [data-testid="stTrackHighlight"] {{
        background: var(--accent) !important;
    }}

    hr {{ border: none !important; border-top: 1px solid var(--border) !important; margin: 1rem 0 !important; }}

    /* ══════════════════════════════════════════════
       STICKY CHAT LAYOUT — mode bar top, input bottom
       ══════════════════════════════════════════════ */

    /* Mode selector row — sticky at very top of tab content */
    .mode-bar {{
        position: sticky !important;
    top: 0 !important;
    z-index: 500 !important;
    background: var(--bg) !important;
    border-bottom: 1px solid var(--border) !important;
    padding: 0.8rem 1.5rem 0.6rem !important;
    }}

    /* Scrollable messages area — takes all remaining space */
    .chat-scroll-area {{
        flex: 1 !important;
    overflow-y: auto !important;
    height: 0 !important;
    padding: 1rem 1.5rem 1rem !important;
    }}

    /* Sticky input wrapper — when used for doc/voice/topic modes */
    .chat-input-bar {{
        position: sticky !important;
        bottom: 0 !important;
        background: var(--bg) !important;
        border-top: 1px solid var(--border) !important;
        padding: 0.6rem 1.5rem 0.8rem !important;
        z-index: 150 !important;
    }}

    /* ── METRIC CARD ── */
    .metric-card {{
        background: var(--panel); border: 1px solid var(--border);
        border-radius: 10px; padding: 1.2rem; text-align: center;
    }}
    .metric-val {{
        font-size: 2rem; font-weight: 700; color: var(--accent);
        font-family: 'Plus Jakarta Sans', sans-serif;
    }}
    .metric-label {{
        font-size: 0.72rem; color: var(--text-secondary);
        text-transform: uppercase; letter-spacing: 0.05em; margin-top: 0.3rem;
    }}

    /* ── SCORE BANNER ── */
    .score-banner {{
        background: var(--accent-light); border: 1px solid var(--accent);
        border-radius: 12px; padding: 2rem; text-align: center; margin: 1rem 0;
    }}
    .score-number {{
        font-size: 3rem; font-weight: 700; color: var(--accent);
        font-family: 'Plus Jakarta Sans', sans-serif;
    }}

    /* ── PROGRESS BAR ── */
    .progress-bar {{
        height: 4px; background: var(--border); border-radius: 2px;
        margin-bottom: 1rem; overflow: hidden;
    }}
    .progress-fill {{
        height: 100%; background: var(--accent);
        border-radius: 2px; transition: width 0.4s ease;
    }}

    /* ── FLASHCARD ── */
    .flashcard {{
        background: linear-gradient(135deg, var(--panel) 0%, var(--surface) 100%);
        border: 2px solid var(--accent);
        border-radius: 16px; padding: 2.5rem;
        min-height: 180px; text-align: center;
        display: flex; align-items: center; justify-content: center;
        cursor: pointer; transition: all 0.3s ease;
        box-shadow: 0 4px 20px rgba(16,163,127,0.15);
    }}
    .flashcard:hover {{ transform: translateY(-2px); box-shadow: 0 8px 30px rgba(16,163,127,0.25); }}
    .flashcard-text {{ font-size: 1.1rem; font-weight: 600; color: var(--text); line-height: 1.6; }}

    /* ── NOTE CARD ── */
    .note-card {{
        border-radius: 10px; padding: 1rem;
        margin-bottom: 0.6rem; border-left: 4px solid var(--accent);
        background: var(--panel); border: 1px solid var(--border);
        border-left: 4px solid;
    }}

    /* ── STREAK BADGE ── */
    .streak-badge {{
        background: linear-gradient(135deg, #f59e0b, #ef4444);
        border-radius: 20px; padding: 0.3rem 0.8rem;
        font-size: 0.78rem; font-weight: 700; color: white;
        display: inline-flex; align-items: center; gap: 0.3rem;
    }}

    /* ── DATAFRAME ── */
    [data-testid="stDataFrame"] {{
        background: var(--panel) !important;
    }}

    /* ── SEARCH CARD ── */
    .search-redirect {{
        background: var(--accent-light); border: 1px solid rgba(16,163,127,0.3);
        border-radius: 10px; padding: 1.2rem 1.5rem; margin: 0.5rem 0;
    }}

    /* ── POMODORO ── */
    .pomo-display {{
        font-size: 3.5rem; font-weight: 700; color: var(--accent);
        font-family: 'JetBrains Mono', monospace; text-align: center;
        letter-spacing: 0.05em;
    }}
    .pomo-label {{
        font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.1em;
        color: var(--text-secondary); text-align: center; margin-top: 0.3rem;
    }}
    </style>
    """, unsafe_allow_html=True)

    # ── JS: fix sticky mode bar + fixed chat input via direct DOM manipulation ──
    st.markdown(f"""
    <script>
    (function applyLayout() {{
        const BG = "{bg_color}";

        function fixLayout() {{
            // ── 1. Make the Streamlit main scroll area fill viewport ──
            const main = document.querySelector('section[data-testid="stMain"]');
            if (main) {{
                main.style.overflow = 'hidden';
                main.style.height   = '100vh';
                main.style.display  = 'flex';
                main.style.flexDirection = 'column';
            }}

            // ── 2. Make the block-container flex and fill ──
            const bc = document.querySelector('section[data-testid="stMain"] .block-container');
            if (bc) {{
                bc.style.flex           = '1';
                bc.style.overflow       = 'hidden';
                bc.style.display        = 'flex';
                bc.style.flexDirection  = 'column';
                bc.style.height = '100vh';
                bc.style.padding        = '0';
                bc.style.maxWidth       = '100%';
            }}

            // ── 3. Sticky tab bar ──
            const tabList = document.querySelector('[data-testid="stTabs"] [data-baseweb="tab-list"]');
            if (tabList) {{
                const tabBar = tabList.closest('[data-testid="stTabs"] > div');
                if (tabBar) {{
                    tabBar.style.position   = 'sticky';
                    tabBar.style.top        = '0';
                    tabBar.style.zIndex     = '200';
                    tabBar.style.background = BG;
                }}
            }}

            // ── 4. Fixed bottom: stBottom (wraps st.chat_input) ──
            const stBottom = document.querySelector('[data-testid="stBottom"]');
            if (stBottom) {{
                stBottom.style.position   = 'fixed';
                stBottom.style.bottom     = '0';
                stBottom.style.right      = '0';
                stBottom.style.zIndex     = '9999';
                stBottom.style.background = BG;
                stBottom.style.borderTop  = '1px solid rgba(255,255,255,0.08)';
                stBottom.style.padding    = '0.7rem 1.5rem 0.9rem';
                // compute left offset from sidebar
                const sidebar = document.querySelector('[data-testid="stSidebar"]');
                stBottom.style.left = sidebar ? sidebar.offsetWidth + 'px' : '0px';
            }}

            // ── 5. Sticky mode-bar div ──
            const modeBar = document.querySelector('.mode-bar');
            if (modeBar) {{
                modeBar.style.position   = 'sticky';
                modeBar.style.top        = '0';
                modeBar.style.zIndex     = '150';
                modeBar.style.background = BG;
            }}

            // ── 6. Add bottom padding so messages aren't hidden behind fixed input ──
            if (stBottom && bc) {{
                bc.style.paddingBottom = (stBottom.offsetHeight + 16) + 'px';
            }}
        }}

        // Run once immediately and then watch for DOM changes
        fixLayout();
        const observer = new MutationObserver(fixLayout);
        observer.observe(document.body, {{ childList: true, subtree: true }});

        // Also re-run on resize (sidebar open/close changes left offset)
        window.addEventListener('resize', fixLayout);
    }})();
    </script>
    """, unsafe_allow_html=True)

inject_css()

# ── Guaranteed JS execution via components iframe ──────────────────────────
import streamlit.components.v1 as components

_bg     = "#0f1117" if st.session_state.theme == "dark" else "#f7f7f8"
_border = "rgba(255,255,255,0.08)" if st.session_state.theme == "dark" else "rgba(0,0,0,0.08)"

components.html(f"""
<script>
(function() {{
    const BG     = "{_bg}";
    const BORDER = "{_border}";

    function fix() {{
        const doc = window.parent.document;

        // 1. Fix stBottom (chat input) — pinned to bottom of viewport
        const bot = doc.querySelector('[data-testid="stBottom"]');
        if (bot) {{
            bot.style.position   = 'fixed';
            bot.style.bottom     = '0';
            bot.style.right      = '0';
            bot.style.zIndex     = '9999';
            bot.style.background = BG;
            bot.style.borderTop  = '1px solid ' + BORDER;
            bot.style.padding    = '0.7rem 1.5rem 0.9rem';
            bot.style.boxShadow  = '0 -4px 20px rgba(0,0,0,0.15)';
            const sb = doc.querySelector('[data-testid="stSidebar"]');
            bot.style.left = sb ? sb.getBoundingClientRect().width + 'px' : '0px';
        }}

        // 2. Sticky mode-bar (Mode dropdown)
        const mb = doc.querySelector('.mode-bar');
        if (mb) {{
            mb.style.position   = 'sticky';
            mb.style.top        = '0';
            mb.style.zIndex     = '300';
            mb.style.background = BG;
            mb.style.borderBottom = '1px solid ' + BORDER;
        }}

        // 3. Sticky tab bar
        const tabs = doc.querySelector('[data-testid="stTabs"] [data-baseweb="tab-list"]');
        if (tabs && tabs.parentElement) {{
            tabs.parentElement.style.position   = 'sticky';
            tabs.parentElement.style.top        = '0';
            tabs.parentElement.style.zIndex     = '200';
            tabs.parentElement.style.background = BG;
        }}

        // 4. Pad main content so last message isn't hidden behind fixed input
        if (bot) {{
            const main = doc.querySelector('section[data-testid="stMain"] .block-container');
            if (main) main.style.paddingBottom = (bot.offsetHeight + 24) + 'px';
        }}
    }}

    fix();
    const obs = new MutationObserver(fix);
    obs.observe(window.parent.document.body, {{ childList: true, subtree: true }});
    window.parent.addEventListener('resize', fix);
}})();
</script>
""", height=0)

# ============================================================
# SYSTEM PROMPT
# ============================================================
SYSTEM_ROLE = """You are SmartLearn AI — an adaptive learning assistant for ALL subjects (Science, Math, Engineering, Arts, History, Literature, Technology, and more).

Guidelines:
- Adapt explanations to the student's level (School / Undergraduate / Postgraduate)
- Use clear headings (##), bullet points, and structured formatting
- Be encouraging, patient, and thorough
- For continuous chat: maintain context and build on previous answers

VISUAL SEARCH RULE:
When the user requests a diagram, chart, graph, flowchart, or any visual:
- Do NOT generate ASCII art or long text diagrams
- Output ONLY: SEARCH_QUERY: <4-8 word image search query>

For all other queries: provide helpful, structured explanations."""

# ============================================================
# HELPERS
# ============================================================
def render_ai_response(text: str):
    sq = re.search(r"SEARCH_QUERY:\s*(.+)", text)
    if sq:
        q = sq.group(1).strip()
        encoded = q.replace(" ", "+")
        st.markdown(f"""
        <div class="search-redirect">
            <div style="font-size:0.72rem; font-weight:600; text-transform:uppercase;
                        letter-spacing:0.05em; color:var(--accent); margin-bottom:0.4rem;">
                🔍 Visual Search Query
            </div>
            <div style="font-size:0.92rem; font-weight:600; color:var(--text); margin-bottom:0.6rem;">
                "{q}"
            </div>
            <a href="https://www.google.com/search?tbm=isch&q={encoded}" target="_blank"
               style="font-size:0.8rem; color:var(--accent); text-decoration:none; font-weight:500;">
                Open Google Images ↗
            </a>
            &nbsp;&nbsp;
            <a href="https://www.youtube.com/results?search_query={encoded}" target="_blank"
               style="font-size:0.8rem; color:var(--accent); text-decoration:none; font-weight:500;">
                YouTube Videos ↗
            </a>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(text)

# ============================================================
# AUTH SCREEN
# ============================================================
if not st.session_state.logged_in:
    _, auth_col, _ = st.columns([1, 1.2, 1])
    with auth_col:
        st.markdown("""
        <div style="text-align:center; padding: 2.5rem 0 1.5rem;">
            <div style="font-size:2.8rem;">🧠</div>
            <div style="font-size:1.8rem; font-weight:700; color:var(--accent); margin-top:0.5rem;">
                Zyqra AI
            </div>
            <div style="font-size:0.85rem; color:var(--text-secondary); margin-top:0.3rem;">
                Your personal adaptive learning assistant
            </div>
        </div>
        """, unsafe_allow_html=True)

        tab_login, tab_signup = st.tabs(["Sign In", "Create Account"])

        with tab_login:
            with st.container(border=True):
                st.markdown("<div style='height:0.3rem'></div>", unsafe_allow_html=True)
                uname = st.text_input("Username", key="login_user", placeholder="Enter username")
                pw = st.text_input("Password", type="password", key="login_pw", placeholder="Enter password")
                st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)
                if st.button("Sign In →", key="login_btn", use_container_width=True):
                    if uname and pw:
                        user = verify_user(uname, pw)
                        if user:
                            st.session_state.logged_in = True
                            st.session_state.user = user
                            st.rerun()
                        else:
                            st.error("Invalid username or password.")
                    else:
                        st.warning("Please fill in all fields.")

        with tab_signup:
            with st.container(border=True):
                st.markdown("<div style='height:0.3rem'></div>", unsafe_allow_html=True)
                new_user = st.text_input("Choose Username", key="reg_user", placeholder="e.g. alex_student")
                new_pw = st.text_input("Choose Password", type="password", key="reg_pw", placeholder="Min. 6 characters")
                new_pw2 = st.text_input("Confirm Password", type="password", key="reg_pw2", placeholder="Repeat password")
                st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)
                if st.button("Create Account →", key="reg_btn", use_container_width=True):
                    if not (new_user and new_pw and new_pw2):
                        st.warning("Fill in all fields.")
                    elif len(new_pw) < 6:
                        st.warning("Password must be at least 6 characters.")
                    elif new_pw != new_pw2:
                        st.error("Passwords don't match.")
                    else:
                        ok, msg = create_user(new_user, new_pw)
                        if ok:
                            st.success(f"✅ {msg} Please sign in.")
                        else:
                            st.error(msg)
    st.stop()

# ============================================================
# MAIN APP (LOGGED IN)
# ============================================================
user = st.session_state.user
user_id = user["id"]

# Refresh user data from DB to get latest streak
with get_db() as conn:
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if row:
        user = dict(row)
        st.session_state.user = user

all_sessions = db_get_sessions(user_id)

if not all_sessions:
    sid = db_create_session(user_id, "session_01", "New Chat")
    all_sessions = db_get_sessions(user_id)

if not st.session_state.current_session_id:
    st.session_state.current_session_id = all_sessions[0]["id"]
    st.session_state.current_session_name = all_sessions[0]["session_name"]

valid_ids = [s["id"] for s in all_sessions]
if st.session_state.current_session_id not in valid_ids:
    st.session_state.current_session_id = all_sessions[0]["id"]
    st.session_state.current_session_name = all_sessions[0]["session_name"]

current_sid = st.session_state.current_session_id

# ============================================================
# SIDEBAR — ✅ FULLY FIXED
# ============================================================
with st.sidebar:
    streak = user.get("streak", 0) or 0
    st.markdown(f"""
    <div style="padding: 1.2rem 1rem 0.8rem; border-bottom: 1px solid var(--border);">
        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:0.8rem;">
            <div style="display:flex; align-items:center; gap:0.7rem;">
                <div style="font-size:1.6rem;">🧠</div>
                <div>
                    <div style="font-size:1rem; font-weight:700; color:var(--text);">Zyqra AI</div>
                    <div style="font-size:0.7rem; color:var(--text-muted);">Adaptive Learning</div>
                </div>
            </div>
        </div>
        <div style="display:flex; align-items:center; justify-content:space-between;">
            <div style="background:var(--accent-light); border-radius:6px; padding:0.4rem 0.7rem;
                        font-size:0.78rem; color:var(--accent); font-weight:600;">
                👤 {user['username']}
            </div>
            <div class="streak-badge">🔥 {streak} day streak</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Theme toggle
    col_theme_label, col_theme_toggle = st.columns([2, 1])
    with col_theme_label:
        st.markdown(
            f"<div style='font-size:0.78rem; color:var(--text-secondary); padding:0.4rem 0.4rem; font-weight:500;'>"
            f"{'🌙 Dark' if st.session_state.theme == 'dark' else '☀️ Light'} Mode</div>",
            unsafe_allow_html=True
        )
    with col_theme_toggle:
        if st.button("Switch", key="theme_toggle", use_container_width=True):
            st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"
            st.rerun()

    with st.expander("⚙️ Settings", expanded=False):
        api_key = st.text_input("Gemini API Key", type="password", placeholder="AIza…", key="api_key_input")
        temperature = st.slider("Temperature", 0.0, 1.0, 0.7, key="temp_slider")
        level = st.selectbox("Academic Level", ["School", "Undergraduate", "Postgraduate"], key="level_select")

    st.markdown("<hr>", unsafe_allow_html=True)

    if st.button("＋ New Chat", key="new_chat_btn", use_container_width=True):
        idx = len(all_sessions) + 1
        new_key = f"session_{idx:03d}_{datetime.datetime.now().strftime('%H%M%S')}"
        new_name = f"Chat {idx}"
        new_sid = db_create_session(user_id, new_key, new_name)
        st.session_state.current_session_id = new_sid
        st.session_state.current_session_name = new_name
        st.session_state.quiz_state = None
        st.session_state.quiz_submitted = False
        st.rerun()

    st.markdown(
        "<div style='font-size:0.7rem; font-weight:600; text-transform:uppercase; "
        "letter-spacing:0.05em; color:var(--text-muted); padding:0.5rem 0 0.3rem;'>Recent Chats</div>",
        unsafe_allow_html=True
    )

    for sess in reversed(all_sessions):
        s_id = sess["id"]
        s_name = sess["session_name"]
        is_active = (s_id == st.session_state.current_session_id)

        if st.session_state.get("rename_id") == s_id:
            new_n = st.text_input("Rename", value=s_name, key=f"ren_inp_{s_id}", label_visibility="collapsed")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Save", key=f"ren_save_{s_id}", use_container_width=True):
                    db_rename_session(s_id, new_n.strip() or s_name)
                    if s_id == st.session_state.current_session_id:
                        st.session_state.current_session_name = new_n.strip() or s_name
                    st.session_state.rename_id = None
                    st.rerun()
            with c2:
                if st.button("Cancel", key=f"ren_cancel_{s_id}", use_container_width=True):
                    st.session_state.rename_id = None
                    st.rerun()
        else:
            msg_c = len(db_get_messages(s_id))
            active_style = "background:var(--accent-light); border-radius:6px;" if is_active else ""
            name_color = "var(--accent)" if is_active else "var(--text)"
            st.markdown(f"""
            <div style="{active_style} padding:0.5rem 0.6rem; margin-bottom:2px;">
                <div style="font-size:0.84rem; color:{name_color}; font-weight:{'600' if is_active else '400'};
                            white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                    {'💬 ' if is_active else ''}{s_name}
                </div>
                <div style="font-size:0.68rem; color:var(--text-muted);">{msg_c} messages</div>
            </div>
            """, unsafe_allow_html=True)

            col_o, col_r, col_d = st.columns([3, 1, 1])
            with col_o:
                lbl = "● Active" if is_active else "Open"
                if st.button(lbl, key=f"open_{s_id}", use_container_width=True, disabled=is_active):
                    st.session_state.current_session_id = s_id
                    st.session_state.current_session_name = s_name
                    st.session_state.quiz_state = None
                    st.session_state.quiz_submitted = False
                    st.rerun()
            with col_r:
                if st.button("✎", key=f"ren_{s_id}", use_container_width=True):
                    st.session_state.rename_id = s_id
                    st.rerun()
            with col_d:
                if len(all_sessions) > 1:
                    if st.button("✕", key=f"del_{s_id}", use_container_width=True):
                        db_delete_session(s_id)
                        if st.session_state.current_session_id == s_id:
                            remaining = [s for s in all_sessions if s["id"] != s_id]
                            if remaining:
                                st.session_state.current_session_id = remaining[0]["id"]
                                st.session_state.current_session_name = remaining[0]["session_name"]
                        st.session_state.quiz_state = None
                        st.rerun()

    st.markdown("<hr>", unsafe_allow_html=True)
    if st.button("← Sign Out", key="signout_btn", use_container_width=True):
        for k in ["logged_in", "user", "current_session_id", "current_session_name",
                  "quiz_state", "quiz_submitted", "rename_id"]:
            st.session_state.pop(k, None)
        st.rerun()

# ============================================================
# API GATE
# ============================================================
api_key = st.session_state.get("api_key_input", "")
if not api_key:
    st.markdown("""
    <div style="display:flex; flex-direction:column; align-items:center; justify-content:center;
                min-height:70vh; text-align:center; gap:1rem; padding:2rem;">
        <div style="font-size:3.5rem;">🧠</div>
        <div style="font-size:1.5rem; font-weight:700; color:var(--accent);">Almost there!</div>
        <div style="font-size:0.9rem; color:var(--text-secondary); max-width:340px; line-height:1.7;">
            Open <strong>Settings</strong> in the sidebar and enter your
            <strong>Google Gemini API key</strong> to start learning.
        </div>
        <div style="background:var(--accent-light); border:1px solid rgba(16,163,127,0.3);
                    border-radius:8px; padding:0.8rem 1.4rem; font-size:0.8rem; color:var(--accent);">
            ↖ Click ⚙️ Settings in the sidebar
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

temperature = st.session_state.get("temp_slider", 0.7)
level = st.session_state.get("level_select", "School")

genai.configure(api_key=api_key)
model = genai.GenerativeModel(
    "gemini-2.5-flash",
    generation_config={"temperature": temperature}
)

# ============================================================
# MAIN LAYOUT HEADER
# ============================================================
st.markdown(f"""
<div class="app-header" style="position:sticky; top:0; z-index:400;
            padding: 1rem 1.8rem 0.8rem; border-bottom:1px solid var(--border);
            background:var(--bg);
            display:flex; align-items:center; justify-content:space-between;">
    <div style="display:flex; align-items:center; gap:0.8rem;">
        <div style="font-size:1.5rem;">🧠</div>
        <div>
            <div style="font-size:1.1rem; font-weight:700; color:var(--text);">
                {st.session_state.current_session_name}
            </div>
            <div style="font-size:0.72rem; color:var(--text-muted);">
                {level} · {('🌙 Dark' if st.session_state.theme == 'dark' else '☀️ Light')} Mode
            </div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

tab_chat, tab_quiz, tab_flashcards, tab_notes, tab_pomodoro, tab_dashboard = st.tabs([
    "  💬  Chat  ",
    "  📝  Quiz  ",
    "  🃏  Flashcards  ",
    "  📒  Notes  ",
    "  ⏱️  Focus  ",
    "  📊  Dashboard  ",
])

# ============================================================
# TAB 1 — CHAT
# ============================================================
# ============================================================
# TAB 1 — CHAT (FIXED VERSION)
# ============================================================
with tab_chat:

    # 🔥 MAIN FLEX WRAPPER (IMPORTANT)
    st.markdown("<div style='display:flex; flex-direction:column; height:100%;'>", unsafe_allow_html=True)

    # =========================
    # 🔝 MODE BAR (STICKY TOP)
    # =========================
    st.markdown("<div class='mode-bar'>", unsafe_allow_html=True)

    col_mode, col_spacer = st.columns([2, 2])
    with col_mode:
        chat_mode = st.selectbox("Mode", [
            "Free Chat",
            "Generate Study Module",
            "Create Learning Roadmap",
            "Adaptive Suggestions",
            "Explain Document",
            "Voice Question",
        ], key="chat_mode_sel")

    st.markdown("</div>", unsafe_allow_html=True)

    # =========================
    # 📜 CHAT SCROLL AREA
    # =========================
    st.markdown("<div class='chat-scroll-area'>", unsafe_allow_html=True)

    messages = db_get_messages(current_sid)

    if messages:
        for msg in messages:
            with st.chat_message(msg["role"]):
                if msg["role"] == "assistant":
                    render_ai_response(msg["content"])
                else:
                    st.markdown(msg["content"])
    else:
        st.markdown("""
        <div style="text-align:center; padding:3rem 1rem; color:var(--text-muted);">
            <div style="font-size:2rem;">💬</div>
            <div style="font-size:0.9rem; font-weight:500;">Start a conversation</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

    # =========================
    # 🔽 INPUT BAR (BOTTOM)
    # =========================
    st.markdown("<div class='chat-input-bar'>", unsafe_allow_html=True)

    if chat_mode in ["Explain Document", "Voice Question"]:

        with st.container(border=True):

            if chat_mode == "Explain Document":
                up_file = st.file_uploader("Upload document", type=["pdf", "txt", "csv"])
                doc_q = st.text_input("Ask about document")

                if st.button("Analyze"):
                    if up_file and doc_q:
                        db_add_message(current_sid, "user", doc_q)

                        with st.spinner("Analyzing..."):
                            try:
                                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                                    tmp.write(up_file.getvalue())
                                    tmp_path = tmp.name

                                gf = genai.upload_file(tmp_path)
                                resp = model.generate_content([gf, doc_q])

                                db_add_message(current_sid, "assistant", resp.text)

                                genai.delete_file(gf.name)
                                os.remove(tmp_path)

                            except Exception as e:
                                db_add_message(current_sid, "assistant", str(e))

                        st.rerun()

            else:
                audio = st.audio_input("Record")

                if st.button("Send Voice"):
                    if audio:
                        db_add_message(current_sid, "user", "🎙️ Voice")

                        with st.spinner("Processing..."):
                            try:
                                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                                    tmp.write(audio.getvalue())
                                    tmp_path = tmp.name

                                gf = genai.upload_file(tmp_path)
                                resp = model.generate_content([gf, "Answer this audio"])

                                db_add_message(current_sid, "assistant", resp.text)

                                genai.delete_file(gf.name)
                                os.remove(tmp_path)

                            except Exception as e:
                                db_add_message(current_sid, "assistant", str(e))

                        st.rerun()

    else:

        if chat_mode == "Free Chat":
            user_input = st.chat_input("Ask anything...")

            if user_input:
                db_add_message(current_sid, "user", user_input)

                with st.spinner("Thinking..."):
                    history = db_get_messages(current_sid)[-10:]
                    history_text = "\n".join(
                        [f"{m['role']}: {m['content']}" for m in history]
                    )

                    prompt = f"{SYSTEM_ROLE}\n{history_text}\nUser: {user_input}"
                    resp = model.generate_content(prompt)

                    db_add_message(current_sid, "assistant", resp.text)

                st.rerun()

        else:
            topic = st.text_input("Topic")

            if st.button("Generate"):
                if topic:
                    db_add_message(current_sid, "user", topic)

                    resp = model.generate_content(f"{SYSTEM_ROLE}\nTopic: {topic}")
                    db_add_message(current_sid, "assistant", resp.text)

                    st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

    # 🔥 CLOSE MAIN WRAPPER
    st.markdown("</div>", unsafe_allow_html=True)

# ============================================================
# TAB 2 — QUIZ
# ============================================================
with tab_quiz:
    st.markdown("<div style='padding:1.2rem 1.5rem 0;'>", unsafe_allow_html=True)

    if not st.session_state.quiz_state:
        with st.container(border=True):
            st.markdown("""
            <div style="padding:0.3rem 0 0.8rem;">
                <div style="font-size:1rem; font-weight:700; color:var(--text);">Generate a Quiz</div>
                <div style="font-size:0.8rem; color:var(--text-secondary); margin-top:0.2rem;">
                    Answer questions, submit, and get instant results + analytics.
                </div>
            </div>
            """, unsafe_allow_html=True)

            qc1, qc2, qc3 = st.columns([3, 1, 1])
            with qc1:
                quiz_topic = st.text_input("Topic", placeholder="e.g. Newton's Laws, Calculus…", key="quiz_topic_inp")
            with qc2:
                num_q = st.selectbox("Questions", [3, 5, 7, 10], index=1, key="num_q_sel")
            with qc3:
                difficulty = st.selectbox("Difficulty", ["Easy", "Medium", "Hard"], index=1, key="difficulty_sel")

            if st.button("Generate Quiz →", key="gen_quiz_btn", use_container_width=True):
                if not quiz_topic:
                    st.warning("Enter a topic first.")
                else:
                    with st.spinner("Creating quiz…"):
                        try:
                            prompt = f"""{SYSTEM_ROLE}
Level: {level}, Difficulty: {difficulty}
Topic: {quiz_topic}
Task: Generate exactly {num_q} multiple-choice questions.
Return ONLY valid JSON array, no markdown fences:
[
  {{
    "question": "Question text",
    "options": ["Option A", "Option B", "Option C", "Option D"],
    "answer": "Exact text of correct option",
    "explanation": "Brief explanation"
  }}
]"""
                            resp = model.generate_content(prompt)
                            clean = re.sub(r"```(?:json)?|```", "", resp.text).strip()
                            quiz_data = json.loads(clean)
                            st.session_state.quiz_state = {
                                "questions": quiz_data,
                                "answers": {},
                                "topic": quiz_topic,
                                "difficulty": difficulty,
                                "level": level,
                                "num_q": num_q,
                            }
                            st.session_state.quiz_submitted = False
                            db_add_message(current_sid, "user", f"📝 Quiz: {quiz_topic} ({difficulty}, {num_q}Q)")
                            db_add_message(current_sid, "assistant", f"✅ Quiz on **{quiz_topic}** — {len(quiz_data)} questions ready!")
                        except Exception as e:
                            st.error(f"Failed to generate quiz: {e}")
                    st.rerun()
    else:
        qs = st.session_state.quiz_state
        quiz_questions = qs["questions"]
        total_q = len(quiz_questions)

        if not st.session_state.quiz_submitted:
            answered = len(qs["answers"])
            pct = int(answered / total_q * 100)

            st.markdown(f"""
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem;">
                <div>
                    <div style="font-size:1rem; font-weight:700; color:var(--text);">📝 {qs['topic']}</div>
                    <div style="font-size:0.75rem; color:var(--text-secondary);">
                        {qs.get('difficulty','Medium')} · {level} · {total_q} Questions
                    </div>
                </div>
                <div style="font-size:0.8rem; color:var(--accent); font-weight:600;">{answered}/{total_q} answered</div>
            </div>
            <div class="progress-bar"><div class="progress-fill" style="width:{pct}%"></div></div>
            """, unsafe_allow_html=True)

            for i, q in enumerate(quiz_questions):
                with st.container(border=True):
                    st.markdown(f"""
                    <div style="font-size:0.7rem; font-weight:600; text-transform:uppercase;
                                letter-spacing:0.05em; color:var(--text-muted); margin-bottom:0.4rem;">
                        Question {i+1} of {total_q}
                    </div>
                    <div style="font-size:0.95rem; font-weight:600; color:var(--text); margin-bottom:1rem; line-height:1.5;">
                        {q['question']}
                    </div>
                    """, unsafe_allow_html=True)
                    sel = st.radio(
                        f"q{i}_radio", q["options"],
                        key=f"quiz_ans_{current_sid}_{i}",
                        label_visibility="collapsed",
                        index=None
                    )
                    if sel is not None:
                        qs["answers"][i] = sel

            answered_now = len(qs["answers"])
            sub_col, reset_col = st.columns([3, 1])
            with sub_col:
                disabled = (answered_now < total_q)
                if st.button(
                    f"Submit Quiz ({answered_now}/{total_q} answered)" if disabled else "Submit & See Results →",
                    key="submit_quiz_btn", use_container_width=True, disabled=disabled
                ):
                    st.session_state.quiz_submitted = True
                    score = sum(1 for i, q in enumerate(quiz_questions) if qs["answers"].get(i) == q["answer"])
                    accuracy = round(score / total_q * 100, 1)
                    wrong_qs = [q["question"][:40] for i, q in enumerate(quiz_questions) if qs["answers"].get(i) != q["answer"]]
                    weak_str = "; ".join(wrong_qs[:3]) if wrong_qs else "None"
                    db_save_quiz_result(user_id, current_sid, qs["topic"], score, total_q, accuracy, weak_str)
                    db_add_message(current_sid, "assistant",
                        f"📊 Quiz result: **{qs['topic']}** — Score: {score}/{total_q} ({accuracy}%)")
                    st.rerun()
            with reset_col:
                if st.button("Reset", key="reset_quiz_btn", use_container_width=True):
                    qs["answers"] = {}
                    st.rerun()
            if disabled:
                st.caption(f"Answer all {total_q} questions to submit.")
        else:
            score = sum(1 for i, q in enumerate(quiz_questions) if qs["answers"].get(i) == q["answer"])
            pct = round(score / total_q * 100, 1)
            grade = "🏆 Excellent!" if pct >= 80 else "👍 Good Job!" if pct >= 60 else "📚 Keep Practicing"
            grade_color = "#10a37f" if pct >= 80 else "#f59e0b" if pct >= 60 else "#ef4444"

            # Confetti for excellent score
            if pct >= 80:
                st.balloons()

            st.markdown(f"""
            <div class="score-banner">
                <div class="score-number">{score}<span style="font-size:1.5rem; color:var(--text-secondary);">/{total_q}</span></div>
                <div style="font-size:0.8rem; color:var(--text-secondary); margin-top:0.3rem; text-transform:uppercase; letter-spacing:0.05em;">
                    Final Score · {pct}%
                </div>
                <div style="font-size:1rem; font-weight:700; margin-top:0.7rem; color:{grade_color};">{grade}</div>
            </div>
            """, unsafe_allow_html=True)

            # Save as flashcards option
            if st.button("🃏 Save Wrong Answers as Flashcards", key="save_fc_btn", use_container_width=True):
                wrong_cards = [
                    {"front": q["question"], "back": f"✅ {q['answer']}\n\n💡 {q.get('explanation','')}"}
                    for i, q in enumerate(quiz_questions)
                    if qs["answers"].get(i) != q["answer"]
                ]
                if wrong_cards:
                    db_save_flashcards(user_id, qs["topic"], wrong_cards)
                    st.success(f"✅ Saved {len(wrong_cards)} flashcards for review!")
                else:
                    st.info("Perfect score — no wrong answers to save!")

            st.markdown("<div style='font-size:0.78rem; font-weight:600; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-secondary); margin-bottom:0.6rem;'>Detailed Review</div>", unsafe_allow_html=True)

            for i, q in enumerate(quiz_questions):
                user_ans = qs["answers"].get(i, "—")
                correct_ans = q["answer"]
                is_correct = (user_ans == correct_ans)
                icon = "✅" if is_correct else "❌"
                with st.container(border=True):
                    st.markdown(f"""
                    <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:1rem;">
                        <div style="flex:1;">
                            <div style="font-size:0.7rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.3rem;">Q{i+1}</div>
                            <div style="font-size:0.92rem; font-weight:600; color:var(--text); margin-bottom:0.5rem;">{q['question']}</div>
                            <div style="font-size:0.82rem; margin-bottom:0.2rem;">
                                <span style="color:var(--text-secondary);">Your answer: </span>
                                <span style="color:{'#10a37f' if is_correct else '#ef4444'}; font-weight:600;">{user_ans}</span>
                            </div>
                            {f'<div style="font-size:0.82rem;"><span style="color:var(--text-secondary);">Correct: </span><span style="color:#10a37f; font-weight:600;">{correct_ans}</span></div>' if not is_correct else ''}
                        </div>
                        <div style="font-size:1.5rem;">{icon}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    if q.get("explanation"):
                        st.markdown(f"""
                        <div style="background:var(--accent-light); border-left:3px solid var(--accent);
                                    border-radius:0 6px 6px 0; padding:0.5rem 0.8rem; margin-top:0.4rem;
                                    font-size:0.8rem; color:var(--text-secondary); line-height:1.6;">
                            💡 {q['explanation']}
                        </div>
                        """, unsafe_allow_html=True)

            rc1, rc2, rc3 = st.columns(3)
            with rc1:
                if st.button("↺ Retake", key="retake_btn", use_container_width=True):
                    qs["answers"] = {}
                    st.session_state.quiz_submitted = False
                    st.rerun()
            with rc2:
                if st.button("⚡ New Quiz", key="new_same_btn", use_container_width=True):
                    old_topic = qs["topic"]
                    old_nq = qs.get("num_q", 5)
                    st.session_state.quiz_state = None
                    st.session_state.quiz_submitted = False
                    with st.spinner("Generating…"):
                        try:
                            prompt = f"""{SYSTEM_ROLE}
Level: {level}, Topic: {old_topic}
Generate {old_nq} NEW multiple-choice questions (different from before).
Return ONLY valid JSON array:
[{{"question":"...","options":["A","B","C","D"],"answer":"correct","explanation":"reason"}}]"""
                            resp = model.generate_content(prompt)
                            clean = re.sub(r"```(?:json)?|```", "", resp.text).strip()
                            new_quiz = json.loads(clean)
                            st.session_state.quiz_state = {"questions": new_quiz, "answers": {}, "topic": old_topic, "num_q": old_nq}
                        except Exception as e:
                            st.error(f"Error: {e}")
                    st.rerun()
            with rc3:
                if st.button("+ Different Quiz", key="diff_quiz_btn", use_container_width=True):
                    st.session_state.quiz_state = None
                    st.session_state.quiz_submitted = False
                    st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

# ============================================================
# TAB 3 — FLASHCARDS (NEW)
# ============================================================
with tab_flashcards:
    st.markdown("<div style='padding:1.2rem 1.5rem 0;'>", unsafe_allow_html=True)
    fc_tab1, fc_tab2 = st.tabs(["📖 Review Cards", "➕ Generate New"])
 
    with fc_tab2:
        with st.container(border=True):
            st.markdown("""
            <div style="font-size:0.95rem;font-weight:700;color:var(--text);margin-bottom:0.6rem;">
                Generate Flashcards with AI
            </div>
            """, unsafe_allow_html=True)
            fc_topic = st.text_input("Topic",
                                     placeholder="e.g. Cell Biology, Algebra, WW2…",
                                     key="fc_topic_inp")
            fc_num = st.selectbox("Number of cards", [5, 10, 15, 20], index=1, key="fc_num_sel")
            if st.button("Generate Flashcards →", key="gen_fc_btn", use_container_width=True):
                if not fc_topic:
                    st.warning("Enter a topic.")
                else:
                    with st.spinner("Creating flashcards…"):
                        try:
                            prompt = f"""{SYSTEM_ROLE}
Level: {level}, Topic: {fc_topic}
Generate {fc_num} flashcards for memorisation.
Return ONLY valid JSON array, no markdown fences:
[{{"front":"Question or term","back":"Answer or definition"}}]"""
                            resp  = model.generate_content(prompt)
                            clean = re.sub(r"```(?:json)?|```", "", resp.text).strip()
                            cards = json.loads(clean)
                            db_save_flashcards(user_id, fc_topic, cards)
                            st.success(f"✅ {len(cards)} flashcards created for '{fc_topic}'!")
                            st.session_state.fc_index = 0
                        except Exception as e:
                            st.error(f"Error: {e}")
                    st.rerun()
 
    with fc_tab1:
        all_cards = db_get_flashcards(user_id)
        if not all_cards:
            st.markdown("""
            <div style="text-align:center;padding:3rem 1rem;">
                <div style="font-size:2rem;">🃏</div>
                <div style="font-size:0.9rem;font-weight:500;color:var(--text-muted);margin-top:0.8rem;">
                    No flashcards yet
                </div>
                <div style="font-size:0.8rem;color:var(--text-muted);margin-top:0.3rem;">
                    Generate some above or save wrong quiz answers as flashcards.
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            topics    = list(dict.fromkeys([c["topic"] for c in all_cards]))
            sel_topic = st.selectbox("Filter by topic", ["All Topics"] + topics,
                                     key="fc_topic_filter")
            filtered  = (all_cards if sel_topic == "All Topics"
                         else [c for c in all_cards if c["topic"] == sel_topic])
 
            if filtered:
                idx       = st.session_state.fc_index % len(filtered)
                card      = filtered[idx]
                flip_key  = card["id"]
                is_flipped = st.session_state.flip_card.get(flip_key, False)
 
                st.markdown(f"""
                <div style="text-align:center;font-size:0.75rem;color:var(--text-muted);
                            margin-bottom:0.8rem;">
                    Card {idx+1} of {len(filtered)} · {card['topic']}
                </div>
                """, unsafe_allow_html=True)
 
                card_content = card["back"] if is_flipped else card["front"]
                card_label   = "💡 Answer" if is_flipped else "❓ Question"
                card_txt_col = "var(--accent)" if is_flipped else "var(--text)"
 
                st.markdown(f"""
                <div class="flashcard">
                    <div>
                        <div style="font-size:0.7rem;color:var(--text-muted);text-transform:uppercase;
                                    letter-spacing:0.06em;margin-bottom:0.6rem;">{card_label}</div>
                        <div class="flashcard-text" style="color:{card_txt_col};">{card_content}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
 
                cf, cp, cn, cd = st.columns([2, 1, 1, 1])
                with cf:
                    if st.button("🔄 Flip Card", key=f"flip_{flip_key}", use_container_width=True):
                        st.session_state.flip_card[flip_key] = not is_flipped
                        st.rerun()
                with cp:
                    if st.button("← Prev", key="fc_prev", use_container_width=True):
                        st.session_state.fc_index = (idx - 1) % len(filtered)
                        st.session_state.flip_card = {}
                        st.rerun()
                with cn:
                    if st.button("Next →", key="fc_next", use_container_width=True):
                        st.session_state.fc_index = (idx + 1) % len(filtered)
                        st.session_state.flip_card = {}
                        st.rerun()
                with cd:
                    if st.button("🗑️ Del", key=f"del_fc_{flip_key}", use_container_width=True):
                        db_delete_flashcard(flip_key)
                        st.session_state.fc_index = max(0, idx - 1)
                        st.session_state.flip_card = {}
                        st.rerun()
 
                pct_done = int((idx + 1) / len(filtered) * 100)
                st.markdown(f"""
                <div class="progress-bar" style="margin-top:1rem;">
                    <div class="progress-fill" style="width:{pct_done}%"></div>
                </div>
                <div style="text-align:center;font-size:0.72rem;color:var(--text-muted);">
                    {pct_done}% through deck
                </div>
                """, unsafe_allow_html=True)
 
    st.markdown("</div>", unsafe_allow_html=True)

# ============================================================
# TAB 4 — NOTES (NEW)
# ============================================================
with tab_notes:
    st.markdown("<div style='padding:1.2rem 1.5rem 0;'>", unsafe_allow_html=True)

    note_col1, note_col2 = st.columns([1, 2])
    NOTE_COLORS = ["#10a37f", "#f59e0b", "#ef4444", "#6366f1", "#0ea5e9"]

    with note_col1:
        with st.container(border=True):
            st.markdown("<div style='font-size:0.9rem; font-weight:700; color:var(--text); margin-bottom:0.6rem;'>📝 Add Note</div>", unsafe_allow_html=True)
            note_title = st.text_input("Title", placeholder="Note title…", key="note_title_inp")
            note_content = st.text_area("Content", placeholder="Write your note here…", key="note_content_inp", height=120)
            note_color_labels = ["🟢 Green", "🟡 Yellow", "🔴 Red", "🟣 Purple", "🔵 Blue"]
            note_color_pick = st.selectbox("Color", note_color_labels, key="note_color_sel")
            note_color = NOTE_COLORS[note_color_labels.index(note_color_pick)]
            if st.button("Save Note →", key="save_note_btn", use_container_width=True):
                if note_title and note_content:
                    db_add_note(user_id, current_sid, note_title, note_content, note_color)
                    st.success("Note saved!")
                    st.rerun()
                else:
                    st.warning("Fill in title and content.")

    with note_col2:
        note_scope = st.radio("Show", ["This Session", "All Notes"], horizontal=True, key="note_scope_radio")
        notes = db_get_notes(user_id, current_sid if note_scope == "This Session" else None)
        if not notes:
            st.markdown("""
            <div style="text-align:center; padding:2rem; color:var(--text-muted);">
                <div style="font-size:1.8rem;">📒</div>
                <div style="font-size:0.88rem; margin-top:0.5rem;">No notes yet. Add your first note!</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            for note in notes:
                with st.container(border=True):
                    st.markdown(f"""
                    <div style="border-left:4px solid {note['color']}; padding-left:0.8rem;">
                        <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                            <div>
                                <div style="font-size:0.9rem; font-weight:700; color:var(--text);">{note['title']}</div>
                                <div style="font-size:0.72rem; color:var(--text-muted);">
                                    {datetime.datetime.fromisoformat(note['created_at']).strftime('%b %d, %H:%M')}
                                </div>
                            </div>
                        </div>
                        <div style="font-size:0.85rem; color:var(--text-secondary); margin-top:0.5rem; line-height:1.6;">
                            {note['content']}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    if st.button("🗑️ Delete", key=f"del_note_{note['id']}", use_container_width=False):
                        db_delete_note(note["id"])
                        st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

# ============================================================
# TAB 5 — POMODORO FOCUS TIMER (NEW)
# ============================================================
with tab_pomodoro:
    st.markdown("<div style='padding:1.5rem 2rem;'>", unsafe_allow_html=True)

    st.markdown("""
    <div style="text-align:center; margin-bottom:1.5rem;">
        <div style="font-size:1.2rem; font-weight:700; color:var(--text);">⏱️ Focus Timer</div>
        <div style="font-size:0.8rem; color:var(--text-secondary); margin-top:0.2rem;">
            Stay focused with the Pomodoro technique
        </div>
    </div>
    """, unsafe_allow_html=True)

    p_col1, p_col2, p_col3 = st.columns([1, 2, 1])
    with p_col2:
        pomo_mode = st.radio(
            "Mode",
            ["🎯 Focus (25 min)", "☕ Short Break (5 min)", "🌿 Long Break (15 min)"],
            key="pomo_mode_radio",
            horizontal=False
        )

        durations = {"🎯 Focus (25 min)": 25 * 60, "☕ Short Break (5 min)": 5 * 60, "🌿 Long Break (15 min)": 15 * 60}
        selected_duration = durations[pomo_mode]

        now = datetime.datetime.now()
        pomo_end = st.session_state.get("pomodoro_end")

        if pomo_end and now < pomo_end:
            remaining = pomo_end - now
            total_secs = remaining.seconds
            mins = total_secs // 60
            secs = total_secs % 60
            pct = 1 - (total_secs / selected_duration)
            st.markdown(f"""
            <div class="pomo-display">{mins:02d}:{secs:02d}</div>
            <div class="pomo-label">⚡ Timer Running — Stay Focused!</div>
            <div class="progress-bar" style="margin-top:1rem;">
                <div class="progress-fill" style="width:{int(pct*100)}%"></div>
            </div>
            """, unsafe_allow_html=True)
            if st.button("⏹ Stop Timer", key="pomo_stop", use_container_width=True):
                st.session_state.pomodoro_end = None
                st.rerun()
            st.info("⏳ Refresh the page to update the timer display.")
        else:
            if pomo_end and now >= pomo_end:
                st.success("✅ Session complete! Take a break.")
                st.session_state.pomodoro_end = None

            secs_display = selected_duration
            mins_d = secs_display // 60
            secs_d = secs_display % 60
            st.markdown(f"""
            <div class="pomo-display">{mins_d:02d}:{secs_d:02d}</div>
            <div class="pomo-label">Ready to start</div>
            """, unsafe_allow_html=True)

            if st.button("▶ Start Timer", key="pomo_start", use_container_width=True):
                st.session_state.pomodoro_end = datetime.datetime.now() + datetime.timedelta(seconds=selected_duration)
                st.rerun()

        st.markdown("<hr>", unsafe_allow_html=True)
        st.markdown("""
        <div style="background:var(--panel); border:1px solid var(--border); border-radius:10px; padding:1.2rem; text-align:center;">
            <div style="font-size:0.85rem; font-weight:600; color:var(--text); margin-bottom:0.6rem;">💡 Pomodoro Tips</div>
            <div style="font-size:0.8rem; color:var(--text-secondary); line-height:1.8;">
                🎯 Work for 25 minutes without distractions<br>
                ☕ Take a 5-minute break after each session<br>
                🌿 Take a longer break after 4 sessions<br>
                📵 Put your phone away during focus time
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

# ============================================================
# TAB 6 — DASHBOARD
# ============================================================
with tab_dashboard:
    st.markdown("<div style='padding:1.2rem 1.5rem 0;'>", unsafe_allow_html=True)

    dash_scope = st.radio(
        "Analytics Scope",
        ["This Session", "All Sessions (Overall)"],
        horizontal=True,
        key="dash_scope_radio"
    )

    if dash_scope == "This Session":
        results = db_get_quiz_results(user_id, current_sid)
        scope_label = f"Session: {st.session_state.current_session_name}"
    else:
        results = db_get_quiz_results(user_id)
        scope_label = f"All Sessions — {user['username']}"

    if not results:
        st.markdown("""
        <div style="text-align:center; padding:4rem 1rem; color:var(--text-muted);">
            <div style="font-size:2.5rem; margin-bottom:1rem;">📊</div>
            <div style="font-size:0.95rem; font-weight:600; color:var(--text-secondary);">No analytics yet</div>
            <div style="font-size:0.82rem; margin-top:0.4rem;">Complete a quiz to see your performance data here.</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        df = pd.DataFrame(results)
        df["created_at"] = pd.to_datetime(df["created_at"])

        avg_acc = df["accuracy"].mean()
        avg_score = df["score"].mean() / df["total"].mean() * 10
        total_quizzes = len(df)
        best_score = df["accuracy"].max()
        total_fc = len(db_get_flashcards(user_id))
        streak = user.get("streak", 0) or 0

        st.markdown(f"<div style='font-size:0.75rem; font-weight:600; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-secondary); margin-bottom:0.8rem;'>{scope_label}</div>", unsafe_allow_html=True)

        k1, k2, k3, k4, k5, k6 = st.columns(6)
        for col, val, lbl in [
            (k1, f"{avg_acc:.0f}%", "Avg Accuracy"),
            (k2, f"{avg_score:.1f}/10", "Avg Score"),
            (k3, str(total_quizzes), "Quizzes"),
            (k4, f"{best_score:.0f}%", "Best Score"),
            (k5, str(total_fc), "Flashcards"),
            (k6, f"🔥 {streak}", "Day Streak"),
        ]:
            with col:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-val">{val}</div>
                    <div class="metric-label">{lbl}</div>
                </div>""", unsafe_allow_html=True)

        st.markdown("<div style='height:1.2rem'></div>", unsafe_allow_html=True)

        def style_chart(fig, ax):
            bg = "#1e2130" if st.session_state.theme == "dark" else "#ffffff"
            text_col = "#8e8ea0" if st.session_state.theme == "dark" else "#6e6e80"
            # ✅ FIX: matplotlib needs hex or RGBA tuples, not CSS rgba() strings
            spine_col = (1.0, 1.0, 1.0, 0.1) if st.session_state.theme == "dark" else (0.0, 0.0, 0.0, 0.1)
            fig.patch.set_facecolor(bg)
            ax.set_facecolor(bg)
            ax.tick_params(colors=text_col, labelsize=8)
            for spine in ["bottom", "left"]:
                ax.spines[spine].set_color(spine_col)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.xaxis.label.set_color(text_col)
            ax.yaxis.label.set_color(text_col)
            fig.tight_layout()

        c1, c2 = st.columns(2)

        with c1:
            with st.container(border=True):
                st.markdown("<div style='font-size:0.78rem; font-weight:600; color:var(--text-secondary); text-transform:uppercase; letter-spacing:0.05em; padding:0.3rem 0 0.6rem;'>Accuracy Over Time</div>", unsafe_allow_html=True)
                dfs = df.sort_values("created_at")
                fig1, ax1 = plt.subplots(figsize=(5, 3))
                ax1.fill_between(range(len(dfs)), dfs["accuracy"], alpha=0.15, color="#10a37f")
                ax1.plot(range(len(dfs)), dfs["accuracy"], marker="o", color="#10a37f",
                         linewidth=2, markersize=5, markerfacecolor="#10a37f", markeredgewidth=0)
                ax1.set_ylim(0, 105)
                ax1.set_ylabel("Accuracy %", fontsize=8)
                ax1.axhline(y=dfs["accuracy"].mean(), color="#f59e0b", linestyle="--", linewidth=1, alpha=0.6)
                ax1.set_xticks(range(len(dfs)))
                ax1.set_xticklabels([d.strftime("%m/%d") for d in dfs["created_at"]], rotation=30, fontsize=7)
                style_chart(fig1, ax1)
                st.pyplot(fig1)
                plt.close(fig1)

        with c2:
            with st.container(border=True):
                st.markdown("<div style='font-size:0.78rem; font-weight:600; color:var(--text-secondary); text-transform:uppercase; letter-spacing:0.05em; padding:0.3rem 0 0.6rem;'>Score by Topic</div>", unsafe_allow_html=True)
                topic_avg = df.groupby("topic")["accuracy"].mean().sort_values(ascending=False).head(8)
                fig2, ax2 = plt.subplots(figsize=(5, 3))
                colors = ["#10a37f" if v >= 70 else "#f59e0b" if v >= 50 else "#ef4444" for v in topic_avg.values]
                topic_avg.plot(kind="bar", ax=ax2, color=colors, width=0.55, edgecolor="none")
                ax2.set_ylabel("Accuracy %", fontsize=8)
                ax2.set_ylim(0, 115)
                for bar in ax2.patches:
                    ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 2,
                             f'{bar.get_height():.0f}%', ha='center', fontsize=7,
                             color="#10a37f" if bar.get_height() >= 70 else "#f59e0b" if bar.get_height() >= 50 else "#ef4444")
                ax2.tick_params(axis='x', rotation=30)
                style_chart(fig2, ax2)
                st.pyplot(fig2)
                plt.close(fig2)

        c3, c4 = st.columns(2)

        with c3:
            with st.container(border=True):
                st.markdown("<div style='font-size:0.78rem; font-weight:600; color:var(--text-secondary); text-transform:uppercase; letter-spacing:0.05em; padding:0.3rem 0 0.6rem;'>Performance Distribution</div>", unsafe_allow_html=True)
                perf = df["accuracy"].apply(
                    lambda x: "Excellent (≥80%)" if x >= 80 else "Good (50–79%)" if x >= 50 else "Needs Work (<50%)"
                ).value_counts()
                fig3, ax3 = plt.subplots(figsize=(4, 3))
                pie_colors = {"Excellent (≥80%)": "#10a37f", "Good (50–79%)": "#f59e0b", "Needs Work (<50%)": "#ef4444"}
                colors_list = [pie_colors.get(k, "#888") for k in perf.index]
                wedges, texts, autotexts = ax3.pie(
                    perf, labels=perf.index, autopct="%1.0f%%",
                    colors=colors_list, startangle=90, pctdistance=0.75,
                    wedgeprops=dict(edgecolor="#1e2130" if st.session_state.theme == "dark" else "#fff", linewidth=2)
                )
                for t in texts:
                    t.set_fontsize(7)
                    t.set_color("#8e8ea0" if st.session_state.theme == "dark" else "#6e6e80")
                for a in autotexts:
                    a.set_fontsize(7)
                    a.set_color("#fff")
                    a.set_fontweight("bold")
                fig3.patch.set_facecolor("#1e2130" if st.session_state.theme == "dark" else "#fff")
                fig3.tight_layout()
                st.pyplot(fig3)
                plt.close(fig3)

        with c4:
            with st.container(border=True):
                st.markdown("<div style='font-size:0.78rem; font-weight:600; color:var(--text-secondary); text-transform:uppercase; letter-spacing:0.05em; padding:0.3rem 0 0.6rem;'>Quiz History</div>", unsafe_allow_html=True)
                disp = df[["topic", "score", "total", "accuracy", "created_at"]].copy()
                disp["created_at"] = disp["created_at"].dt.strftime("%m/%d %H:%M")
                disp["result"] = disp.apply(lambda r: f"{int(r['score'])}/{int(r['total'])}", axis=1)
                disp["accuracy"] = disp["accuracy"].apply(lambda x: f"{x:.0f}%")
                disp = disp[["topic", "result", "accuracy", "created_at"]].rename(columns={
                    "topic": "Topic", "result": "Score", "accuracy": "Accuracy", "created_at": "Date"
                })
                st.dataframe(disp, use_container_width=True, hide_index=True, height=200)

    st.markdown("</div>", unsafe_allow_html=True)