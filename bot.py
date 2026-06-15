#!/usr/bin/env python3
"""
FinBot — Gestão Financeira via Telegram + Google Sheets
Multi-user, onboarding conversacional, persistência via Master Sheet.
"""
import os, json, sqlite3, logging, re, calendar
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TEMPLATE_SPREADSHEET_ID = os.environ.get("TEMPLATE_SPREADSHEET_ID", "1m-GTVEJcqzzEBoslIJ5OpeSPj1HJnd3U-6m3JCH_uv8")
DB_PATH = Path(__file__).parent / "finbot.db"
RENDER_DB_PATH = Path("/tmp/finbot.db")
MASTER_SHEET_ID = os.environ.get("MASTER_SHEET_ID", "1tTn01DomMhi5mrXW9yhrHzyE2-Uo9A85RlM_GsFTjzc")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("FinBot")

# ═══════════════════════════════════════════════════════
# CONVERSATION STATES
# ═══════════════════════════════════════════════════════
(NAME, INCOME, CARDS, GOAL,
 AMOUNT, DESC, CATEGORY, PAYMENT, CARD_SEL, NECESSARY, OBS,
 IS_SUBSCRIPTION, SUBSCRIPTION_NAME, SUBSCRIPTION_VALOR,
 IS_INSTALMENT, INSTALMENT_QTY,
 FIXO_NOME, FIXO_VALOR, FIXO_DIA, FIXO_CATEGORIA,
 PARC_NOME, PARC_TOTAL, PARC_NPARC, PARC_VALOR_PARC, PARC_CATEGORIA,
 META_NOME, META_TARGET, META_CATEGORIA_META,
 BUSCA_TERMO,
 COMPRAS_CATEG, COMPRAS_ITEM, COMPRAS_QTY) = range(32)

CATEGORIES = {
    "alimentacao": "🍽️ Alimentação", "mercado": "🛒 Mercado",
    "moto": "🏍️ Moto", "transporte": "🚌 Transporte",
    "pessoal": "👤 Pessoal", "saude": "🏥 Saúde",
    "assinaturas": "📱 Assinaturas", "dividas": "💰 Dívidas",
    "delivery": "🛵 Delivery", "educacao": "📚 Educação",
    "moradia": "🏠 Moradia", "lazer": "🎮 Lazer",
    "outros": "📦 Outros"
}

PAYMENT_METHODS = {"pix": "💵 Pix", "credito": "💳 Crédito",
                   "debito": "🏧 Débito", "boleto": "📄 Boleto", "dinheiro": "💶 Dinheiro"}

# ═══════════════════════════════════════════════════════
# GOOGLE AUTH (com cache global para economizar memória)
# ═══════════════════════════════════════════════════════
_sheets_service = None
_drive_service = None
_credentials_instance = None


# ═══════════════════════════════════════════════════════
# HELPER: converte valor da planilha para float
# ═══════════════════════════════════════════════════════
def parse_float(val) -> float:
    """Converte valor BR para float: 1.234,56 → 1234.56, 3000.0 → 3000.0"""
    if val is None:
        return 0.0
    try:
        s = str(val).replace("R$", "").strip()
        # Se tem vírgula: formato BR (1.234,56) — troca última vírgula por ponto, remove pontos
        if "," in s:
            s = s.replace(".", "")       # remove separador milhar
            s = s.replace(",", ".")      # vírgula → ponto decimal
        # Se não tem vírgula: formato EN (3000.0) — só converte direto
        return float(s)
    except (ValueError, TypeError):
        return 0.0

def _get_credentials():
    global _credentials_instance
    if _credentials_instance is not None:
        return _credentials_instance
    """Carrega credenciais Google do token.json ou env vars."""
    token_path = Path(__file__).parent / "google_token.json"
    if not token_path.exists():
        token_path = Path.home() / "AppData" / "Local" / "hermes" / "google_token.json"
    if token_path.exists():
        with open(token_path) as f:
            d = json.load(f)
        _credentials_instance = Credentials(
            token=d["token"], refresh_token=d["refresh_token"],
            token_uri=d["token_uri"], client_id=d["client_id"],
            client_secret=d["client_secret"], scopes=d["scopes"]
        )
        return _credentials_instance
    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    token_uri = os.environ.get("GOOGLE_TOKEN_URI", "https://oauth2.googleapis.com/token")
    scopes = os.environ.get("GOOGLE_SCOPES", "https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/drive.file").split()
    if refresh_token and client_id and client_secret:
        token = os.environ.get("GOOGLE_TOKEN", "")
        _credentials_instance = Credentials(
            token=token, refresh_token=refresh_token,
            token_uri=token_uri, client_id=client_id,
            client_secret=client_secret, scopes=scopes
        )
        return _credentials_instance
    raise RuntimeError("Credenciais Google não encontradas.")

def get_sheets_service():
    global _sheets_service
    if _sheets_service is None:
        _sheets_service = build("sheets", "v4", credentials=_get_credentials())
    return _sheets_service

def get_drive_service():
    global _drive_service
    if _drive_service is None:
        _drive_service = build("drive", "v3", credentials=_get_credentials())
    return _drive_service

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

# ═══════════════════════════════════════════════════════
# GOOGLE SHEETS — Master Sheet (persistência)
# ═══════════════════════════════════════════════════════
MASTER_USERS_RANGE = "USERS!A:H"

def ensure_master_sheet():
    svc = get_sheets_service()
    try:
        meta = svc.spreadsheets().get(spreadsheetId=MASTER_SHEET_ID).execute()
        sheets = [s["properties"]["title"] for s in meta.get("sheets", [])]
        if "USERS" not in sheets:
            svc.spreadsheets().batchUpdate(spreadsheetId=MASTER_SHEET_ID, body={
                "requests": [{"addSheet": {"properties": {"title": "USERS"}}}]
            }).execute()
            svc.spreadsheets().values().update(
                spreadsheetId=MASTER_SHEET_ID, range=MASTER_USERS_RANGE,
                valueInputOption="USER_ENTERED",
                body={"values": [["user_id","username","first_name","name","income","cards","goal","spreadsheet_id"]]}
            ).execute()
            logger.info("Master Sheet USERS created")
    except Exception as e:
        logger.error(f"Erro master sheet: {e}")

def sync_users_from_master():
    svc = get_sheets_service()
    try:
        result = svc.spreadsheets().values().get(
            spreadsheetId=MASTER_SHEET_ID, range=MASTER_USERS_RANGE
        ).execute()
        rows = result.get("values", [])
        if len(rows) <= 1:
            return 0
        count = 0
        for row in rows[1:]:
            if len(row) >= 8 and row[0]:
                try:
                    uid = int(row[0])
                    upsert_user(uid,
                        username=row[1] if len(row)>1 else "",
                        first_name=row[2] if len(row)>2 else "",
                        name=row[3] if len(row)>3 else "",
                        income=parse_float(row[4]) if row[4] else 0,
                        cards=row[5] if len(row)>5 else "",
                        goal=row[6] if len(row)>6 else "",
                        spreadsheet_id=row[7] if len(row)>7 else "",
                        onboarding_done=1)
                    count += 1
                except (ValueError, IndexError):
                    continue
        logger.info(f"Synced {count} users from master sheet")
        return count
    except Exception as e:
        logger.error(f"Erro sync master: {e}")
        return 0

def save_user_to_master(user_id: int, username: str, first_name: str, name: str,
                        income: float, cards: str, goal: str, spreadsheet_id: str):
    ensure_master_sheet()
    svc = get_sheets_service()
    try:
        result = svc.spreadsheets().values().get(
            spreadsheetId=MASTER_SHEET_ID, range=MASTER_USERS_RANGE
        ).execute()
        rows = result.get("values", [])
        user_str = str(user_id)
        found_row = None
        for i, row in enumerate(rows):
            if row and row[0] == user_str:
                found_row = i + 1
                break
        new_row = [user_str, username, first_name, name, str(income), cards, goal, spreadsheet_id]
        if found_row:
            svc.spreadsheets().values().update(
                spreadsheetId=MASTER_SHEET_ID, range=f"USERS!A{found_row}:H{found_row}",
                valueInputOption="USER_ENTERED", body={"values": [new_row]}
            ).execute()
        else:
            svc.spreadsheets().values().append(
                spreadsheetId=MASTER_SHEET_ID, range=MASTER_USERS_RANGE,
                valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
                body={"values": [new_row]}
            ).execute()
    except Exception as e:
        logger.error(f"Erro save user to master: {e}")

# ═══════════════════════════════════════════════════════
# GOOGLE SHEETS — Operações na planilha do usuário
# ═══════════════════════════════════════════════════════
def create_user_spreadsheet(user_name: str) -> str:
    drive_svc = get_drive_service()
    copy = drive_svc.files().copy(
        fileId=TEMPLATE_SPREADSHEET_ID, body={"name": f"FinBot - {user_name}"}
    ).execute()
    return copy["id"]

def get_or_create_month_sheet(spreadsheet_id: str, year_month: str) -> str:
    svc = get_sheets_service()
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for s in meta["sheets"]:
        if s["properties"]["title"] == year_month:
            return year_month
    svc.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
        "requests": [{"addSheet": {"properties": {"title": year_month}}}]
    }).execute()
    headers = [["DATA","DESCRIÇÃO","CATEGORIA","SUBCATEGORIA","PAGAMENTO","VALOR","CARTÃO","NECESSÁRIO?","TIPO","OBS"]]
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"{year_month}!A1:J1",
        valueInputOption="USER_ENTERED", body={"values": headers}
    ).execute()
    return year_month

def append_gasto(spreadsheet_id: str, year_month: str, row: list):
    svc = get_sheets_service()
    svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id, range=f"{year_month}!A:J",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": [row]}
    ).execute()

def read_range(spreadsheet_id: str, range_str: str):
    svc = get_sheets_service()
    r = svc.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_str).execute()
    return r.get("values", [])

# ── FATURAS ──
# Estrutura: CARTÃO | REF_MÊS | TOTAL | VENCIMENTO | PAGO | VALOR_PAGO | DATA_PAGAMENTO | OBS
# Vencimento padrão: dia 08 de cada mês
# REF_MÊS: YYYY-MM da fatura (mês de referência, não mês de pagamento)

VENCIMENTO_DIA = 8  # Dia de vencimento de todas as faturas

def _calc_vencimento(ref_month: str) -> str:
    """Calcula data de vencimento: dia 08 do mês seguinte ao ref_month."""
    y, m = map(int, ref_month.split("-"))
    if m == 12:
        next_m, next_y = 1, y + 1
    else:
        next_m, next_y = m + 1, y
    return f"{VENCIMENTO_DIA:02d}/{next_m:02d}/{next_y}"

def _calc_prox_ref_month(ref_month: str) -> str:
    """Calcula o próximo mês de referência (para parcelamentos)."""
    y, m = map(int, ref_month.split("-"))
    if m == 12:
        return f"{y + 1}-01"
    return f"{y}-{m + 1:02d}"

def ensure_fatura_sheet(spreadsheet_id: str):
    """Cria aba FATURAS se não existir. Usa cache."""
    if _sheet_exists(spreadsheet_id, "FATURAS"):
        return
    svc = get_sheets_service()
    svc.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
        "requests": [{"addSheet": {"properties": {"title": "FATURAS", "gridProperties": {"rowCount": 100, "columnCount": 8}}}}]
    }).execute()
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range="FATURAS!A1:H1",
        valueInputOption="USER_ENTERED",
        body={"values": [["CARTÃO","REF_MÊS","TOTAL","VENCIMENTO","PAGO","VALOR_PAGO","DATA_PAGAMENTO","OBS"]]}
    ).execute()
    _sheets_cache[f"{spreadsheet_id}:FATURAS"] = True

def get_fatura_row(spreadsheet_id: str, cartao: str, ref_month: str):
    """Busca fatura por cartão + mês de referência."""
    svc = get_sheets_service()
    ensure_fatura_sheet(spreadsheet_id)
    result = svc.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range="FATURAS!A1:H50").execute()
    values = result.get("values", [])
    if not values:
        return None
    for idx, row in enumerate(values[1:], start=2):
        if len(row) >= 2 and row[0] == cartao and row[1] == ref_month:
            return idx, row
    return None

def get_or_create_fatura(spreadsheet_id: str, cartao: str, ref_month: str):
    """Busca fatura ou cria nova se não existir."""
    existing = get_fatura_row(spreadsheet_id, cartao, ref_month)
    if existing:
        return existing
    # Criar nova fatura
    svc = get_sheets_service()
    ensure_fatura_sheet(spreadsheet_id)
    venc = _calc_vencimento(ref_month)
    new_row = [cartao, ref_month, "0.00", venc, "NAO", "0.00", "", ""]
    svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id, range="FATURAS!A1:H50",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": [new_row]}
    ).execute()
    # Retornar a linha criada
    return get_fatura_row(spreadsheet_id, cartao, ref_month)

def update_fatura_total(spreadsheet_id: str, cartao: str, ref_month: str, valor_adicional: float):
    """Soma valor ao TOTAL da fatura. Criar fatura se não existir."""
    existing = get_or_create_fatura(spreadsheet_id, cartao, ref_month)
    if not existing:
        return
    row_idx, row_data = existing
    cur_total = parse_float(row_data[2]) if len(row_data) > 2 and row_data[2] else 0.0
    novo_total = cur_total + valor_adicional
    svc = get_sheets_service()
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"FATURAS!C{row_idx}",
        valueInputOption="USER_ENTERED", body={"values": [[f"{novo_total:.2f}"]]}
    ).execute()

def update_fatura_cell(spreadsheet_id: str, row_idx: int, col_letter: str, value):
    svc = get_sheets_service()
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"FATURAS!{col_letter}{row_idx}",
        valueInputOption="USER_ENTERED", body={"values": [[value]]}
    ).execute()

def append_fatura_row(spreadsheet_id: str, row: list):
    svc = get_sheets_service()
    ensure_fatura_sheet(spreadsheet_id)
    svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id, range="FATURAS!A1:H50",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": [row]}
    ).execute()

# ── FIXOS ──
def ensure_fixos_sheet(spreadsheet_id: str):
    """Cria aba FIXOS se não existir. NÃO recria se já existir."""
    svc = get_sheets_service()
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    if any(s["properties"]["title"] == "FIXOS" for s in meta.get("sheets", [])):
        return  # Já existe
    svc.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
        "requests": [{"addSheet": {"properties": {"title": "FIXOS", "gridProperties": {"rowCount": 500, "columnCount": 6}}}}]
    }).execute()
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range="FIXOS!A1:F1",
        valueInputOption="USER_ENTERED",
        body={"values": [["NOME","VALOR","DIA_VENCIMENTO","CATEGORIA","ATIVO","OBS"]]}
    ).execute()

def read_fixos(spreadsheet_id: str) -> list:
    svc = get_sheets_service()
    ensure_fixos_sheet(spreadsheet_id)
    result = svc.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range="FIXOS!A1:F50").execute()
    rows = result.get("values", [])
    if len(rows) <= 1:
        return []
    items = []
    for row in rows[1:]:
        if len(row) >= 1 and row[0]:
            items.append({
                "nome": row[0], "valor": parse_float(row[1]) if row[1] else 0,
                "dia": row[2] if len(row)>2 else "", "categoria": row[3] if len(row)>3 else "outros",
                "ativo": row[4].upper()=="SIM" if len(row)>4 else True,
                "obs": row[5] if len(row)>5 else ""
            })
    return items
    return items

def append_fixo(spreadsheet_id: str, row: list):
    svc = get_sheets_service()
    ensure_fixos_sheet(spreadsheet_id)
    svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id, range="FIXOS!A1:F50",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": [row]}
    ).execute()

# ── PARCELAMENTOS ──
# Cache global de abas já verificadas (evita chamadas API repetidas)
_sheets_cache = {}

def _sheet_exists(spreadsheet_id, sheet_name):
    """Verifica se aba existe usando cache."""
    key = f"{spreadsheet_id}:{sheet_name}"
    if key in _sheets_cache:
        return _sheets_cache[key]
    svc = get_sheets_service()
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    exists = any(s["properties"]["title"] == sheet_name for s in meta.get("sheets", []))
    _sheets_cache[key] = exists
    return exists

def ensure_parcelas_sheet(spreadsheet_id: str):
    """Cria aba PARCELAMENTOS se não existir. Usa cache."""
    if _sheet_exists(spreadsheet_id, "PARCELAMENTOS"):
        return
    svc = get_sheets_service()
    svc.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
        "requests": [{"addSheet": {"properties": {"title": "PARCELAMENTOS", "gridProperties": {"rowCount": 100, "columnCount": 8}}}}]
    }).execute()
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range="PARCELAMENTOS!A1:H1",
        valueInputOption="USER_ENTERED",
        body={"values": [["COD","DESCRICAO","VALOR_PARCELA","TOTAL_PARCELAS","PAGAS","RESTANTES","VALOR_PAGO","VALOR_RESTANTE"]]}
    ).execute()
    _sheets_cache[f"{spreadsheet_id}:PARCELAMENTOS"] = True

def ensure_fixos_sheet(spreadsheet_id: str):
    """Cria aba FIXOS se não existir. Usa cache."""
    if _sheet_exists(spreadsheet_id, "FIXOS"):
        return
    svc = get_sheets_service()
    svc.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
        "requests": [{"addSheet": {"properties": {"title": "FIXOS", "gridProperties": {"rowCount": 100, "columnCount": 6}}}}]
    }).execute()
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range="FIXOS!A1:F1",
        valueInputOption="USER_ENTERED",
        body={"values": [["NOME","VALOR","DIA_VENCIMENTO","CATEGORIA","ATIVO","OBS"]]}
    ).execute()
    _sheets_cache[f"{spreadsheet_id}:FIXOS"] = True

def ensure_fatura_sheet(spreadsheet_id: str):
    """Cria aba FATURAS se não existir. Usa cache."""
    if _sheet_exists(spreadsheet_id, "FATURAS"):
        return
    svc = get_sheets_service()
    svc.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
        "requests": [{"addSheet": {"properties": {"title": "FATURAS", "gridProperties": {"rowCount": 100, "columnCount": 8}}}}]
    }).execute()
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range="FATURAS!A1:H1",
        valueInputOption="USER_ENTERED",
        body={"values": [["CARTÃO","REF_MÊS","TOTAL","VENCIMENTO","PAGO","VALOR_PAGO","DATA_PAGAMENTO","OBS"]]}
    ).execute()
    _sheets_cache[f"{spreadsheet_id}:FATURAS"] = True

def read_parcelas(spreadsheet_id: str) -> list:
    svc = get_sheets_service()
    ensure_parcelas_sheet(spreadsheet_id)
    result = svc.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range="PARCELAMENTOS!A1:H50").execute()
    rows = result.get("values", [])
    if len(rows) <= 1:
        return []
    items = []
    for row in rows[1:]:
        if len(row) >= 1 and row[0]:
            cod = row[0]
            descricao = row[1] if len(row) > 1 else ""
            valor_parcela = parse_float(row[2]) if len(row) > 2 and row[2] else 0
            total_parcelas = int(parse_float(row[3])) if len(row) > 3 and row[3] else 0
            pagas = int(parse_float(row[4])) if len(row) > 4 and row[4] else 0
            restantes = int(parse_float(row[5])) if len(row) > 5 and row[5] else (total_parcelas - pagas)
            valor_pago = parse_float(row[6]) if len(row) > 6 and row[6] else (valor_parcela * pagas)
            valor_restante = parse_float(row[7]) if len(row) > 7 and row[7] else (valor_parcela * restantes)
            items.append({
                "cod": cod, "descricao": descricao, "valor_parcela": valor_parcela,
                "total_parcelas": total_parcelas, "pagas": pagas, "restantes": restantes,
                "valor_pago": valor_pago, "valor_restante": valor_restante
            })
    return items

def append_parcela(spreadsheet_id: str, row: list):
    svc = get_sheets_service()
    ensure_parcelas_sheet(spreadsheet_id)
    svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id, range="PARCELAMENTOS!A1:H50",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": [row]}
    ).execute()

def update_parcela_cell(spreadsheet_id: str, row_idx: int, col: str, value):
    svc = get_sheets_service()
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"PARCELAMENTOS!{col}{row_idx}",
        valueInputOption="USER_ENTERED", body={"values": [[value]]}
    ).execute()

# ── COMPRAS (Google Sheets) ──
def ensure_compras_sheet(spreadsheet_id: str):
    """Cria aba COMPRAS no Sheets para persistência."""
    svc = get_sheets_service()
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheets = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if "COMPRAS" in sheets:
        return
    svc.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
        "requests": [{"addSheet": {"properties": {"title": "COMPRAS", "gridProperties": {"rowCount": 500, "columnCount": 7}}}}]
    }).execute()
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range="COMPRAS!A1:G1",
        valueInputOption="USER_ENTERED",
        body={"values": [["COD","ITEM","QTY","CATEGORIA","PRECO","COMPRADO","DATA"]]}
    ).execute()

def read_compras(spreadsheet_id: str, apenas_pendentes=True) -> list:
    svc = get_sheets_service()
    ensure_compras_sheet(spreadsheet_id)
    result = svc.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range="COMPRAS!A:G").execute()
    rows = result.get("values", [])
    if len(rows) <= 1:
        return []
    items = []
    for row in rows[1:]:
        if not row or not row[0]:
            continue
        comprado = row[5].upper() == "SIM" if len(row) > 5 else False
        if apenas_pendentes and comprado:
            continue
        items.append({
            "cod": row[0], "item": row[1] if len(row) > 1 else "",
            "qty": row[2] if len(row) > 2 else "1",
            "categoria": row[3] if len(row) > 3 else "outros",
            "preco": parse_float(row[4]) if len(row) > 4 and row[4] else 0,
            "comprado": comprado,
            "data": row[6] if len(row) > 6 else ""
        })
    return items

def append_compra(spreadsheet_id: str, row: list):
    svc = get_sheets_service()
    ensure_compras_sheet(spreadsheet_id)
    svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id, range="COMPRAS!A:G",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": [row]}
    ).execute()

def update_compra_cell(spreadsheet_id: str, row_idx: int, col: str, value):
    svc = get_sheets_service()
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"COMPRAS!{col}{row_idx}",
        valueInputOption="USER_ENTERED", body={"values": [[value]]}
    ).execute()
def ensure_metas_sheet(spreadsheet_id: str):
    svc = get_sheets_service()
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    if any(s["properties"]["title"] == "METAS" for s in meta.get("sheets", [])):
        return
    svc.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
        "requests": [{"addSheet": {"properties": {"title": "METAS", "gridProperties": {"rowCount": 500, "columnCount": 6}}}}]
    }).execute()
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range="METAS!A1:F1",
        valueInputOption="USER_ENTERED",
        body={"values": [["NOME","META","ATUAL","CATEGORIA","MENSAL","ATIVO"]]}
    ).execute()

def read_metas(spreadsheet_id: str) -> list:
    svc = get_sheets_service()
    ensure_metas_sheet(spreadsheet_id)
    result = svc.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range="METAS!A:F").execute()
    rows = result.get("values", [])
    if len(rows) <= 1:
        return []
    items = []
    for row in rows[1:]:
        if len(row) >= 2 and row[0]:
            items.append({
                "nome": row[0], "meta": parse_float(row[1]) if row[1] else 0,
                "atual": parse_float(row[2]) if len(row)>2 and row[2] else 0,
                "categoria": row[3] if len(row)>3 else "",
                "mensal": row[4].upper()=="SIM" if len(row)>4 else False,
                "ativo": row[5].upper()=="SIM" if len(row)>5 else True
            })
    return items

def append_meta(spreadsheet_id: str, row: list):
    svc = get_sheets_service()
    ensure_metas_sheet(spreadsheet_id)
    svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id, range="METAS!A:F",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": [row]}
    ).execute()

# ═══════════════════════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════════════════════
def category_keyboard():
    buttons = []
    row = []
    for key, label in CATEGORIES.items():
        row.append(InlineKeyboardButton(label, callback_data=f"cat_{key}"))
        if len(row) == 3:
            buttons.append(row); row = []
    if row: buttons.append(row)
    return InlineKeyboardMarkup(buttons)

def payment_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(v, callback_data=f"pay_{k}")] for k, v in PAYMENT_METHODS.items()]
    )

def yes_no_keyboard(prefix: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sim", callback_data=f"{prefix}_sim"),
         InlineKeyboardButton("❌ Não", callback_data=f"{prefix}_nao")]
    ])

def main_menu_keyboard():
    """Menu principal com 5 categorias."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💸 Lançamentos", callback_data="menu_financas")],
        [InlineKeyboardButton("📊 Relatórios", callback_data="menu_relatorios")],
        [InlineKeyboardButton("🛒 Compras", callback_data="menu_compras")],
        [InlineKeyboardButton("👤 Perfil", callback_data="menu_perfil")],
        [InlineKeyboardButton("💵 Receita", callback_data="menu_receita")],
    ])

def financas_submenu_keyboard():
    """Sub-menu de Finanças."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💸 Lançamentos", callback_data="menu_lancamentos"),
         InlineKeyboardButton("📅 Parcelas", callback_data="menu_parcelas")],
        [InlineKeyboardButton("📱 Assinaturas", callback_data="menu_assinaturas"),
         InlineKeyboardButton("🔙 Voltar", callback_data="menu_voltar")],
    ])

def relatorios_submenu_keyboard():
    """Sub-menu de Relatórios."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Resumo", callback_data="menu_resumo"),
         InlineKeyboardButton("📈 Insights", callback_data="menu_insights")],
        [InlineKeyboardButton("📄 Relatório Completo", callback_data="menu_relatorio")],
        [InlineKeyboardButton("🔙 Voltar", callback_data="menu_voltar")],
    ])

# ═══════════════════════════════════════════════════════
# UTILS
# ═══════════════════════════════════════════════════════
def ensure_user(update: Update):
    user_id = update.effective_user.id
    user = get_user(user_id)
    return user and user.get("onboarding_done")



# ═══════════════════════════════════════════════════════
# ONBOARDING
# ═══════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)

    if user and user.get("onboarding_done"):
        await update.message.reply_text(
            f"👋 Olá, *{user['name']}*!\n"
            f"💰 Renda: R$ {user['income']:,.2f} | 🎯 {user['goal']}\n"
            f"📊 Use os botões abaixo para gerenciar seus gastos.\n\n"
            "O que deseja fazer?",
            parse_mode="Markdown", reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    context.user_data["onboarding"] = {}
    await update.message.reply_text(
        "🏦 *Bem-vindo ao FinBot!*\n\n"
        "Vou configurar seu perfil financeiro. É rapidinho!\n\n"
        "1️⃣ *Qual seu nome?*",
        parse_mode="Markdown"
    )
    return NAME

async def onboarding_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["onboarding"]["name"] = update.message.text
    await update.message.reply_text("2️⃣ *Qual sua renda mensal?*\nEx: 3000 ou 4500,90", parse_mode="Markdown")
    return INCOME

async def onboarding_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.replace(",", ".").replace("R$", "").strip()
    try:
        income = float(txt)
    except ValueError:
        await update.message.reply_text("❌ Valor inválido. Digite apenas números (ex: 3000)")
        return INCOME
    if income <= 0:
        await update.message.reply_text("❌ Renda deve ser maior que zero. Tente novamente.")
        return INCOME
    context.user_data["onboarding"]["income"] = income
    await update.message.reply_text(
        "3️⃣ *Quais cartões você usa?*\n"
        "Separe por vírgula (ex: Nubank, Itaú)\n"
        "Ou digite *nenhum*",
        parse_mode="Markdown"
    )
    return CARDS

async def onboarding_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["onboarding"]["cards"] = update.message.text
    await update.message.reply_text(
        "4️⃣ *Qual seu principal objetivo financeiro?*\n\n"
        "Ex: Quitar dívidas / Economizar / Sair do vermelho / Controlar gastos",
        parse_mode="Markdown"
    )
    return GOAL

async def onboarding_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data["onboarding"]
    data["goal"] = update.message.text
    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    first_name = update.effective_user.first_name or ""

    try:
        existing_user = get_user(user_id)

        if existing_user and existing_user.get("spreadsheet_id"):
            spreadsheet_id = existing_user["spreadsheet_id"]
            logger.info(f"Reutilizando planilha {spreadsheet_id} para {data['name']}")
        else:
            logger.info(f"Criando nova planilha para {data['name']}")
            spreadsheet_id = create_user_spreadsheet(data["name"])
            logger.info(f"Planilha criada: {spreadsheet_id}")

        upsert_user(user_id,
            username=username, first_name=first_name,
            name=data["name"], income=data["income"],
            cards=data["cards"], goal=data["goal"],
            spreadsheet_id=spreadsheet_id, onboarding_done=1)

        # Salvar na Master Sheet (persistência)
        try:
            save_user_to_master(user_id, username, first_name, data["name"],
                                data["income"], data["cards"], data["goal"], spreadsheet_id)
        except Exception as e:
            logger.warning(f"Não foi possível salvar na master: {e}")

        ym = datetime.now().strftime("%Y-%m")
        get_or_create_month_sheet(spreadsheet_id, ym)

        await update.message.reply_text(
            f"✅ *Perfil criado, {data['name']}!*\n\n"
            f"💰 Renda mensal: R$ {data['income']:,.2f}\n"
            f"💳 Cartões: {data['cards']}\n"
            f"🎯 Objetivo: {data['goal']}\n\n"
            f"📊 Sua planilha:\nhttps://docs.google.com/spreadsheets/d/{spreadsheet_id}\n\n"
            "Use */gasto* para registrar despesas ou */g 50 mercado alimentação pix* para modo rápido!\n"
            "Comandos: */gasto*, */g*, */fixo*, */parcela*, */compras*, */busca*, */relatorio*",
            parse_mode="Markdown", reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Erro onboarding para user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ Erro ao finalizar cadastro: {str(e)[:200]}\nTente /start novamente."
        )
        return ConversationHandler.END

# ═══════════════════════════════════════════════════════
# GASTO CONVERSACIONAL
# ═══════════════════════════════════════════════════════
async def gasto_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro para configurar seu perfil.")
        return ConversationHandler.END
    context.user_data["gasto"] = {}
    await update.message.reply_text("💸 *Quanto gastou?*\nEx: 50 ou 149,90", parse_mode="Markdown")
    return AMOUNT

async def gasto_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.replace(",", ".").replace("R$", "").strip()
    try:
        amount = float(txt)
        if amount <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Valor inválido. Digite um número positivo (ex: 50)")
        return AMOUNT
    context.user_data["gasto"]["amount"] = amount
    await update.message.reply_text("📝 *O que comprou?*\nEx: Mercado, Uber, Netflix...", parse_mode="Markdown")
    return DESC

async def gasto_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["gasto"]["desc"] = update.message.text
    await update.message.reply_text("📂 *Qual a categoria?*", parse_mode="Markdown", reply_markup=category_keyboard())
    return CATEGORY

async def gasto_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_key = query.data.replace("cat_", "")
    context.user_data["gasto"]["category"] = cat_key
    await query.edit_message_text(
        f"📂 Categoria: *{CATEGORIES[cat_key]}*\n\n💳 *Forma de pagamento?*",
        parse_mode="Markdown", reply_markup=payment_keyboard()
    )
    return PAYMENT

async def gasto_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pay_key = query.data.replace("pay_", "")
    context.user_data["gasto"]["payment"] = pay_key
    if pay_key == "credito":
        user = get_user(update.effective_user.id)
        cards_str = user.get("cards", "") if user else ""
        if cards_str and cards_str.lower() != "nenhum":
            cards = [c.strip() for c in cards_str.split(",")]
            buttons = [[InlineKeyboardButton(c, callback_data=f"card_{c}")] for c in cards]
            buttons.append([InlineKeyboardButton("➕ Outro", callback_data="card_outro")])
            await query.edit_message_text(
                "💳 Pagamento: *Crédito*\n\n🏦 *Qual cartão?*",
                parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons)
            )
            return CARD_SEL
    context.user_data["gasto"]["card"] = ""
    await query.edit_message_text(
        f"💳 Pagamento: *{PAYMENT_METHODS[pay_key]}*\n\n⭐ *Isso era necessário?*",
        parse_mode="Markdown", reply_markup=yes_no_keyboard("nec")
    )
    return NECESSARY

async def gasto_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    card = query.data.replace("card_", "")
    if card == "outro":
        await query.edit_message_text("🏦 Digite o nome do cartão:")
        context.user_data["gasto"]["awaiting_card"] = True
        return CARD_SEL
    context.user_data["gasto"]["card"] = card
    await query.edit_message_text(
        f"🏦 Cartão: *{card}*\n\n⭐ *Isso era necessário?*",
        parse_mode="Markdown", reply_markup=yes_no_keyboard("nec")
    )
    return NECESSARY

async def gasto_card_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["gasto"]["card"] = update.message.text
    await update.message.reply_text(
        f"🏦 Cartão: *{update.message.text}*\n\n⭐ *Isso era necessário?*",
        parse_mode="Markdown", reply_markup=yes_no_keyboard("nec")
    )
    return NECESSARY

async def gasto_necessary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    nec = "SIM" if query.data == "nec_sim" else "NÃO"
    context.user_data["gasto"]["necessary"] = nec
    await query.edit_message_text(
        f"⭐ Necessário: *{nec}*\n\n🔄 *É uma assinatura/mensalidade recorrente?*",
        parse_mode="Markdown",
        reply_markup=yes_no_keyboard("sub")
    )
    return IS_SUBSCRIPTION

async def gasto_is_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    is_sub = query.data == "sub_sim"
    context.user_data["gasto"]["is_subscription"] = is_sub
    if is_sub:
        await query.edit_message_text(
            "📌 *Nome da assinatura:*\nEx: Netflix, Spotify, Academia, iCloud...",
            parse_mode="Markdown"
        )
        return SUBSCRIPTION_NAME
    context.user_data["gasto"]["subscription_name"] = ""
    context.user_data["gasto"]["subscription_valor"] = 0
    return await _ask_instalment(update, context)

async def gasto_subscription_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["gasto"]["subscription_name"] = update.message.text
    await update.message.reply_text(
        f"💰 *Valor mensal da assinatura:*\nEx: 55,90",
        parse_mode="Markdown"
    )
    return SUBSCRIPTION_VALOR

async def gasto_subscription_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.replace(",", ".").replace("R$", "").strip()
    try:
        v = float(txt)
    except ValueError:
        await update.message.reply_text("❌ Valor inválido. Ex: 55,90")
        return SUBSCRIPTION_VALOR
    context.user_data["gasto"]["subscription_valor"] = v
    return await _ask_instalment(update, context)

async def _ask_instalment(update, context):
    """Ask if credit purchase is instalment."""
    g = context.user_data["gasto"]
    if g["payment"] == "credito":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 À vista", callback_data="inst_avista"),
             InlineKeyboardButton("📅 Parcelado", callback_data="inst_parcelado")]
        ])
        msg = update.message if update.message else update.callback_query.message
        await msg.reply_text(
            "📅 *Compra parcelada ou à vista?*",
            parse_mode="Markdown", reply_markup=keyboard
        )
        return IS_INSTALMENT
    context.user_data["gasto"]["instalment_qty"] = 1
    return await _go_to_obs(update, context)

async def gasto_is_instalment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    is_inst = query.data == "inst_parcelado"
    if is_inst:
        await query.edit_message_text(
            "🔢 *Em quantas vezes?*\nEx: 3, 6, 12, 24",
            parse_mode="Markdown"
        )
        return INSTALMENT_QTY
    context.user_data["gasto"]["instalment_qty"] = 1
    return await _go_to_obs(update, context)

async def gasto_instalment_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text)
        if qty < 1: raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Número inválido. Ex: 3, 6, 12")
        return INSTALMENT_QTY
    context.user_data["gasto"]["instalment_qty"] = qty
    return await _go_to_obs(update, context)

async def _go_to_obs(update, context):
    """Go to OBS state."""
    msg = update.message if update.message else update.callback_query.message
    await msg.reply_text(
        "📝 *Alguma observação?*\nDigite /pular para deixar em branco",
        parse_mode="Markdown"
    )
    return OBS

async def gasto_obs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    obs = update.message.text if update.message.text != "/pular" else ""
    await salvar_gasto(update, context, obs)
    return ConversationHandler.END

async def gasto_obs_pular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await salvar_gasto(update, context, "")
    return ConversationHandler.END

async def gasto_quick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Modo rápido: /g 50 mercado alimentacao pix nubank"""
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro.")
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "❌ */g <valor> <descrição> <categoria> [pagamento] [cartão]*\n"
            "Ex: /g 50 mercado alimentação pix nubank",
            parse_mode="Markdown"
        )
        return
    try:
        amount = float(args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ Valor inválido.")
        return
    desc = args[1]; cat = args[2].lower()
    pay = args[3].lower() if len(args) > 3 else "pix"
    card = args[4] if len(args) > 4 else ""
    if cat not in CATEGORIES:
        await update.message.reply_text(f"⚠️ Categoria inválida. Opções: {', '.join(CATEGORIES.keys())}")
        return
    if pay not in PAYMENT_METHODS:
        await update.message.reply_text(f"⚠️ Pagamento inválido. Opções: {', '.join(PAYMENT_METHODS.keys())}")
        return
    context.user_data["gasto"] = {
        "amount": amount, "desc": desc, "category": cat,
        "payment": pay, "card": card, "necessary": "NÃO"
    }
    await salvar_gasto(update, context, "")

async def salvar_gasto(update: Update, context, obs: str):
    try:
        g = context.user_data["gasto"]
        user_id = update.effective_user.id
        user = get_user(user_id)
        if not user:
            await update.message.reply_text("❌ User não encontrado. Use /start.")
            return
        sid = user.get("spreadsheet_id", "")
        if not sid:
            await update.message.reply_text("❌ Planilha não configurada. Use /start.")
            return
        ym = datetime.now().strftime("%Y-%m")
        get_or_create_month_sheet(sid, ym)

        row = [
            datetime.now().strftime("%d/%m/%Y"),
            g["desc"], CATEGORIES.get(g["category"], g["category"]).upper(), "",
            PAYMENT_METHODS.get(g["payment"], g["payment"]).upper(),
            g["amount"], g.get("card", "").upper(),
            g.get("necessary", "NÃO"), "CONSUMO", obs
        ]
        append_gasto(sid, ym, row)

        # ── Atualizar Fatura (apenas crédito) ──
        if g["payment"] == "credito":
            cartao = g.get("card", "").upper()
            if cartao:
                qty = g.get("instalment_qty", 1)
                if qty > 1:
                    valor_parcela = round(g["amount"] / qty, 2)
                    ref_mes = ym
                    update_fatura_total(sid, cartao, ref_mes, valor_parcela)
                    for i in range(1, qty):
                        ref_mes = _calc_prox_ref_month(ref_mes)
                        update_fatura_total(sid, cartao, ref_mes, valor_parcela)
                else:
                    update_fatura_total(sid, cartao, ym, g["amount"])

        # ── Parcelamento ──
        qty = g.get("instalment_qty", 1)
        if qty > 1:
            valor_parcela = round(g["amount"] / qty, 2)
            cod = datetime.now().strftime("%Y%m%d%H%M%S")
            ensure_parcelas_sheet(sid)
            append_parcela(sid, [cod, g["desc"], valor_parcela, qty, 0, qty, 0.0, round(valor_parcela * qty, 2)])

        # ── Fixos (Assinaturas) ──
        if g.get("is_subscription"):
            ensure_fixos_sheet(sid)
            sub_name = g.get("subscription_name", g["desc"])
            sub_valor = g.get("subscription_valor", g["amount"])
            append_fixo(sid, [sub_name, sub_valor, str(datetime.now().day), g["category"], "SIM", ""])

        # ── Contador ──
        today = datetime.now().strftime("%Y-%m-%d")
        last = user.get("last_gasto_date", "")
        gastos_count = (user.get("gastos_count", 0) or 0) + 1
        upsert_user(user_id, last_gasto_date=today, gastos_count=gastos_count)

        # ── Confirmação ──
        msg_parts = [
            f"✅ *R$ {g['amount']:,.2f}* — {g['desc']}",
            f"📂 {CATEGORIES.get(g['category'], g['category'])}",
            f"💳 {PAYMENT_METHODS.get(g['payment'], g['payment'])}",
        ]
        if qty > 1:
            msg_parts.append(f"📅 Parcelado em {qty}x de R$ {round(g['amount']/qty, 2):,.2f}")
        if obs:
            msg_parts.append(f"📝 {obs}")

        await update.message.reply_text("\n".join(msg_parts), parse_mode="Markdown")
        await update.message.reply_text("👇 O que deseja fazer agora?", reply_markup=main_menu_keyboard())

    except Exception as e:
        logger.error(f"Erro salvar_gasto: {e}", exc_info=True)
        try:
            await update.message.reply_text("⚠️ Ocorreu um erro. Tente novamente ou use /start.")
        except Exception:
            pass

# ═══════════════════════════════════════════════════════
# COMANDOS /resumo, /limite, /novomes, /fatura, /pagar_fatura
# ═══════════════════════════════════════════════════════
async def cmd_resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro."); return
    user = get_user(update.effective_user.id)
    sid = user["spreadsheet_id"]; ym = datetime.now().strftime("%Y-%m")
    try:
        data = read_range(sid, f"{ym}!A1:J200")
    except Exception as e:
        logger.error(f"Erro resumo: {e}")
        await update.message.reply_text("❌ Erro ao ler planilha"); return
    if len(data) <= 1:
        await update.message.reply_text("📊 Nenhum gasto registrado esse mês."); return
    total = sum(parse_float(r[5]) for r in data[1:] if len(r) > 5 and r[5])
    cats = {}
    for r in data[1:]:
        if len(r) > 5 and r[2] and r[5]:
            cats[r[2]] = cats.get(r[2], 0) + parse_float(r[5])
    lines = [f"📊 *Resumo {datetime.now().strftime('%B/%Y')}*", f"💰 Total: R$ {total:,.2f}",
             f"📂 {len(data)-1} gastos", ""]
    for cat, val in sorted(cats.items(), key=lambda x: -x[1]):
        bar = "█" * int(val/total*15) + "░" * (15 - int(val/total*15)) if total > 0 else "░"*15
        lines.append(f"{bar} {cat[:20]}: R$ {val:,.2f}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    await update.message.reply_text(f"📊 Planilha: https://docs.google.com/spreadsheets/d/{sid}", parse_mode="Markdown")
    await update.message.reply_text("👇", reply_markup=main_menu_keyboard())

async def cmd_limite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_user(update): return
    user = get_user(update.effective_user.id)
    income = user["income"]; sid = user["spreadsheet_id"]
    ym = datetime.now().strftime("%Y-%m")
    try:
        data = read_range(sid, f"{ym}!A1:J200")
        total = sum(parse_float(r[5]) for r in data[1:] if len(r) > 5 and r[5]) if len(data) > 1 else 0
    except:
        await update.message.reply_text("❌ Erro ao ler planilha"); return
    day = datetime.now().day
    saldo = income - total
    limite_diario = saldo / max(30 - day, 1)
    await update.message.reply_text(
        f"💸 *Controle Financeiro*\n\n"
        f"📥 Receita: R$ {income:,.2f}\n📤 Gastos: R$ {total:,.2f}\n"
        f"💰 Saldo: R$ {saldo:,.2f}\n📅 Dias restantes: {30-day}\n"
        f"🎯 Limite diário: R$ {limite_diario:,.2f}",
        parse_mode="Markdown")
    await update.message.reply_text("👇", reply_markup=main_menu_keyboard())

async def cmd_novomes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_user(update): return
    user = get_user(update.effective_user.id)
    ym = datetime.now().strftime("%Y-%m")
    get_or_create_month_sheet(user["spreadsheet_id"], ym)
    await update.message.reply_text(
        f"✅ Planilha *{ym}* pronta!\nhttps://docs.google.com/spreadsheets/d/{user['spreadsheet_id']}",
        parse_mode="Markdown")

async def cmd_fatura(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_user(update): return
    user = get_user(update.effective_user.id); sid = user["spreadsheet_id"]
    svc = get_sheets_service()
    ensure_fatura_sheet(sid)
    try:
        result = svc.spreadsheets().values().get(spreadsheetId=sid, range="FATURAS!A1:H50").execute()
        values = result.get("values", [])
        if not values or len(values) == 1:
            await update.message.reply_text("📄 Nenhuma fatura registrada."); return
        open_rows = [r for r in values[1:] if len(r) >= 5 and r[4].upper() != "SIM"]
        if not open_rows:
            await update.message.reply_text("✅ Todas as faturas estão pagas."); return
        lines = ["📄 *Faturas em aberto*\n"]
        for r in open_rows:
            lines.append(f"• {r[0]} ({r[1]}): R$ {r[2]} – Venc: {r[3] if len(r)>3 else '?'}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Erro fatura: {e}")
        await update.message.reply_text("❌ Erro ao ler faturas.")

async def cmd_pagar_fatura(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_user(update): return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("❌ Uso: /pagar_fatura <cartão> <ref_mês> <valor>\nEx: /pagar_fatura Nubank 2026-06 1234,56"); return
    cartao, ref_month = args[0], args[1]
    try:
        valor = float(args[2].replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ Valor inválido."); return
    user = get_user(update.effective_user.id); sid = user["spreadsheet_id"]
    res = get_fatura_row(sid, cartao, ref_month)
    if not res:
        await update.message.reply_text(f"❌ Fatura não encontrada para {cartao} / {ref_month}."); return
    row_idx, row = res
    update_fatura_cell(sid, row_idx, "E", "SIM")
    update_fatura_cell(sid, row_idx, "F", f"{valor:.2f}")
    update_fatura_cell(sid, row_idx, "G", datetime.now().strftime("%d/%m/%Y"))
    await update.message.reply_text(f"✅ Fatura de {cartao} ({ref_month}) paga: R$ {valor:,.2f}.")

# ═══════════════════════════════════════════════════════
# /fixo — Gastos Fixos
# ═══════════════════════════════════════════════════════
async def cmd_fixo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro."); return
    args = context.args
    if not args:
        await cmd_fixo_list(update, context); return
    if args[0] in ("add","adicionar","novo"):
        context.user_data["fixo"] = {}
        await update.message.reply_text("📌 *Nome do gasto fixo:*\nEx: Aluguel, Netflix, Academia", parse_mode="Markdown")
        return FIXO_NOME
    await update.message.reply_text(
        "📌 */fixo* — Listar fixos\n*/fixo add* — Adicionar fixo\n"
        "Para remover, edite direto na aba FIXOS da sua planilha.",
        parse_mode="Markdown")

async def fixo_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["fixo"]["nome"] = update.message.text
    await update.message.reply_text("💰 *Valor do gasto fixo:*\nEx: 89,90", parse_mode="Markdown")
    return FIXO_VALOR

async def fixo_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        v = float(update.message.text.replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ Valor inválido."); return FIXO_VALOR
    context.user_data["fixo"]["valor"] = v
    await update.message.reply_text("📅 *Dia de vencimento:*\nEx: 15 (dia do mês)", parse_mode="Markdown")
    return FIXO_DIA

async def fixo_dia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["fixo"]["dia"] = update.message.text
    await update.message.reply_text("📂 *Categoria:*", parse_mode="Markdown", reply_markup=category_keyboard())
    return FIXO_CATEGORIA

async def fixo_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat = query.data.replace("cat_", "")
    d = context.user_data["fixo"]
    user = get_user(update.effective_user.id)
    append_fixo(user["spreadsheet_id"], [d["nome"], d["valor"], d["dia"], cat, "SIM", ""])
    await query.edit_message_text(
        f"✅ Fixo adicionado: *{d['nome']}* — R$ {d['valor']:,.2f} (dia {d['dia']})\n"
        f"📂 {CATEGORIES.get(cat, cat)}",
        parse_mode="Markdown")
    await query.message.reply_text("👇 O que deseja fazer agora?", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

async def cmd_fixo_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    fixos = read_fixos(user["spreadsheet_id"])
    if not fixos:
        await update.message.reply_text("📌 Nenhum gasto fixo cadastrado. Use */fixo add*", parse_mode="Markdown"); return
    ativos = [f for f in fixos if f.get("ativo", True)]
    total = sum(f["valor"] for f in ativos)
    lines = [f"📌 *Gastos Fixos ({len(ativos)})*", f"💰 Total: R$ {total:,.2f}\n"]
    for f in ativos:
        dia = f"dia {f['dia']}" if f.get("dia") else ""
        obs = f" ({f['obs']})" if f.get("obs") else ""
        lines.append(f"• *{f['nome']}* — R$ {f['valor']:,.2f} — {dia}{obs}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    await update.message.reply_text("👇", reply_markup=main_menu_keyboard())

# ═══════════════════════════════════════════════════════
# /parcela — Parcelamentos
# ═══════════════════════════════════════════════════════
async def cmd_parcela(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro."); return
    args = context.args
    if not args:
        await cmd_parcela_list(update, context); return
    sub = args[0].lower()
    if sub in ("add","adicionar","novo"):
        context.user_data["parcela"] = {}
        await update.message.reply_text("📅 *Nome do parcelamento:*\nEx: Curso, Geladeira, Celular", parse_mode="Markdown")
        return PARC_NOME
    await update.message.reply_text(
        "📅 */parcela* — Listar parcelas\n*/parcela add* — Adicionar parcela\n"
        "Para quitar: edite a aba PARCELAMENTOS na planilha.", parse_mode="Markdown")

async def parcela_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["parcela"]["nome"] = update.message.text
    await update.message.reply_text("💰 *Valor total do parcelamento:*\nEx: 3000", parse_mode="Markdown")
    return PARC_TOTAL

async def parcela_total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        v = float(update.message.text.replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ Valor inválido."); return PARC_TOTAL
    context.user_data["parcela"]["total"] = v
    await update.message.reply_text("🔢 *Número de parcelas:*\nEx: 12", parse_mode="Markdown")
    return PARC_NPARC

async def parcela_nparc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        n = int(update.message.text)
    except ValueError:
        await update.message.reply_text("❌ Número inválido."); return PARC_NPARC
    context.user_data["parcela"]["n_parcelas"] = n
    await update.message.reply_text("💵 *Valor de cada parcela:*\nEx: 250", parse_mode="Markdown")
    return PARC_VALOR_PARC

async def parcela_valor_parc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        v = float(update.message.text.replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ Valor inválido."); return PARC_VALOR_PARC
    context.user_data["parcela"]["valor_parcela"] = v
    await update.message.reply_text("📂 *Categoria:*", parse_mode="Markdown", reply_markup=category_keyboard())
    return PARC_CATEGORIA

async def parcela_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat = query.data.replace("cat_", "")
    d = context.user_data["parcela"]
    user = get_user(update.effective_user.id)
    # Calcular próx vencimento (hoje + 1 mês)
    prox = (datetime.now() + timedelta(days=30)).strftime("%d/%m/%Y")
    append_parcela(user["spreadsheet_id"], [d["nome"], d["total"], d["n_parcelas"],
                                            d["valor_parcela"], cat, "0", prox, "SIM"])
    await query.edit_message_text(
        f"✅ Parcelamento adicionado: *{d['nome']}*\n"
        f"💰 Total: R$ {d['total']:,.2f} em {d['n_parcelas']}x de R$ {d['valor_parcela']:,.2f}\n"
        f"📂 {CATEGORIES.get(cat, cat)}",
        parse_mode="Markdown")
    await query.message.reply_text("👇 O que deseja fazer agora?", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

async def cmd_parcela_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    parcelas = read_parcelas(user["spreadsheet_id"])
    if not parcelas:
        await update.message.reply_text("📅 Nenhum parcelamento. Use */parcela add*", parse_mode="Markdown")
        return
    ativas = [p for p in parcelas if p.get("ativo", True)]
    if not ativas:
        await update.message.reply_text("✅ Todos os parcelamentos estão quitados!"); return
    total_restante = 0
    lines = [f"📅 *Parcelamentos Ativos ({len(ativas)})*\n"]
    for p in ativas:
        restantes = p["n_parcelas"] - p.get("pagas", 0)
        restante_valor = restantes * p["valor_parcela"]
        total_restante += restante_valor
        lines.append(f"• *{p['nome']}* — {p.get('pagas',0)}/{p['n_parcelas']} pagas")
        lines.append(f"  R$ {p['valor_parcela']:,.2f}/mês | Restam {restantes}x = R$ {restante_valor:,.2f}")
    lines.append(f"\n💰 *Total restante: R$ {total_restante:,.2f}*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    await update.message.reply_text("👇", reply_markup=main_menu_keyboard())

# ═══════════════════════════════════════════════════════
# /meta — Metas Financeiras
# ═══════════════════════════════════════════════════════
async def cmd_meta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro."); return
    args = context.args
    if not args:
        await cmd_meta_list(update, context); return
    sub = args[0].lower()
    if sub in ("add","adicionar","nova"):
        context.user_data["meta"] = {}
        await update.message.reply_text("🎯 *Nome da meta:*\nEx: Economizar para viagem, Quitar dívidas", parse_mode="Markdown")
        return META_NOME
    await update.message.reply_text(
        "🎯 */meta* — Listar metas\n*/meta add* — Adicionar meta", parse_mode="Markdown")

async def meta_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["meta"]["nome"] = update.message.text
    await update.message.reply_text("💰 *Valor da meta:*\nEx: 5000", parse_mode="Markdown")
    return META_TARGET

async def meta_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        v = float(update.message.text.replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ Valor inválido."); return META_TARGET
    context.user_data["meta"]["target"] = v
    await update.message.reply_text("📂 *Categoria (opcional):*\nDigite /pular para ignorar", parse_mode="Markdown")
    return META_CATEGORIA_META

async def meta_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = update.message.text if update.message.text != "/pular" else ""
    d = context.user_data["meta"]
    user = get_user(update.effective_user.id)
    append_meta(user["spreadsheet_id"], [d["nome"], d["target"], "0", cat, "NÃO", "SIM"])
    upsert_meta_db(user_id=user["user_id"], name=d["nome"], target=d["target"], category=cat)
    await update.message.reply_text(
        f"✅ Meta criada: *{d['nome']}* — R$ {d['target']:,.2f}",
        parse_mode="Markdown")
    return ConversationHandler.END

async def meta_categoria_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback version if category has buttons"""
    query = update.callback_query
    await query.answer()
    cat = query.data.replace("cat_", "")
    d = context.user_data["meta"]
    user = get_user(update.effective_user.id)
    append_meta(user["spreadsheet_id"], [d["nome"], d["target"], "0", cat, "NÃO", "SIM"])
    upsert_meta_db(user_id=user["user_id"], name=d["nome"], target=d["target"], category=cat)
    await query.edit_message_text(
        f"✅ Meta criada: *{d['nome']}* — R$ {d['target']:,.2f} ({CATEGORIES.get(cat, cat)})",
        parse_mode="Markdown")
    return ConversationHandler.END

async def cmd_meta_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    metas = read_metas(user["spreadsheet_id"])
    metas_locais = get_metas_from_db(user["user_id"])
    if not metas and not metas_locais:
        await update.message.reply_text("🎯 Nenhuma meta cadastrada. Use */meta add*", parse_mode="Markdown"); return
    lines = ["🎯 *Minhas Metas*\n"]
    for m in metas:
        if m.get("ativo", True):
            pct = (m["atual"] / m["meta"]) * 100 if m["meta"] > 0 else 0
            bar = "▓" * int(pct / 10) + "░" * (10 - int(pct / 10))
            lines.append(f"• *{m['nome']}*")
            lines.append(f"  {bar} R$ {m['atual']:,.2f} / R$ {m['meta']:,.2f} ({pct:.0f}%)")
    if not metas:
        for m in metas_locais:
            pct = (m["current"] / m["target"]) * 100 if m["target"] > 0 else 0
            bar = "▓" * int(pct / 10) + "░" * (10 - int(pct / 10))
            lines.append(f"• *{m['name']}*")
            lines.append(f"  {bar} R$ {m['current']:,.2f} / R$ {m['target']:,.2f} ({pct:.0f}%)")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# ═══════════════════════════════════════════════════════
# /busca — Busca Avançada
# ═══════════════════════════════════════════════════════
async def cmd_busca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro."); return
    args = context.args
    if not args:
        await update.message.reply_text(
            "🔍 *Busca Avançada*\n\n"
            "Uso: */busca <termo>*\n"
            "Ex: */busca mercado*\n*/busca Nubank*\n*/busca 500*\n\n"
            "Você também pode filtrar:\n*/busca categoria:alimentacao*\n*/busca valor:>100*",
            parse_mode="Markdown"); return
    query_text = " ".join(args)
    await execute_busca(update, context, query_text)

async def execute_busca(update: Update, context: ContextTypes.DEFAULT_TYPE, query_text: str):
    user = get_user(update.effective_user.id)
    sid = user["spreadsheet_id"]; ym = datetime.now().strftime("%Y-%m")
    data = read_range(sid, f"{ym}!A1:J50")
    if len(data) <= 1:
        await update.message.reply_text("📭 Nenhum gasto registrado esse mês."); return

    # Parse filters
    filters_list = {"termo": "", "categoria": "", "valor_min": None, "valor_max": None, "pagamento": ""}
    parts = query_text.lower().split()
    for p in parts:
        if p.startswith("categoria:"):
            filters_list["categoria"] = p.split(":", 1)[1]
        elif p.startswith("valor:>"):
            try: filters_list["valor_min"] = float(p.split(":>")[1])
            except: pass
        elif p.startswith("valor:<"):
            try: filters_list["valor_max"] = float(p.split(":<")[1])
            except: pass
        elif p.startswith("pagamento:"):
            filters_list["pagamento"] = p.split(":", 1)[1]
        else:
            filters_list["termo"] += p + " "

    filters_list["termo"] = filters_list["termo"].strip()
    termo_lower = filters_list["termo"].lower() if filters_list["termo"] else ""

    results = []
    for r in data[1:]:
        if len(r) < 6: continue
        row_text = "|".join(str(x).lower() for x in r[:6])
        cat = r[2].lower() if len(r) > 2 else ""
        pag = r[4].lower() if len(r) > 4 else ""
        val = parse_float(r[5]) if r[5] else 0

        if filters_list["categoria"] and filters_list["categoria"] not in cat:
            continue
        if filters_list["pagamento"] and filters_list["pagamento"] not in pag:
            continue
        if filters_list["valor_min"] and val < filters_list["valor_min"]:
            continue
        if filters_list["valor_max"] and val > filters_list["valor_max"]:
            continue
        if termo_lower and termo_lower not in row_text:
            continue

        results.append(r)

    if not results:
        await update.message.reply_text("🔍 Nenhum gasto encontrado com esses filtros."); return

    total = sum(parse_float(r[5]) for r in results if r[5])
    lines = [f"🔍 *{len(results)} resultado(s)*", f"💰 Total: R$ {total:,.2f}\n"]
    for r in results:
        lines.append(f"• {r[0]} — *{r[1]}* — R$ {r[5]} — {r[3] if len(r)>3 else ''}")
    if len(lines) > 30:
        lines = lines[:28] + ["\n... (mais resultados não exibidos)"]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    await update.message.reply_text("👇", reply_markup=main_menu_keyboard())

# ═══════════════════════════════════════════════════════
# /relatorio — Relatório Financeiro
# ═══════════════════════════════════════════════════════
async def cmd_relatorio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro."); return
    user = get_user(update.effective_user.id)
    sid = user["spreadsheet_id"]; ym = datetime.now().strftime("%Y-%m")
    income = user["income"]

    try:
        data = read_range(sid, f"{ym}!A1:J50")
        fixos = read_fixos(sid)
        parcelas = read_parcelas(sid)
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao ler dados: {e}"); return

    if len(data) <= 1:
        await update.message.reply_text("📭 Nenhum gasto no mês para gerar relatório."); return

    total = sum(parse_float(r[5]) for r in data[1:] if len(r) > 5 and r[5])
    cats = {}
    for r in data[1:]:
        if len(r) > 5 and r[2] and r[5]:
            cats[r[2]] = cats.get(r[2], 0) + parse_float(r[5])

    # Calcular gastos necessários vs supérfluos
    necessarios = sum(parse_float(r[5]) for r in data[1:] if len(r) > 7 and r[7] == "SIM" and r[5])
    superfluos = total - necessarios

    # Gastos fixos
    total_fixos = sum(f["valor"] for f in fixos if f.get("ativo", True))

    # Parcelas
    total_parcelas_mensal = sum(p["valor_parcela"] for p in parcelas if p.get("ativo", True))
    total_restante = sum(
        (p["n_parcelas"] - p.get("pagas", 0)) * p["valor_parcela"]
        for p in parcelas if p.get("ativo", True)
    )

    dia = datetime.now().day
    projecao = (total / dia) * 30 if dia > 0 else total
    saldo_projetado = income - projecao

    lines = [
        f"📄 *Relatório Financeiro — {ym}*\n",
        f"📥 *Receita:* R$ {income:,.2f}",
        f"📤 *Gastos:* R$ {total:,.2f} ({total/income*100:.0f}% da renda)" if income > 0 else f"📤 *Gastos:* R$ {total:,.2f}",
        f"💰 *Saldo:* R$ {income - total:,.2f}",
        f"✅ *Necessário:* R$ {necessarios:,.2f} | ❌ *Supérfluo:* R$ {superfluos:,.2f}\n",
        f"📌 *Fixos:* R$ {total_fixos:,.2f}/mês",
        f"📅 *Parcelas:* R$ {total_parcelas_mensal:,.2f}/mês",
        f"💳 *Dívidas restantes:* R$ {total_restante:,.2f}\n",
        f"🔮 *Projeção fim do mês:* R$ {projecao:,.2f}",
    ]
    if income > 0:
        if saldo_projetado < 0:
            lines.append(f"⚠️ *Alerta:* Projeção de déficit de R$ {abs(saldo_projetado):,.2f}!")
        else:
            lines.append(f"💪 *Saldo projetado:* R$ {saldo_projetado:,.2f}")

    lines.append(f"\n📂 *Gastos por categoria:*")
    for cat, val in sorted(cats.items(), key=lambda x: -x[1])[:5]:
        pct = val / total * 100 if total > 0 else 0
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        lines.append(f"{bar} {cat[:15]}: R$ {val:,.2f} ({pct:.0f}%)")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    await update.message.reply_text(f"📊 Planilha: https://docs.google.com/spreadsheets/d/{sid}", parse_mode="Markdown")
    await update.message.reply_text("👇", reply_markup=main_menu_keyboard())

# ═══════════════════════════════════════════════════════
# /conquistas — Gamificação
# ═══════════════════════════════════════════════════════
async def cmd_conquistas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro."); return
    user = get_user(update.effective_user.id)
    achievements = get_achievements(update.effective_user.id)
    ACHIEVEMENT_NAMES = {
        "gastos_10": "📝 Primeiros Passos — 10 gastos registrados",
        "gastos_100": "🏆 Mestre dos Gastos — 100 gastos registrados",
    }

    lines = [
        f"🏆 *Suas Conquistas*\n",
        f"📝 Total de gastos: {user.get('gastos_count',0)}\n",
        "🔓 *Conquistas desbloqueadas:*"
    ]

    unlocked_keys = {a["key"] for a in achievements}
    found = False
    for key, name in ACHIEVEMENT_NAMES.items():
        if key in unlocked_keys:
            lines.append(f"  ✅ {name}")
            found = True
    if not found:
        lines.append("  (nenhuma ainda — continue usando o bot!)")

    # Mostrar próximas conquistas
    lines.append("\n🎯 *Próximas conquistas:*")
    if "gastos_10" not in unlocked_keys:
        lines.append(f"  🔒 {ACHIEVEMENT_NAMES['gastos_10']}")
    if "gastos_100" not in unlocked_keys and "gastos_10" in unlocked_keys:
        lines.append(f"  🔒 {ACHIEVEMENT_NAMES['gastos_100']}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# ═══════════════════════════════════════════════════════
# /perfil — Configurar Perfil
# ═══════════════════════════════════════════════════════
async def cmd_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra perfil e permite editar renda."""
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro.")
        return
    user = get_user(update.effective_user.id)
    args = context.args
    
    if not args:
        await update.message.reply_text(
            f"👤 *Seu Perfil*\n\n"
            f"📝 Nome: {user['name']}\n"
            f"💰 Renda: R$ {user['income']:,.2f}\n"
            f"💳 Cartões: {user.get('cards', 'nenhum')}\n"
            f"🎯 Objetivo: {user.get('goal', '')}\n\n"
            f"Para alterar sua renda: */perfil renda 3500*\n"
            f"Para alterar nome: */perfil nome Caio Salles*\n"
            f"Para alterar cartões: */perfil cards Nubank, Itau*",
            parse_mode="Markdown", reply_markup=main_menu_keyboard()
        )
        return
    
    sub = args[0].lower()
    if sub == "renda" and len(args) >= 2:
        try:
            nova_renda = float(args[1].replace(",", "."))
        except ValueError:
            await update.message.reply_text("❌ Valor inválido. Use: /perfil renda 3500")
            return
        if nova_renda <= 0:
            await update.message.reply_text("❌ Renda deve ser maior que zero.")
            return
        upsert_user(update.effective_user.id, income=nova_renda)
        save_user_to_master(update.effective_user.id, user.get("username",""), user.get("first_name",""),
                           user["name"], nova_renda, user.get("cards",""), user.get("goal",""), user["spreadsheet_id"])
        await update.message.reply_text(f"✅ Renda atualizada para R$ {nova_renda:,.2f}!", parse_mode="Markdown", reply_markup=main_menu_keyboard())
    elif sub == "nome" and len(args) >= 2:
        novo_nome = " ".join(args[1:])
        upsert_user(update.effective_user.id, name=novo_nome)
        await update.message.reply_text(f"✅ Nome atualizado para *{novo_nome}*!", parse_mode="Markdown", reply_markup=main_menu_keyboard())
    elif sub == "cards" and len(args) >= 2:
        novos_cards = " ".join(args[1:])
        upsert_user(update.effective_user.id, cards=novos_cards)
        await update.message.reply_text(f"✅ Cartões atualizados: *{novos_cards}*", parse_mode="Markdown", reply_markup=main_menu_keyboard())
    else:
        await update.message.reply_text(
            "Use: */perfil renda 3500*\n*/perfil nome Caio*\n*/perfil cards Nubank, Itau*",
            parse_mode="Markdown"
        )

# ═══════════════════════════════════════════════════════
# /receita — Registrar Renda Extra
# ═══════════════════════════════════════════════════════
async def cmd_receita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registra uma receita extra na planilha."""
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "💵 *Registrar Receita Extra*\n\n"
            "Uso: */receita <valor> <descrição>*\n"
            "Ex: */receita 500 freela*\n*/receita 1500 bonus*\n*/receita 200 ifood*",
            parse_mode="Markdown"
        )
        return
    
    try:
        valor = float(args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ Valor inválido. Ex: /receita 500 freela")
        return
    
    desc = " ".join(args[1:])
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("❌ User não encontrado. Use /start."); return
    sid = user.get("spreadsheet_id", "")
    if not sid:
        await update.message.reply_text("❌ Planilha não configurada. Use /start."); return
    ym = datetime.now().strftime("%Y-%m")
    get_or_create_month_sheet(sid, ym)
    
    # Add a row with type "RECEITA" instead of "CONSUMO"
    row = [
        datetime.now().strftime("%d/%m/%Y"),
        desc, "RECEITA", "", "PIX",
        valor, "", "SIM", "RECEITA", ""
    ]
    append_gasto(sid, ym, row)
    
    # Also ensure INCOME tab exists
    svc = get_sheets_service()
    meta = svc.spreadsheets().get(spreadsheetId=sid).execute()
    sheets_list = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if "RECEITAS" not in sheets_list:
        svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={
            "requests": [{"addSheet": {"properties": {"title": "RECEITAS"}}}]
        }).execute()
        svc.spreadsheets().values().update(
            spreadsheetId=sid, range="RECEITAS!A1:E1",
            valueInputOption="USER_ENTERED",
            body={"values": [["DATA","DESCRIÇÃO","VALOR","CATEGORIA","OBS"]]}
        ).execute()
    
    svc.spreadsheets().values().append(
        spreadsheetId=sid, range="RECEITAS!A:E",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": [[datetime.now().strftime("%d/%m/%Y"), desc, valor, "EXTRA", ""]]}
    ).execute()
    
    await update.message.reply_text(
        f"💵 *Receita de R$ {valor:,.2f}* registrada!\n📝 {desc}",
        parse_mode="Markdown", reply_markup=main_menu_keyboard()
    )

# ═══════════════════════════════════════════════════════
# /insights — Análise Inteligente de Gastos
# ═══════════════════════════════════════════════════════
async def cmd_insights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gera insights financeiros automáticos."""
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro.")
        return
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("❌ User não encontrado. Use /start."); return
    sid = user.get("spreadsheet_id", "")
    if not sid:
        await update.message.reply_text("❌ Planilha não configurada. Use /start."); return
    ym = datetime.now().strftime("%Y-%m")
    
    try:
        from insights import gerar_insights
        insights_list = gerar_insights(sid, ym)
    except Exception as e:
        logger.error(f"Erro insights: {e}")
        await update.message.reply_text(f"❌ Erro ao gerar insights: {e}")
        return
    
    if not insights_list:
        await update.message.reply_text("📈 Nenhum insight disponível ainda. Registre mais gastos!", parse_mode="Markdown", reply_markup=main_menu_keyboard())
        return
    
    lines = ["📈 *Seus Insights Financeiros*\n"]
    for insight in insights_list:
        lines.append(insight)
    
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu_keyboard())

# ═══════════════════════════════════════════════════════
# /compras — Lista de Compras (Google Sheets)
# ═══════════════════════════════════════════════════════
async def cmd_compras(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gerencia lista de compras via Google Sheets."""
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro.")
        return
    args = context.args
    user = get_user(update.effective_user.id)
    sid = user["spreadsheet_id"]

    if not args:
        items = read_compras(sid, apenas_pendentes=True)
        if not items:
            await update.message.reply_text(
                "🛒 *Lista de Compras*\n\n📭 Nenhum item na lista.\n"
                "Use */compras add <item>* para adicionar.",
                parse_mode="Markdown", reply_markup=main_menu_keyboard()
            )
            return
        cats = {}
        for it in items:
            cat = it["categoria"]
            if cat not in cats:
                cats[cat] = []
            preco_str = f" (R$ {it['preco']:.2f})" if it['preco'] > 0 else ""
            qty_str = f" ({it['qty']})" if it['qty'] and it['qty'] != "1" else ""
            cats[cat].append(f"• {it['item']}{qty_str}{preco_str}")
        lines = ["🛒 *Lista de Compras*\n"]
        for cat, itens in cats.items():
            icon = "🛒" if cat == "mercado" else "📦" if cat == "online" else "📋"
            lines.append(f"{icon} *{cat.upper()}*:")
            lines.extend(itens)
            lines.append("")
        lines.append(f"📝 Total: {len(items)} itens")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu_keyboard())
        return

    sub = args[0].lower()

    if sub == "add" and len(args) >= 2:
        item_args = args[1:]
        cat = "mercado"
        qty = "1"
        preco = 0.0
        if item_args[0].lower() in ("mercado", "online", "farmacia", "casa", "outros"):
            cat = item_args[0].lower()
            item_args = item_args[1:]
        if item_args and item_args[-1].lower().endswith("x"):
            try:
                q = int(item_args[-1][:-1])
                if q > 0:
                    qty = str(q)
                    item_args = item_args[:-1]
            except ValueError:
                pass
        if item_args and item_args[-1].startswith("R$"):
            try:
                preco = float(item_args[-1][2:].replace(",", "."))
                item_args = item_args[:-1]
            except ValueError:
                pass
        elif item_args:
            try:
                preco = float(item_args[-1].replace(",", "."))
                item_args = item_args[:-1]
            except (ValueError, IndexError):
                pass
        item = " ".join(item_args) if item_args else "item"
        items = read_compras(sid, apenas_pendentes=False)
        cod = str(len(items) + 1)
        append_compra(sid, [cod, item, qty, cat, preco, "NAO", datetime.now().strftime("%d/%m/%Y")])
        preco_str = f" — R$ {preco:.2f}" if preco > 0 else ""
        await update.message.reply_text(
            f"✅ Adicionado: *{item}* ({cat}){preco_str}",
            parse_mode="Markdown", reply_markup=main_menu_keyboard()
        )

    elif sub == "rm" and len(args) >= 2:
        try:
            idx = int(args[1]) - 1
        except ValueError:
            await update.message.reply_text("❌ Use: /compras rm <número>")
            return
        items = read_compras(sid, apenas_pendentes=True)
        if 0 <= idx < len(items):
            row_idx = idx + 2  # +2 para cabeçalho
            update_compra_cell(sid, row_idx, "G", "SIM")  # Marca como comprado
            await update.message.reply_text(f"🗑️ Removido: *{items[idx]['item']}*", parse_mode="Markdown", reply_markup=main_menu_keyboard())
        else:
            await update.message.reply_text(f"❌ Item #{args[1]} não encontrado.")

    elif sub == "comprado" and len(args) >= 2:
        try:
            idx = int(args[1]) - 1
        except ValueError:
            await update.message.reply_text("❌ Use: /compras comprado <número>")
            return
        items = read_compras(sid, apenas_pendentes=True)
        if 0 <= idx < len(items):
            row_idx = idx + 2
            update_compra_cell(sid, row_idx, "F", "SIM")
            await update.message.reply_text(f"✅ Comprado: *{items[idx]['item']}* 🎉", parse_mode="Markdown", reply_markup=main_menu_keyboard())
        else:
            await update.message.reply_text(f"❌ Item #{args[1]} não encontrado.")

    else:
        await update.message.reply_text(
            "🛒 *Compras*\n\n"
            "*/compras* — Ver lista\n"
            "*/compras add mercado leite 2x* — Adicionar\n"
            "*/compras add online kindle 200* — Com preço\n"
            "*/compras rm 1* — Remover\n"
            "*/compras comprado 1* — Marcar como comprado",
            parse_mode="Markdown"
        )

# ═══════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════
# RELATÓRIOS — Imprimem dados diretamente das abas do Sheets
# ═══════════════════════════════════════════════════════
async def cmd_relatorio_parcelamentos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Relatório de parcelamentos da aba PARCELAMENTOS."""
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro."); return
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("❌ User não encontrado. Use /start."); return
    sid = user.get("spreadsheet_id", "")
    if not sid:
        await update.message.reply_text("❌ Planilha não configurada. Use /start."); return
    try:
        parcelas = read_parcelas(sid)
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao ler parcelamentos: {e}"); return
    if not parcelas:
        await update.message.reply_text("📅 Nenhum parcelamento cadastrado.", reply_markup=main_menu_keyboard()); return
    lines = ["📅 *RELATÓRIO DE PARCELAMENTOS*\n"]
    total_pago = 0
    total_restante = 0
    for p in parcelas:
        total_pago += p["valor_pago"]
        total_restante += p["valor_restante"]
        pct = int(p["pagas"] / p["total_parcelas"] * 100) if p["total_parcelas"] > 0 else 0
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        lines.append(f"*{p['cod']}* — {p['descricao']}")
        lines.append(f"  R$ {p['valor_parcela']:,.2f}/mês | {p['pagas']}/{p['total_parcelas']} pagas")
        lines.append(f"  {bar} {pct}% | Pago: R$ {p['valor_pago']:,.2f} | Resta: R$ {p['valor_restante']:,.2f}")
        lines.append("")
    lines.append(f"💰 *Total Pago:* R$ {total_pago:,.2f}")
    lines.append(f"💳 *Total Restante:* R$ {total_restante:,.2f}")
    lines.append(f"📊 *Total Geral:* R$ {total_pago + total_restante:,.2f}")
    lines.append(f"\n📊 Planilha: https://docs.google.com/spreadsheets/d/{sid}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu_keyboard())

async def cmd_relatorio_fixos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Relatório de gastos fixos da aba FIXOS."""
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro."); return
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("❌ User não encontrado. Use /start."); return
    sid = user.get("spreadsheet_id", "")
    if not sid:
        await update.message.reply_text("❌ Planilha não configurada. Use /start."); return
    try:
        fixos = read_fixos(sid)
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao ler fixos: {e}"); return
    if not fixos:
        await update.message.reply_text("📌 Nenhum gasto fixo cadastrado.", reply_markup=main_menu_keyboard()); return
    ativos = [f for f in fixos if f.get("ativo", True)]
    total = sum(f["valor"] for f in ativos)
    lines = ["📌 *RELATÓRIO DE GASTOS FIXOS*\n"]
    for f in ativos:
        dia = f"dia {f['dia']}" if f.get("dia") else "s/dia"
        lines.append(f"• *{f['nome']}* — R$ {f['valor']:,.2f}/mês — {dia}")
        if f.get("obs"):
            lines.append(f"  _{f['obs']}_")
    lines.append(f"\n💰 *Total mensal:* R$ {total:,.2f}")
    lines.append(f"📊 *Total anual (est.):* R$ {total * 12:,.2f}")
    lines.append(f"\n📊 Planilha: https://docs.google.com/spreadsheets/d/{sid}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu_keyboard())

async def cmd_relatorio_resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Relatório resumo do mês (aba YYYY-MM)."""
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro."); return
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("❌ User não encontrado. Use /start."); return
    sid = user.get("spreadsheet_id", "")
    if not sid:
        await update.message.reply_text("❌ Planilha não configurada. Use /start."); return
    ym = datetime.now().strftime("%Y-%m")
    try:
        data = read_range(sid, f"{ym}!A1:J50")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao ler planilha: {e}"); return
    if len(data) <= 1:
        await update.message.reply_text("📭 Nenhum gasto registrado este mês.", reply_markup=main_menu_keyboard()); return
    total = sum(parse_float(r[5]) for r in data[1:] if len(r) > 5 and r[5])
    cats = {}
    for r in data[1:]:
        if len(r) > 5 and r[2] and r[5]:
            cats[r[2]] = cats.get(r[2], 0) + parse_float(r[5])
    income = user.get("income", 0)
    saldo = income - total
    lines = [f"📊 *RESUMO FINANCEIRO — {ym}*\n"]
    lines.append(f"📥 Receita: R$ {income:,.2f}")
    lines.append(f"📤 Gastos: R$ {total:,.2f} ({total/income*100:.0f}% da renda)" if income > 0 else f"📤 Gastos: R$ {total:,.2f}")
    lines.append(f"💰 Saldo: R$ {saldo:,.2f}")
    lines.append(f"📂 {len(data)-1} lançamentos\n")
    lines.append("📂 *Por categoria:*")
    for cat, val in sorted(cats.items(), key=lambda x: -x[1]):
        pct = val / total * 100 if total > 0 else 0
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        lines.append(f"{bar} {cat[:15]}: R$ {val:,.2f} ({pct:.0f}%)")
    lines.append(f"\n📊 Planilha: https://docs.google.com/spreadsheets/d/{sid}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu_keyboard())

async def cmd_relatorio_completo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Relatório completo: resumo + fixos + parcelamentos."""
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro."); return
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("❌ User não encontrado. Use /start."); return
    sid = user.get("spreadsheet_id", "")
    if not sid:
        await update.message.reply_text("❌ Planilha não configurada. Use /start."); return
    ym = datetime.now().strftime("%Y-%m")
    income = user.get("income", 0)

    # ── Resumo do mês ──
    try:
        data = read_range(sid, f"{ym}!A1:J50")
        total_gastos = sum(parse_float(r[5]) for r in data[1:] if len(r) > 5 and r[5]) if len(data) > 1 else 0
        cats = {}
        for r in data[1:]:
            if len(r) > 5 and r[2] and r[5]:
                cats[r[2]] = cats.get(r[2], 0) + parse_float(r[5])
    except:
        total_gastos = 0
        cats = {}

    # ── Fixos ──
    try:
        fixos = read_fixos(sid)
        total_fixos = sum(f["valor"] for f in fixos if f.get("ativo", True))
    except:
        total_fixos = 0

    # ── Parcelamentos ──
    try:
        parcelas = read_parcelas(sid)
        total_parcelas_pago = sum(p["valor_pago"] for p in parcelas)
        total_parcelas_restante = sum(p["valor_restante"] for p in parcelas)
    except:
        total_parcelas_pago = 0
        total_parcelas_restante = 0

    # ── Montar relatório ──
    lines = [f"📄 *RELATÓRIO COMPLETO — {ym}*\n"]
    lines.append("═" * 30)
    lines.append("📊 *RESUMO DO MÊS*")
    lines.append(f"📥 Receita: R$ {income:,.2f}")
    lines.append(f"📤 Gastos: R$ {total_gastos:,.2f}")
    lines.append(f"💰 Saldo: R$ {income - total_gastos:,.2f}\n")

    if cats:
        lines.append("📂 *Categorias:*")
        for cat, val in sorted(cats.items(), key=lambda x: -x[1])[:5]:
            pct = val / total_gastos * 100 if total_gastos > 0 else 0
            lines.append(f"  • {cat[:15]}: R$ {val:,.2f} ({pct:.0f}%)")
        lines.append("")

    lines.append("═" * 30)
    lines.append("📌 *GASTOS FIXOS*")
    lines.append(f"💰 Total mensal: R$ {total_fixos:,.2f}")
    lines.append(f"📊 Total anual (est.): R$ {total_fixos * 12:,.2f}\n")

    lines.append("═" * 30)
    lines.append("📅 *PARCELAMENTOS*")
    lines.append(f"💰 Total já pago: R$ {total_parcelas_pago:,.2f}")
    lines.append(f"💳 Total restante: R$ {total_parcelas_restante:,.2f}")
    lines.append(f"📊 Total geral: R$ {total_parcelas_pago + total_parcelas_restante:,.2f}\n")

    lines.append("═" * 30)
    total_comprometido = total_gastos + total_fixos + total_parcelas_restante
    lines.append("🔮 *PROJEÇÃO*")
    lines.append(f"💸 Total comprometido: R$ {total_comprometido:,.2f}")
    if income > 0:
        lines.append(f"📈 % da renda comprometida: {total_comprometido/income*100:.0f}%")
        lines.append(f"💰 Saldo livre: R$ {income - total_comprometido:,.2f}")
    lines.append(f"\n📊 Planilha: https://docs.google.com/spreadsheets/d/{sid}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu_keyboard())

# ═══════════════════════════════════════════════════════
# MENU HANDLER — Callbacks dos botões inline
# ═══════════════════════════════════════════════════════
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cmd = query.data

    # Garantir que effective_user está disponível para callbacks
    if update.effective_user is None:
        try:
            update._effective_user = query.from_user
        except Exception:
            pass

    # Helper para criar update fake com effective_user para comandos via callback
    def _fake_update_for_command():
        _msg = query.message
        _user = query.from_user
        _upd = Update(update_id=0, message=_msg)
        _upd._effective_user = _user
        return _upd

    if cmd == "menu_financas":
        # Lançamentos → fluxo /gasto
        await query.edit_message_text(
            "💸 *Lançamentos*\n\n"
            "Use */gasto* para modo guiado (passo a passo)\n"
            "Use */g 50 mercado pix* para modo rápido\n\n"
            "Pagamentos à vista: débito, pix, dinheiro\n"
            "Pagamentos parcelados: crédito, carnê",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )

    elif cmd == "menu_relatorios":
        # Sub-menu Relatórios: Parcelas | Assinaturas | Lançamentos | Resumo | Completo
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Parcelas", callback_data="menu_parcelas")],
            [InlineKeyboardButton("📱 Assinaturas", callback_data="menu_assinaturas")],
            [InlineKeyboardButton("💸 Lançamentos", callback_data="menu_lancamentos")],
            [InlineKeyboardButton("📊 Resumo", callback_data="menu_resumo")],
            [InlineKeyboardButton("📄 Relatório Completo", callback_data="menu_relatorio")],
            [InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="menu_voltar")],
        ])
        await query.edit_message_text("📊 *Relatórios*\n\nSelecione uma opção:", parse_mode="Markdown", reply_markup=keyboard)

    elif cmd == "menu_parcelas":
        await cmd_relatorio_parcelamentos(_fake_update_for_command(), context)

    elif cmd == "menu_assinaturas":
        await cmd_relatorio_fixos(_fake_update_for_command(), context)

    elif cmd == "menu_lancamentos":
        await cmd_relatorio_resumo(_fake_update_for_command(), context)

    elif cmd == "menu_resumo":
        await cmd_relatorio_resumo(_fake_update_for_command(), context)

    elif cmd == "menu_relatorio":
        await cmd_relatorio_completo(_fake_update_for_command(), context)

    elif cmd == "menu_compras":
        await query.edit_message_text(
            "🛒 *Compras & Desejos*\n\n"
            "*/compras* — Ver lista de compras\n"
            "*/compras add leite 2x* — Adicionar (com quantidade)\n"
            "*/compras add mercado arroz* — Categoria: mercado\n"
            "*/compras add online kindle 200* — Com preço\n"
            "*/compras rm 1* — Remover item #1\n"
            "*/compras comprado 1* — Marcar como comprado\n"
            "*/compras desejo item* — Lista de desejos\n"
            "*/compras done* — Limpar lista",
            reply_markup=main_menu_keyboard()
        )

    elif cmd == "menu_perfil":
        user = get_user(update.effective_user.id)
        await query.edit_message_text(
            f"👤 *Seu Perfil*\n\n"
            f"📝 Nome: {user['name']}\n"
            f"💰 Renda: R$ {user['income']:,.2f}\n"
            f"💳 Cartões: {user.get('cards', 'nenhum')}\n"
            f"🎯 Objetivo: {user.get('goal', '')}\n\n"
            f"Para alterar: */perfil renda 3500*",
            parse_mode="Markdown", reply_markup=main_menu_keyboard()
        )

    elif cmd == "menu_receita":
        await query.edit_message_text(
            "💵 *Receitas Extra*\n\n"
            "Use */receita <valor> <descrição>*\n"
            "Ex: /receita 500 freela\n"
            "Ex: /receita 1500 bonus\n"
            "Ex: /receita 200 ifood\n\n"
            "💡 Dica: Registre todas as rendas extras para ter "
            "uma visão completa do seu fluxo financeiro!",
            parse_mode="Markdown", reply_markup=main_menu_keyboard()
        )

    elif cmd == "menu_voltar":
        await query.edit_message_text("👇 O que deseja fazer agora?",
            reply_markup=main_menu_keyboard())

    else:
        await query.edit_message_text("✅ Funcionalidade em desenvolvimento.",
            reply_markup=main_menu_keyboard())


    # ═══════════════════════════════════════════════════════
    # ERROR HANDLER
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception: {context.error}", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ Ocorreu um erro. Tente novamente ou use /start."
            )
        except Exception:
            pass

# ═══════════════════════════════════════════════════════
# NOTIFICAÇÕES (2 tipos implementados com cron real)
# ═══════════════════════════════════════════════════════
async def budget_warning(context: ContextTypes.DEFAULT_TYPE):
    """Alerta de orçamento — todo dia às 10h BRT."""
    users = get_all_users()
    for user in users:
        try:
            ym = datetime.now().strftime("%Y-%m")
            data = read_range(user["spreadsheet_id"], f"{ym}!A1:J200")
            total = sum(parse_float(r[5]) for r in data[1:] if len(r) > 5 and r[5]) if len(data) > 1 else 0
            pct = total / user["income"] * 100 if user["income"] > 0 else 0

            if pct >= 80:
                days_left = 30 - datetime.now().day
                limite = (user["income"] - total) / max(days_left, 1)
                await context.bot.send_message(
                    user["user_id"],
                    f"🔴 *Alerta de orçamento!*\n\n"
                    f"Gasto: R$ {total:,.2f} de R$ {user['income']:,.2f} ({pct:.0f}%)\n"
                    f"Restam {days_left} dias\nLimite diário: R$ {limite:,.2f}\n\n⚠️ Atenção!",
                    parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Erro budget_warning user {user['user_id']}: {e}")

async def lembrete_registro(context: ContextTypes.DEFAULT_TYPE):
    """Lembrete diário de registro de gastos — todo dia às 20h BRT."""
    users = get_all_users()
    today = datetime.now().strftime("%Y-%m-%d")
    for user in users:
        try:
            if user.get("last_gasto_date") != today:
                await context.bot.send_message(
                    user["user_id"],
                    f"🔥 *{user['name']}, não esqueça de registrar seus gastos hoje!*",
                    parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Erro lembrete user {user['user_id']}: {e}")

async def monthly_reset(context: ContextTypes.DEFAULT_TYPE):
    """Cria aba do novo mês — dia 1 às 00:05 BRT."""
    ym = datetime.now().strftime("%Y-%m")
    users = get_all_users()
    for user in users:
        try:
            get_or_create_month_sheet(user["spreadsheet_id"], ym)
            await context.bot.send_message(
                user["user_id"],
                f"📅 *Novo mês: {ym}*\n"
                f"Sua planilha está pronta! Bons hábitos financeiros! 💪",
                parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Erro monthly_reset user {user['user_id']}: {e}")

# ═══════════════════════════════════════════════════════
# POST-INIT
# ═══════════════════════════════════════════════════════
async def post_init(application):
    """Configura comandos do bot no menu do Telegram."""
    await application.bot.set_my_commands([
        ("start", "Iniciar/Reiniciar o bot"),
        ("gasto", "Registrar gasto (guiado)"),
        ("g", "Gasto rápido: /g 50 mercado alimentacao pix"),
        ("resumo", "Resumo financeiro do mês"),
        ("limite", "Limite diário disponível"),
        ("fatura", "Ver faturas em aberto"),
        ("pagar_fatura", "Pagar fatura"),
        ("fixo", "Gerenciar gastos fixos"),
        ("parcela", "Gerenciar parcelamentos"),
        ("busca", "Buscar gastos"),
        ("insights", "Insights financeiros e alertas"),
        ("receita", "Registrar renda extra"),
        ("perfil", "Configurar perfil (renda, nome, cartões)"),
        ("compras", "Lista de compras / mercado"),
        ("relatorio", "Relatório financeiro completo"),
        ("relatorio_parcelamentos", "Relatório de parcelamentos"),
        ("relatorio_fixos", "Relatório de gastos fixos"),
        ("relatorio_resumo", "Resumo financeiro do mês"),
        ("relatorio_completo", "Relatório completo (tudo)"),
        ("novomes", "Criar aba do mês atual"),
    ])
    logger.info("Bot commands set")

# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════
def main():
    init_db()
    
    # Dashboard só inicia localmente (não no Render para evitar conflito de porta)
    if not os.environ.get("RENDER"):
        try:
            from dashboard import start_dashboard
            start_dashboard(blocking=False)
            logger.info("📊 Dashboard iniciado na porta 8888")
        except Exception as e:
            logger.warning(f"Dashboard não iniciado: {e}")
    else:
        logger.info("📊 Dashboard desabilitado no Render (porta 8080 reservada)")

    # Sincronizar usuários da Master Sheet (se disponível)
    try:
        ensure_master_sheet()
        count = sync_users_from_master()
        if count > 0:
            logger.info(f"Restored {count} users from master sheet")
    except Exception as e:
        logger.warning(f"Master sheet sync unavailable: {e}")

    app = Application.builder().token(TOKEN).build()

    # ── Notificações com JobQueue ──
    # Alerta de orçamento: todo dia às 10h BRT
    app.job_queue.run_daily(budget_warning, time=datetime.strptime("10:00", "%H:%M").time(), name="budget_warning")
    # Lembrete diário: todo dia às 20h BRT
    app.job_queue.run_daily(lembrete_registro, time=datetime.strptime("20:00", "%H:%M").time(), name="lembrete_registro")
    # Reset mensal: dia 1 às 00:05
    app.job_queue.run_daily(monthly_reset, time=datetime.strptime("00:05", "%H:%M").time(), days=(0,), name="monthly_reset")
    # Resumo semanal: segunda às 9h
    app.job_queue.run_daily(
        lambda ctx: None,  # placeholder — weekly_summary seria reativado com mais dados
        time=datetime.strptime("09:00", "%H:%M").time(),
        days=(0,), name="weekly_summary_placeholder"
    )

    # ── Onboarding Handler ──
    onboarding_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_name)],
            INCOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_income)],
            CARDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_cards)],
            GOAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_goal)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)]
    )

    # ── Gasto Conversacional Handler ──
    gasto_conv = ConversationHandler(
        entry_points=[CommandHandler("gasto", gasto_start)],
        states={
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, gasto_amount)],
            DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, gasto_desc)],
            CATEGORY: [CallbackQueryHandler(gasto_category, pattern="^cat_")],
            PAYMENT: [CallbackQueryHandler(gasto_payment, pattern="^pay_")],
            CARD_SEL: [
                CallbackQueryHandler(gasto_card, pattern="^card_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, gasto_card_text)
            ],
            NECESSARY: [CallbackQueryHandler(gasto_necessary, pattern="^nec_")],
            IS_SUBSCRIPTION: [CallbackQueryHandler(gasto_is_subscription, pattern="^sub_")],
            SUBSCRIPTION_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, gasto_subscription_name)],
            SUBSCRIPTION_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, gasto_subscription_valor)],
            IS_INSTALMENT: [CallbackQueryHandler(gasto_is_instalment, pattern="^inst_")],
            INSTALMENT_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, gasto_instalment_qty)],
            OBS: [
                CommandHandler("pular", gasto_obs_pular),
                MessageHandler(filters.TEXT & ~filters.COMMAND, gasto_obs)
            ],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        conversation_timeout=300  # 5 min auto-cancel para limpar estados órfãos
    )

    # ── /fixo Conversational Handler ──
    fixo_conv = ConversationHandler(
        entry_points=[CommandHandler("fixo", cmd_fixo)],
        states={
            FIXO_NOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, fixo_nome)],
            FIXO_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, fixo_valor)],
            FIXO_DIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, fixo_dia)],
            FIXO_CATEGORIA: [CallbackQueryHandler(fixo_categoria, pattern="^cat_")],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )

    # ── /parcela Conversational Handler ──
    parcela_conv = ConversationHandler(
        entry_points=[CommandHandler("parcela", cmd_parcela)],
        states={
            PARC_NOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, parcela_nome)],
            PARC_TOTAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, parcela_total)],
            PARC_NPARC: [MessageHandler(filters.TEXT & ~filters.COMMAND, parcela_nparc)],
            PARC_VALOR_PARC: [MessageHandler(filters.TEXT & ~filters.COMMAND, parcela_valor_parc)],
            PARC_CATEGORIA: [CallbackQueryHandler(parcela_categoria, pattern="^cat_")],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)]
    )

    # ── Registrar HANDLERS (ordem importa!) ──
    # Comandos diretos (sem estado) primeiro
    app.add_handler(CommandHandler("g", gasto_quick))
    app.add_handler(CommandHandler("fatura", cmd_fatura))
    app.add_handler(CommandHandler("pagar_fatura", cmd_pagar_fatura))
    app.add_handler(CommandHandler("resumo", cmd_resumo))
    app.add_handler(CommandHandler("limite", cmd_limite))
    app.add_handler(CommandHandler("novomes", cmd_novomes))
    app.add_handler(CommandHandler("busca", cmd_busca))
    app.add_handler(CommandHandler("insights", cmd_insights))
    app.add_handler(CommandHandler("relatorio", cmd_relatorio))
    app.add_handler(CommandHandler("relatorio_parcelamentos", cmd_relatorio_parcelamentos))
    app.add_handler(CommandHandler("relatorio_fixos", cmd_relatorio_fixos))
    app.add_handler(CommandHandler("relatorio_resumo", cmd_relatorio_resumo))
    app.add_handler(CommandHandler("relatorio_completo", cmd_relatorio_completo))
    # app.add_handler(CommandHandler("conquistas", cmd_conquistas))  # removed for simplicity

    app.add_handler(CommandHandler("perfil", cmd_perfil))
    app.add_handler(CommandHandler("receita", cmd_receita))
    app.add_handler(CommandHandler("compras", cmd_compras))
# ConversationHandlers depois
    app.add_handler(onboarding_conv)
    app.add_handler(parcela_conv)
    app.add_handler(fixo_conv)
    app.add_handler(gasto_conv)

    # Callback handler do menu
    app.add_handler(CallbackQueryHandler(menu_handler, pattern="^menu_"))

    # Error handler
    app.add_error_handler(error_handler)

    app.post_init = post_init

    # ── HTTP Health Check Server (para Render) ──
    port = int(os.environ.get("PORT", 8080))

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"FinBot OK\n")
        def do_HEAD(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
        def log_message(self, format, *args):
            pass

    http_server = HTTPServer(("0.0.0.0", port), HealthHandler)
    http_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    http_thread.start()

    logger.info(f"🤖 FinBot iniciado na porta {port}")
    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()
