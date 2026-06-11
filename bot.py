#!/usr/bin/env python3
"""
FinBot — Gestão Financeira via Telegram + Google Sheets
Multi-user, onboarding conversacional, SQLite, notificações.
"""
import os, json, sqlite3, logging, re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

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
# GOOGLE SHEETS
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

def create_user_spreadsheet(user_name: str) -> str:
    """Copia o template e retorna o ID da nova planilha."""
    svc = get_sheets_service()
    # Copy template
    copy = svc.spreadsheets().copy(
        spreadsheetId=TEMPLATE_SPREADSHEET_ID,
        body={"name": f"FinBot - {user_name}"}
    ).execute()
    new_id = copy["spreadsheetId"]
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

    # Criar planilha pessoal
    spreadsheet_id = create_user_spreadsheet(data["name"])

    # Salvar no DB
    upsert_user(
        user_id,
        username=username, first_name=first_name,
        name=data["name"], income=data["income"],
        cards=data["cards"], goal=data["goal"],
        spreadsheet_id=spreadsheet_id,
        onboarding_done=1
    )

    # Criar aba do mês atual
    ym = datetime.now().strftime("%Y-%m")
    get_or_create_month_sheet(spreadsheet_id, ym)

    await update.message.reply_text(
        f"✅ *Perfil criado, {data['name']}!*\n\n"
        f"💰 Renda mensal: R$ {data['income']:,.2f}\n"
        f"💳 Cartões: {data['cards']}\n"
        f"🎯 Objetivo: {data['goal']}\n\n"
        f"📊 Sua planilha:\nhttps://docs.google.com/spreadsheets/d/{spreadsheet_id}\n\n"
        f"Use */gasto* para registrar despesas ou */g 50 mercado alimentação pix* para modo rápido!",
        parse_mode="Markdown"
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
    user = get_user(update.effective_user.id)
    sid = user["spreadsheet_id"]
    ym = datetime.now().strftime("%Y-%m")
    data = read_range(sid, f"{ym}!A1:J200")
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
    user = get_user(update.effective_user.id)
    income = user["income"]
    sid = user["spreadsheet_id"]
    ym = datetime.now().strftime("%Y-%m")
    data = read_range(sid, f"{ym}!A1:J200")
    total = sum(float(r[5]) for r in data[1:] if len(r) > 5 and r[5]) if len(data) > 1 else 0

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
        # Simula chamada do comando
    await query.edit_message_text("✅ Funcionalidade em desenvolvimento. Use os comandos diretos por enquanto.")

# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

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
    app.add_handler(CallbackQueryHandler(menu_handler, pattern="^menu_"))

    # Start polling in background thread
    import threading
    poll_thread = threading.Thread(
        target=app.run_polling,
        kwargs={"drop_pending_updates": True, "close_loop": False},
        daemon=True
    )
    poll_thread.start()

    # Mini HTTP server for Render health check
    from http.server import HTTPServer, BaseHTTPRequestHandler
    port = int(os.environ.get("PORT", 8080))

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"FinBot OK\n")

        def log_message(self, format, *args):
            pass  # silence HTTP logs

    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"🤖 FinBot iniciado na porta {port}")
    server.serve_forever()

if __name__ == "__main__":
    main()
