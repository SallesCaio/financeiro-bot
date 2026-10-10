"""FinBot - db.py (split de bot.py)."""
import sqlite3
from typing import Optional
from finbot.config import DB_PATH, RENDER_DB_PATH


# ═══════════════════════════════════════════════════════
# DATABASE (SQLite — cache local)
# ═══════════════════════════════════════════════════════
def get_db_path():
    if RENDER_DB_PATH.exists():
        return RENDER_DB_PATH
    return DB_PATH

def init_db():
    path = get_db_path()
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                name TEXT,
                income REAL,
                cards TEXT,
                goal TEXT,
                spreadsheet_id TEXT,
                onboarding_done INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_gasto_date TEXT,
                gastos_count INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS notification_state (
                user_id INTEGER,
                notif_type TEXT,
                last_sent TEXT,
                last_value TEXT,
                PRIMARY KEY (user_id, notif_type)
            );
            CREATE TABLE IF NOT EXISTS metas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT,
                target REAL,
                current REAL DEFAULT 0,
                category TEXT,
                monthly INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS compras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                item TEXT NOT NULL,
                qty TEXT DEFAULT "1",
                categoria TEXT DEFAULT "mercado",
                preco REAL DEFAULT 0,
                comprado INTEGER DEFAULT 0,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS desejos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                item TEXT NOT NULL,
                preco_alvo REAL DEFAULT 0,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS achievements (
                user_id INTEGER,
                key TEXT,
                unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, key)
            );
        """)
        conn.commit()

def get_user(user_id: int) -> Optional[dict]:
    path = get_db_path()
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return None
        cols = [d[0] for d in conn.execute("SELECT * FROM users LIMIT 0").description]
        return dict(zip(cols, row))

def upsert_user(user_id: int, **kwargs):
    path = get_db_path()
    with sqlite3.connect(path) as conn:
        existing = conn.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone()
        if existing:
            sets = ", ".join(f"{k}=?" for k in kwargs)
            conn.execute(f"UPDATE users SET {sets} WHERE user_id=?", (*kwargs.values(), user_id))
        else:
            cols = "user_id," + ",".join(kwargs.keys())
            placeholders = "?," + ",".join("?" for _ in kwargs)
            conn.execute(f"INSERT INTO users ({cols}) VALUES ({placeholders})", (user_id, *kwargs.values()))
        conn.commit()

def get_all_users():
    path = get_db_path()
    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT * FROM users WHERE onboarding_done=1").fetchall()
        cols = [d[0] for d in conn.execute("SELECT * FROM users LIMIT 0").description]
        return [dict(zip(cols, row)) for row in rows]

def unlock_achievement(user_id: int, key: str):
    path = get_db_path()
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT OR IGNORE INTO achievements (user_id, key) VALUES (?, ?)", (user_id, key))
        conn.commit()

def get_achievements(user_id: int) -> list:
    path = get_db_path()
    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT key, unlocked_at FROM achievements WHERE user_id=?", (user_id,)).fetchall()
        return [{"key": r[0], "unlocked_at": r[1]} for r in rows]

def get_metas_from_db(user_id: int) -> list:
    path = get_db_path()
    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT * FROM metas WHERE user_id=? AND active=1", (user_id,)).fetchall()
        cols = [d[0] for d in conn.execute("SELECT * FROM metas LIMIT 0").description]
        return [dict(zip(cols, row)) for row in rows]

def upsert_meta_db(user_id: int, name: str, target: float, category: str, monthly: int = 0):
    path = get_db_path()
    with sqlite3.connect(path) as conn:
        existing = conn.execute(
            "SELECT id FROM metas WHERE user_id=? AND name=? AND active=1", (user_id, name)
        ).fetchone()
        if existing:
            conn.execute("UPDATE metas SET target=?, category=?, monthly=? WHERE id=?",
                         (target, category, monthly, existing[0]))
        else:
            conn.execute(
                "INSERT INTO metas (user_id, name, target, category, monthly) VALUES (?,?,?,?,?)",
                (user_id, name, target, category, monthly)
            )
        conn.commit()

