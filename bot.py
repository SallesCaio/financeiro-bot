#!/usr/bin/env python3
"""
FinBot — Gestão Financeira via Telegram + Google Sheets
Multi-user, onboarding conversacional, SQLite, notificações.
"""
import os, json, sqlite3, logging, re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import calendar
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ═══════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TEMPLATE_SPREADSHEET_ID = os.environ.get("TEMPLATE_SPREADSHEET_ID", "1m-GTVEJcqzzEBoslIJ5OpeSPj1HJnd3U-6m3JCH_uv8")
DB_PATH = Path(__file__).parent / "finbot.db"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("FinBot")

# Error handler
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception: {context.error}", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ Ocorreu um erro. Tente novamente ou use /start."
            )
        except Exception:
            pass

# Conversation states
(NAME, INCOME, CARDS, GOAL,
 AMOUNT, DESC, CATEGORY, PAYMENT, CARD_SEL, NECESSARY, OBS) = range(11)

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
# DATABASE
# ═══════════════════════════════════════════════════════
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
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
                streak INTEGER DEFAULT 0,
                last_gasto_date TEXT,
                level TEXT DEFAULT 'bronze'
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
            CREATE TABLE IF NOT EXISTS achievements (
                user_id INTEGER,
                key TEXT,
                unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, key)
            );
        """)
        conn.commit()

def get_user(user_id: int) -> Optional[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return None
        cols = [d[0] for d in conn.execute("SELECT * FROM users LIMIT 0").description]
        return dict(zip(cols, row))

def upsert_user(user_id: int, **kwargs):
    with sqlite3.connect(DB_PATH) as conn:
        existing = conn.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone()
        if existing:
            sets = ", ".join(f"{k}=?" for k in kwargs)
            conn.execute(f"UPDATE users SET {sets} WHERE user_id=?", (*kwargs.values(), user_id))
        else:
            cols = "user_id," + ",".join(kwargs.keys())
            placeholders = "?," + ",".join("?" for _ in kwargs)
            conn.execute(f"INSERT INTO users ({cols}) VALUES ({placeholders})", (user_id, *kwargs.values()))
        conn.commit()

def get_notification_state(user_id: int, notif_type: str) -> Optional[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT * FROM notification_state WHERE user_id=? AND notif_type=?",
            (user_id, notif_type)
        ).fetchone()
        if not row:
            return None
        return {"user_id": row[0], "notif_type": row[1], "last_sent": row[2], "last_value": row[3]}

def set_notification_state(user_id: int, notif_type: str, last_value: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO notification_state VALUES (?,?,?,?)",
            (user_id, notif_type, datetime.now().isoformat(), last_value)
        )
        conn.commit()

# ═══════════════════════════════════════════════════════
# GOOGLE SHEETS / DRIVE
# ═══════════════════════════════════════════════════════
def get_sheets_service():
    token_path = Path(__file__).parent / "google_token.json"
    if not token_path.exists():
        token_path = Path.home() / "AppData" / "Local" / "hermes" / "google_token.json"
    with open(token_path) as f:
        d = json.load(f)
    creds = Credentials(token=d["token"], refresh_token=d["refresh_token"],
                        token_uri=d["token_uri"], client_id=d["client_id"],
                        client_secret=d["client_secret"], scopes=d["scopes"])
    return build("sheets", "v4", credentials=creds)

def get_drive_service():
    token_path = Path(__file__).parent / "google_token.json"
    if not token_path.exists():
        token_path = Path.home() / "AppData" / "Local" / "hermes" / "google_token.json"
    with open(token_path) as f:
        d = json.load(f)
    creds = Credentials(token=d["token"], refresh_token=d["refresh_token"],
                        token_uri=d["token_uri"], client_id=d["client_id"],
                        client_secret=d["client_secret"], scopes=d["scopes"])
    return build("drive", "v3", credentials=creds)

def create_user_spreadsheet(user_name: str) -> str:
    """Copia o template via Drive API e retorna o ID da nova planilha."""
    drive_svc = get_drive_service()
    # Copy template using Drive API
    copy = drive_svc.files().copy(
        fileId=TEMPLATE_SPREADSHEET_ID,
        body={"name": f"FinBot - {user_name}"}
    ).execute()
    new_id = copy["id"]
    return new_id

def get_or_create_month_sheet(spreadsheet_id: str, year_month: str) -> str:
    """Garante que a aba do mês existe. Se não, cria."""
    svc = get_sheets_service()
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for s in meta["sheets"]:
        if s["properties"]["title"] == year_month:
            return year_month
    # Criar a aba
    svc.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
        "requests": [{"addSheet": {"properties": {"title": year_month}}}]
    }).execute()
    # Copiar cabeçalhos do template
    headers = [["DATA", "DESCRIÇÃO", "CATEGORIA", "SUBCATEGORIA", "PAGAMENTO", "VALOR", "CARTÃO", "NECESSÁRIO?", "TIPO", "OBS"]]
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"{year_month}!A1:J1",
        valueInputOption="USER_ENTERED", body={"values": headers}
    ).execute()
    return year_month

def append_gasto(spreadsheet_id: str, year_month: str, row: list):
    svc = get_sheets_service()
    svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"{year_month}!A:J",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]}
    ).execute()

def read_range(spreadsheet_id: str, range_str: str):
    svc = get_sheets_service()
    r = svc.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_str).execute()
    return r.get("values", [])

# ═══════════════════════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════════════════════
def category_keyboard():
    buttons = []
    row = []
    for key, label in CATEGORIES.items():
        row.append(InlineKeyboardButton(label, callback_data=f"cat_{key}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)

def payment_keyboard():
    buttons = [[InlineKeyboardButton(v, callback_data=f"pay_{k}")] for k, v in PAYMENT_METHODS.items()]
    return InlineKeyboardMarkup(buttons)

def yes_no_keyboard(prefix: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sim", callback_data=f"{prefix}_sim"),
         InlineKeyboardButton("❌ Não", callback_data=f"{prefix}_nao")]
    ])

# ═══════════════════════════════════════════════════════
# ONBOARDING
# ═══════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)

    if user and user.get("onboarding_done"):
        # Usuário já cadastrado
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💸 Registrar gasto", callback_data="menu_gasto"),
             InlineKeyboardButton("📊 Resumo", callback_data="menu_resumo")],
            [InlineKeyboardButton("📌 Fixos", callback_data="menu_fixos"),
             InlineKeyboardButton("📅 Parcelas", callback_data="menu_parcelas")],
            [InlineKeyboardButton("🔍 Buscar", callback_data="menu_busca"),
             InlineKeyboardButton("📄 Relatório", callback_data="menu_relatorio")],
        ])
        await update.message.reply_text(
            f"👋 Olá, *{user['name']}*!\n"
            f"💰 Renda: R$ {user['income']:,.2f}\n"
            f"🎯 Objetivo: {user['goal']}\n\n"
            "O que deseja fazer?",
            parse_mode="Markdown", reply_markup=keyboard
        )
        return ConversationHandler.END

    # Novo usuário — onboarding
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
        # Verificar se usuário já existe no DB
        existing_user = get_user(user_id)
        
        if existing_user and existing_user.get("spreadsheet_id"):
            # Usuário já tem planilha - reutilizar
            spreadsheet_id = existing_user["spreadsheet_id"]
            logger.info(f"Onboarding: reutilizando planilha existente {spreadsheet_id} para {data['name']}")
        else:
            # Criar nova planilha apenas se não existir
            logger.info(f"Onboarding: criando nova planilha para {data['name']}")
            spreadsheet_id = create_user_spreadsheet(data["name"])
            logger.info(f"Planilha criada: {spreadsheet_id}")

        # Salvar/atualizar no DB
        logger.info(f"Onboarding: salvando usuário {user_id} no DB")
        upsert_user(
            user_id,
            username=username, first_name=first_name,
            name=data["name"], income=data["income"],
            cards=data["cards"], goal=data["goal"],
            spreadsheet_id=spreadsheet_id,
            onboarding_done=1
        )
        logger.info(f"Onboarding: usuário salvo no DB")

        # Garantir aba do mês atual
        ym = datetime.now().strftime("%Y-%m")
        logger.info(f"Onboarding: criando/verificando aba {ym}")
        get_or_create_month_sheet(spreadsheet_id, ym)
        logger.info(f"Onboarding: aba {ym} verificada")

        await update.message.reply_text(
            f"✅ *Perfil {' restaurado' if existing_user and existing_user.get('spreadsheet_id') else 'criado'}, {data['name']}!*\n\n"
            f"💰 Renda mensal: R$ {data['income']:,.2f}\n"
            f"💳 Cartões: {data['cards']}\n"
            f"🎯 Objetivo: {data['goal']}\n\n"
            f"📊 Sua planilha:\nhttps://docs.google.com/spreadsheets/d/{spreadsheet_id}\n\n"
            f"Use */gasto* para registrar despesas ou */g 50 mercado alimentação pix* para modo rápido!",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Erro no onboarding_goal para user {user_id}: {e}", exc_info=True)
        # Send error as plain text (no Markdown parsing issues)
        err_msg = str(e)[:200]
        await update.message.reply_text(
            f"❌ Erro ao finalizar cadastro: {err_msg}\n"
            f"Tente /start novamente."
        )
        return ConversationHandler.END

# ═══════════════════════════════════════════════════════
# CONVERSATIONAL GASTO
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
        if amount <= 0:
            raise ValueError
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
    await query.edit_message_text(f"📂 Categoria: *{CATEGORIES[cat_key]}*\n\n💳 *Forma de pagamento?*", parse_mode="Markdown", reply_markup=payment_keyboard())
    return PAYMENT

async def gasto_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pay_key = query.data.replace("pay_", "")
    context.user_data["gasto"]["payment"] = pay_key
    # Se for crédito, pergunta o cartão
    if pay_key == "credito":
        user = get_user(update.effective_user.id)
        cards_str = user.get("cards", "") if user else ""
        if cards_str and cards_str.lower() != "nenhum":
            cards = [c.strip() for c in cards_str.split(",")]
            buttons = [[InlineKeyboardButton(c, callback_data=f"card_{c}")] for c in cards]
            buttons.append([InlineKeyboardButton("➕ Outro", callback_data="card_outro")])
            await query.edit_message_text(
                f"💳 Pagamento: *Crédito*\n\n🏦 *Qual cartão?*",
                parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons)
            )
            return CARD_SEL
    # Se não é crédito, pula cartão
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
        await query.edit_message_text("Digite o nome do cartão:")
        # Mudamos para esperar texto
        context.user_data["gasto"]["awaiting_card"] = True
        await query.edit_message_text("🏦 Digite o nome do cartão:")
        return CARD_SEL
    # Check if this is a card selection or text message
    context.user_data["gasto"]["card"] = card
    await query.edit_message_text(
        f"🏦 Cartão: *{card}*\n\n⭐ *Isso era necessário?*",
        parse_mode="Markdown", reply_markup=yes_no_keyboard("nec")
    )
    return NECESSARY

async def gasto_card_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe nome do cartão digitado."""
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
        f"⭐ Necessário: *{nec}*\n\n📝 *Alguma observação?*\nDigite /pular para deixar em branco",
        parse_mode="Markdown"
    )
    return OBS

async def gasto_obs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    obs = update.message.text if update.message.text != "/pular" else ""
    await salvar_gasto(update, context, obs)
    return ConversationHandler.END

async def gasto_quick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Modo rápido: /g 50 mercado alimentação pix nubank"""
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

    valor_str = args[0].replace(",", ".")
    try:
        amount = float(valor_str)
    except ValueError:
        await update.message.reply_text("❌ Valor inválido.")
        return

    desc = args[1]
    cat = args[2].lower()
    pay = args[3].lower() if len(args) > 3 else "pix"
    card = args[4] if len(args) > 4 else ""

    # Validar categoria
    if cat not in CATEGORIES:
        cats = ", ".join(CATEGORIES.keys())
        await update.message.reply_text(f"⚠️ Categoria inválida. Opções: {cats}")
        return

    if pay not in PAYMENT_METHODS:
        pays = ", ".join(PAYMENT_METHODS.keys())
        await update.message.reply_text(f"⚠️ Pagamento inválido. Opções: {pays}")
        return

    context.user_data["gasto"] = {
        "amount": amount, "desc": desc, "category": cat,
        "payment": pay, "card": card, "necessary": "NÃO"
    }
    await salvar_gasto(update, context, "")

async def salvar_gasto(update: Update, context, obs: str):
    g = context.user_data["gasto"]
    user_id = update.effective_user.id
    user = get_user(user_id)
    sid = user["spreadsheet_id"]
    ym = datetime.now().strftime("%Y-%m")
    get_or_create_month_sheet(sid, ym)

    row = [
        datetime.now().strftime("%d/%m/%Y"),
        g["desc"],
        CATEGORIES.get(g["category"], g["category"]).upper(),
        "",
        PAYMENT_METHODS.get(g["payment"], g["payment"]).upper(),
        g["amount"],
        g.get("card", "").upper(),
        g.get("necessary", "NÃO"),
        "CONSUMO",
        obs
    ]
    append_gasto(sid, ym, row)

    # If credit card expense, update/fatüra fatura
    if g["payment"] == "credito":
        try:
            ref_month = ym
            cartao = g.get("card", "").upper()
            if cartao:
                ensure_fatura_sheet(sid)
                existing = get_fatura_row(sid, cartao, ref_month)
                amount = g["amount"]
                if existing:
                    row_idx, row = existing
                    current_total = float(row[2]) if len(row) > 2 and row[2] else 0.0
                    new_total = current_total + amount
                    update_fatura_cell(sid, row_idx, "C", f"{new_total:.2f}")
                    due_date = row[3] if len(row) > 3 and row[3] else ""
                    if not due_date:
                        y, m = map(int, ref_month.split("-"))
                        if m == 12:
                            next_m = 1
                            next_y = y + 1
                        else:
                            next_m = m + 1
                            next_y = y
                        import calendar
                        last_day = calendar.monthrange(next_y, next_m)[1]
                        due_date = f"{last_day:02d}/{next_m:02d}/{next_y}"
                        update_fatura_cell(sid, row_idx, "D", due_date)
                else:
                    y, m = map(int, ref_month.split("-"))
                    if m == 12:
                        next_m = 1
                        next_y = y + 1
                    else:
                        next_m = m + 1
                        next_y = y
                    import calendar
                    last_day = calendar.monthrange(next_y, next_m)[1]
                    due_date = f"{last_day:02d}/{next_m:02d}/{next_y}"
                    new_row = [cartao, ref_month, f"{amount:.2f}", due_date, "NAO", "0.00", "", ""]
                    append_fatura_row(sid, new_row)
        except Exception as e:
            logger.error(f"Erro ao atualizar fatura: {e}")

    # Atualizar streak
    today = datetime.now().strftime("%Y-%m-%d")
    last = user.get("last_gasto_date", "")
    if last and last != today:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        if last == yesterday:
            new_streak = (user.get("streak", 0) or 0) + 1
        else:
            new_streak = 1
    else:
        new_streak = 1
    upsert_user(user_id, last_gasto_date=today, streak=new_streak)

    # Responder
    msg_parts = [
        f"✅ *R$ {g['amount']:,.2f}* — {g['desc']}",
        f"📂 {CATEGORIES.get(g['category'], g['category'])}",
        f"💳 {PAYMENT_METHODS.get(g['payment'], g['payment'])}",
    ]
    if g.get("card"):
        msg_parts.append(f"🏦 {g['card']}")
    if obs:
        msg_parts.append(f"📝 {obs}")
    msg_parts.append(f"🔥 Streak: {new_streak} dias")

    # Tentar mandar reply ou edit
    if update.callback_query:
        await update.callback_query.edit_message_text("\n".join(msg_parts), parse_mode="Markdown")
    else:
        await update.message.reply_text("\n".join(msg_parts), parse_mode="Markdown")


# ═══════════════════════════════════════════════════════
# UTILS
# ═══════════════════════════════════════════════════════
def ensure_user(update: Update):
    user_id = update.effective_user.id
    user = get_user(user_id)
    return user and user.get("onboarding_done")

# ═══════════════════════════════════════════════════════
# COMANDOS RÁPIDOS
# ═══════════════════════════════════════════════════════
async def cmd_resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro."); return
    logger.info(f"/resumo chamado por user {update.effective_user.id}")
    user = get_user(update.effective_user.id)
    sid = user["spreadsheet_id"]
    ym = datetime.now().strftime("%Y-%m")
    try:
        data = read_range(sid, f"{ym}!A1:J200")
    except Exception as e:
        logger.error(f"Erro read_range: {e}")
        await update.message.reply_text("❌ Erro ao ler planilha")
        return
    if len(data) <= 1:
        await update.message.reply_text("📊 Nenhum gasto registrado esse mês.")
        return
    total = sum(float(r[5]) for r in data[1:] if len(r) > 5 and r[5])
    cats = {}
    for r in data[1:]:
        if len(r) > 5 and r[2] and r[5]:
            cat = r[2]
            val = float(r[5])
            cats[cat] = cats.get(cat, 0) + val
    lines = [f"📊 *Resumo {datetime.now().strftime('%B/%Y')}*", f"💰 Total: R$ {total:,.2f}", f"📂 {len(data)-1} gastos", ""]
    for cat, val in sorted(cats.items(), key=lambda x: -x[1]):
        bar_len = int(val / total * 15) if total > 0 else 0
        bar = "█" * bar_len + "░" * (15 - bar_len)
        lines.append(f"{bar} {cat[:20]}: R$ {val:,.2f}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_fixos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_user(update): return
    await update.message.reply_text("📌 *Em breve:* gerenciamento completo de gastos fixos. Por enquanto edite direto na planilha.", parse_mode="Markdown")

async def cmd_parcelas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_user(update): return
    await update.message.reply_text("📅 *Em breve:* gerenciamento completo de parcelamentos.", parse_mode="Markdown")

async def cmd_limite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_user(update): return
    logger.info(f"/limite chamado por user {update.effective_user.id}")
    try:
        user = get_user(update.effective_user.id)
        logger.info(f"User encontrado: {user['name']}, income={user['income']}")
        income = user["income"]
        sid = user["spreadsheet_id"]
        logger.info(f"Spreadsheet ID: {sid}")
        ym = datetime.now().strftime("%Y-%m")
        logger.info(f"Lendo aba {ym}")
        data = read_range(sid, f"{ym}!A1:J200")
        logger.info(f"Dados lidos: {len(data)} linhas")
        total = sum(float(r[5]) for r in data[1:] if len(r) > 5 and r[5]) if len(data) > 1 else 0
        logger.info(f"Total calculado: {total}")

        day_of_month = datetime.now().day
        days_left = 30 - day_of_month
        saldo = income - total
        limite_diario = saldo / max(days_left, 1)

        await update.message.reply_text(
            f"💸 *Controle Financeiro*\n\n"
            f"📥 Receita: R$ {income:,.2f}\n"
            f"📤 Gastos: R$ {total:,.2f}\n"
            f"💰 Saldo: R$ {saldo:,.2f}\n"
            f"📅 Dias restantes: {days_left}\n"
            f"🎯 Limite diário: R$ {limite_diario:,.2f}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Erro cmd_limite: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Erro ao calcular limite: {str(e)[:200]}")

async def cmd_novomes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_user(update): return
    user = get_user(update.effective_user.id)
    ym = datetime.now().strftime("%Y-%m")
    get_or_create_month_sheet(user["spreadsheet_id"], ym)
    await update.message.reply_text(
        f"✅ Planilha *{ym}* pronta!\n"
        f"https://docs.google.com/spreadsheets/d/{user['spreadsheet_id']}",
        parse_mode="Markdown"
    )


# ════════════════════════════════════════════════════════
# FATURA HANDLING (Global - Nível do Módulo)
# ════════════════════════════════════════════════════════
def get_fatura_service():
    # Reuse sheets service
    return get_sheets_service()

def ensure_fatura_sheet(spreadsheet_id: str):
    svc = get_fatura_service()
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheets = meta.get("sheets", [])
    if any(s["properties"]["title"] == "FATURAS" for s in sheets):
        return
    # Add sheet
    request = {
        "addSheet": {
            "properties": {
                "title": "FATURAS",
                "gridProperties": {
                    "rowCount": 1000,
                    "columnCount": 8
                }
            }
        }
    }
    svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [request]}
    ).execute()
    # Add headers
    headers = [["CARTÃO", "REF_MÊS", "TOTAL", "VENCIMENTO", "PAGO", "VALOR_PAGO", "DATA_PAGAMENTO", "OBS"]]
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="FATURAS!A1:H1",
        valueInputOption="USER_ENTERED",
        body={"values": headers}
    ).execute()

def get_fatura_row(spreadsheet_id: str, cartao: str, ref_month: str):
    svc = get_fatura_service()
    # Ensure sheet exists
    ensure_fatura_sheet(spreadsheet_id)
    # Get all rows
    result = svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range="FATURAS!A:H"
    ).execute()
    values = result.get("values", [])
    if not values:
        return None
    # Skip header
    for idx, row in enumerate(values[1:], start=2):  # row index in sheet (1-based)
        if len(row) >= 2 and row[0] == cartao and row[1] == ref_month:
            return idx, row
    return None

def update_fatura_cell(spreadsheet_id: str, row_idx: int, col_letter: str, value):
    svc = get_fatura_service()
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"FATURAS!{col_letter}{row_idx}",
        valueInputOption="USER_ENTERED",
        body={"values": [[value]]}
    ).execute()

def append_fatura_row(spreadsheet_id: str, row: list):
    svc = get_fatura_service()
    ensure_fatura_sheet(spreadsheet_id)
    svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range="FATURAS!A:H",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]}
    ).execute()

async def cmd_fatura(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_user(update): return
    user = get_user(update.effective_user.id)
    sid = user["spreadsheet_id"]
    svc = get_fatura_service()
    ensure_fatura_sheet(sid)
    result = svc.spreadsheets().values().get(
        spreadsheetId=sid,
        range="FATURAS!A:H"
    ).execute()
    values = result.get("values", [])
    if not values or len(values) == 1:
        await update.message.reply_text("📄 Nenhuma fatura registrada.")
        return
    # Skip header
    rows = values[1:]
    open_rows = [r for r in rows if len(r) >= 5 and r[4].upper() != "SIM"]
    if not open_rows:
        await update.message.reply_text("✅ Todas as faturas estão pagas.")
        return
    lines = ["📄 *Faturas em aberto*\n"]
    for r in open_rows:
        cartao = r[0] if len(r) > 0 else ""
        ref = r[1] if len(r) > 1 else ""
        total = r[2] if len(r) > 2 else "0"
        venc = r[3] if len(r) > 3 else ""
        lines.append(f"• {cartao} ({ref}): R$ {total} – Venc: {venc}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_pagar_fatura(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_user(update): return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "❌ Uso: /pagar_fatura <cartão> <ref_mês> <valor>\n"
            "Ex: /pagar_fatura Nubank 2026-06 1234,56"
        )
        return
    cartao = args[0]
    ref_month = args[1]
    try:
        valor = float(args[2].replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ Valor inválido.")
        return
    user = get_user(update.effective_user.id)
    sid = user["spreadsheet_id"]
    svc = get_fatura_service()
    ensure_fatura_sheet(sid)
    res = get_fatura_row(sid, cartao, ref_month)
    if not res:
        await update.message.reply_text(f"❌ Fatura não encontrada para {cartao} / {ref_month}.")
        return
    row_idx, row = res
    # Mark as paid
    update_fatura_cell(sid, row_idx, "E", "SIM")  # PAGO column (5th column = E)
    update_fatura_cell(sid, row_idx, "F", f"{valor:.2f}")  # VALOR_PAGO
    update_fatura_cell(sid, row_idx, "G", datetime.now().strftime("%d/%m/%Y"))  # DATA_PAGAMENTO
    await update.message.reply_text(
        f"✅ Fatura de {cartao} ({ref_month}) paga no valor de R$ {valor:,.2f}."
    )

# ═══════════════════════════════════════════════════════
# MENU CALLBACKS
# ═══════════════════════════════════════════════════════
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cmd = query.data
    if cmd in ("menu_resumo",):
        # Redireciona para o comando
        await query.edit_message_text("📊 Carregando resumo...")
    await query.edit_message_text("✅ Funcionalidade em desenvolvimento. Use os comandos diretos por enquanto.")

# ═══════════════════════════════════════════════════════
# NOTIFICAÇÕES INTELIGENTES
# ═══════════════════════════════════════════════════════
async def notify_all_users(context: ContextTypes.DEFAULT_TYPE, notif_type: str, msg_template: str):
    """Envia notificação para todos os usuários cadastrados."""
    with sqlite3.connect(DB_PATH) as conn:
        users = conn.execute("SELECT user_id FROM users WHERE onboarding_done=1").fetchall()
    for (uid,) in users:
        try:
            await context.bot.send_message(uid, msg_template, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Falha ao notificar {uid}: {e}")

async def weekly_summary(context: ContextTypes.DEFAULT_TYPE):
    """Resumo semanal — segunda-feira 9h."""
    with sqlite3.connect(DB_PATH) as conn:
        users = conn.execute("SELECT user_id, spreadsheet_id, income, name FROM users WHERE onboarding_done=1").fetchall()

    for uid, sid, income, name in users:
        try:
            ym = datetime.now().strftime("%Y-%m")
            data = read_range(sid, f"{ym}!A1:J200")
            if len(data) <= 1:
                continue

            # Gastos dos últimos 7 dias
            week_ago = (datetime.now() - timedelta(days=7)).strftime("%d/%m/%Y")
            week_total = 0
            week_cats = {}
            for r in data[1:]:
                if len(r) > 5 and r[0] and r[5]:
                    try:
                        gasto_date = datetime.strptime(r[0], "%d/%m/%Y")
                        if gasto_date >= datetime.now() - timedelta(days=7):
                            val = float(r[5])
                            week_total += val
                            cat = r[2] if len(r) > 2 and r[2] else "OUTROS"
                            week_cats[cat] = week_cats.get(cat, 0) + val
                    except:
                        pass

            if week_total == 0:
                continue

            top = sorted(week_cats.items(), key=lambda x: -x[1])[:3]
            lines = [
                f"📊 *Resumo Semanal — {name}*",
                f"💰 Total: R$ {week_total:,.2f}",
                f"📂 Top categorias:",
            ]
            for cat, val in top:
                lines.append(f"  • {cat}: R$ {val:,.2f}")

            # Verificar se passou 50% da renda
            if week_total > income * 0.5:
                lines.append(f"\n⚠️ Você já gastou {week_total/income*100:.0f}% da sua renda essa semana!")

            await context.bot.send_message(uid, "\n".join(lines), parse_mode="Markdown")

        except Exception as e:
            logger.error(f"Erro weekly_summary para {uid}: {e}")

async def spending_spike_alert(context: ContextTypes.DEFAULT_TYPE):
    """Alerta de aumento anormal — diário às 18h."""
    with sqlite3.connect(DB_PATH) as conn:
        users = conn.execute("SELECT user_id, spreadsheet_id FROM users WHERE onboarding_done=1").fetchall()

    for uid, sid in users:
        try:
            ym = datetime.now().strftime("%Y-%m")
            data = read_range(sid, f"{ym}!A1:J200")
            if len(data) <= 5:
                continue

            # Comparar essa semana vs semana passada
            now = datetime.now()
            this_week = {}
            last_week = {}

            for r in data[1:]:
                if len(r) > 5 and r[0] and r[5] and r[2]:
                    try:
                        d = datetime.strptime(r[0], "%d/%m/%Y")
                        val = float(r[5])
                        cat = r[2]
                        if d >= now - timedelta(days=7):
                            this_week[cat] = this_week.get(cat, 0) + val
                        elif d >= now - timedelta(days=14):
                            last_week[cat] = last_week.get(cat, 0) + val
                    except:
                        pass

            # Detectar spikes > 50%
            alerts = []
            for cat, curr in this_week.items():
                prev = last_week.get(cat, 0)
                if prev > 0 and curr > prev * 1.5:
                    pct = int((curr / prev - 1) * 100)
                    alerts.append(f"🚨 *{cat}* subiu {pct}%: R$ {prev:,.2f} → R$ {curr:,.2f}")

            if alerts:
                await context.bot.send_message(
                    uid,
                    f"⚠️ *Alertas de gastos — {name if (name := get_user(uid)) else ''}*\n\n" + "\n".join(alerts),
                    parse_mode="Markdown"
                )

        except Exception as e:
            logger.error(f"Erro spike_alert para {uid}: {e}")

async def budget_warning(context: ContextTypes.DEFAULT_TYPE):
    """Alerta de orçamento estourado — diário às 10h."""
    with sqlite3.connect(DB_PATH) as conn:
        users = conn.execute("SELECT user_id, spreadsheet_id, income FROM users WHERE onboarding_done=1").fetchall()

    for uid, sid, income in users:
        try:
            ym = datetime.now().strftime("%Y-%m")
            data = read_range(sid, f"{ym}!A1:J200")
            total = sum(float(r[5]) for r in data[1:] if len(r) > 5 and r[5]) if len(data) > 1 else 0
            pct = total / income * 100 if income > 0 else 0

            if pct >= 80:
                days_left = 30 - datetime.now().day
                limite_diario = (income - total) / max(days_left, 1)
                await context.bot.send_message(
                    uid,
                    f"🔴 *Alerta de orçamento!*\n\n"
                    f"Gasto: R$ {total:,.2f} de R$ {income:,.2f} ({pct:.0f}%)\n"
                    f"Restam {days_left} dias no mês\n"
                    f"Limite diário: R$ {limite_diario:,.2f}\n\n"
                    f"⚠️ Cuidado com gastos extras!",
                    parse_mode="Markdown"
                )

        except Exception as e:
            logger.error(f"Erro budget_warning para {uid}: {e}")

async def streak_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Lembrete de streak — diário às 20h se não registrou hoje."""
    with sqlite3.connect(DB_PATH) as conn:
        users = conn.execute(
            "SELECT user_id, name, streak FROM users WHERE onboarding_done=1 AND last_gasto_date != ?",
            (datetime.now().strftime("%Y-%m-%d"),)
        ).fetchall()

    for uid, name, streak in users:
        try:
            await context.bot.send_message(
                uid,
                f"🔥 *{name}, não esqueça de registrar seus gastos hoje!*\n"
                f"Streak atual: {streak or 0} dias. Não perca a sequência!",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Falha streak_reminder para {uid}: {e}")

async def monthly_reset(context: ContextTypes.DEFAULT_TYPE):
    """Cria aba do novo mês — dia 1 às 00:05."""
    ym = datetime.now().strftime("%Y-%m")
    with sqlite3.connect(DB_PATH) as conn:
        users = conn.execute("SELECT user_id, spreadsheet_id, name FROM users WHERE onboarding_done=1").fetchall()

    for uid, sid, name in users:
        try:
            get_or_create_month_sheet(sid, ym)
            await context.bot.send_message(
                uid,
                f"📅 *Novo mês: {ym}*\n"
                f"Sua planilha está pronta! Bons hábitos financeiros esse mês, {name}! 💪",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Erro monthly_reset para {uid}: {e}")

# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    # ── Job Queue (notificações) ──
    scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(lambda: None, CronTrigger(day_of_week="mon", hour=9), args=[], id="weekly")
    app.job_queue.run_repeating(weekly_summary, interval=604800, first=10, name="weekly_summary")  # ~7 dias

    # Alerta de orçamento: todo dia às 10h
    app.job_queue.run_repeating(budget_warning, interval=86400, first=30, name="budget_warning")

    # Alerta de spike: todo dia às 18h
    app.job_queue.run_repeating(spending_spike_alert, interval=86400, first=60, name="spike_alert")

    # Lembrete streak: todo dia às 20h
    app.job_queue.run_repeating(streak_reminder, interval=86400, first=90, name="streak_reminder")

    # Reset mensal: dia 1
    app.job_queue.run_repeating(monthly_reset, interval=86400, first=120, name="monthly_reset")

    # Onboarding
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

    # Gasto conversacional
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
            OBS: [MessageHandler(filters.TEXT & ~filters.COMMAND, gasto_obs)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)]
    )

    app.add_handler(onboarding_conv)
    app.add_handler(gasto_conv)
    app.add_handler(CommandHandler("g", gasto_quick))
    app.add_handler(CommandHandler("resumo", cmd_resumo))
    app.add_handler(CommandHandler("fixos", cmd_fixos))
    app.add_handler(CommandHandler("parcelas", cmd_parcelas))
    app.add_handler(CommandHandler("limite", cmd_limite))
    app.add_handler(CommandHandler("novomes", cmd_novomes))
    app.add_handler(CommandHandler("fatura", cmd_fatura))
    app.add_handler(CommandHandler("pagar_fatura", cmd_pagar_fatura))
    app.add_handler(CallbackQueryHandler(menu_handler, pattern="^menu_"))

    # Error handler
    app.add_error_handler(error_handler)
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler
    port = int(os.environ.get("PORT", 8080))

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"FinBot OK\n")

        def log_message(self, format, *args):
            pass

    http_server = HTTPServer(("0.0.0.0", port), HealthHandler)
    http_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    http_thread.start()

    logger.info(f"🤖 FinBot iniciado na porta {port}")
    # Run polling in MAIN thread (required for signal handlers)
    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()
