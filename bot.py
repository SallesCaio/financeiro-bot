"""
Bot Telegram - Controle Financeiro
Conecta ao Google Sheets para lançamentos e consultas.
"""
import os
import json
import logging
from datetime import datetime
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ── Config ────────────────────────────────────────────────
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1m-GTVEJcqzzEBoslIJ5OpeSPj1HJnd3U-6m3JCH_uv8")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Sheets ────────────────────────────────────────────────
def get_sheets_service():
    """Build Google Sheets service from stored credentials."""
    token_path = Path(__file__).parent / "google_token.json"
    if not token_path.exists():
        token_path = Path.home() / "AppData" / "Local" / "hermes" / "google_token.json"

    with open(token_path) as f:
        token_data = json.load(f)

    creds = Credentials(
        token=token_data["token"],
        refresh_token=token_data["refresh_token"],
        token_uri=token_data["token_uri"],
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=token_data["scopes"],
    )
    return build("sheets", "v4", credentials=creds)


def read_sheet(sheet_name: str, range_str: str):
    service = get_sheets_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{sheet_name}!{range_str}"
    ).execute()
    return result.get("values", [])


def append_row(sheet_name: str, values: list):
    service = get_sheets_service()
    body = {"values": [values]}
    return service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{sheet_name}!A:Z",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body=body,
    ).execute()


# ── Comandos ──────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 *Financeiro Bot*\n\n"
        "Comandos disponíveis:\n"
        "/gasto \\<valor> \\<descrição> \\<categoria> \\[pagamento] \\[cartão] — Registrar gasto\n"
        "/resumo — Resumo financeiro\n"
        "/fixos — Gastos fixos mensais\n"
        "/parcelas — Parcelamentos pendentes\n"
        "/limite — Saldo livre e limite semanal\n"
        "/categorias — Gastos por categoria\n\n"
        "Exemplo:\n/gasto 50 Mercado Alimentação pix nubank",
        parse_mode="Markdown",
    )


async def gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registrar um gasto: /gasto 50 mercado alimentação pix nubank"""
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "❌ Formato: /gasto <valor> <descrição> <categoria> [pagamento] [cartão]\n"
            "Ex: /gasto 50 Mercado Alimentação pix nubank"
        )
        return

    valor = args[0].replace(",", ".")
    try:
        valor_float = float(valor)
    except ValueError:
        await update.message.reply_text("❌ Valor inválido. Use: 50 ou 50,90")
        return

    descricao = args[1]
    categoria = args[2].upper()
    pagamento = args[3].upper() if len(args) > 3 else "PIX"
    cartao = args[4].upper() if len(args) > 4 else ""

    # Mapear categorias válidas
    categorias_validas = [
        "ALIMENTAÇÃO", "MOTO", "PESSOAL", "ASSINATURAS", "DIVIDAS",
        "DELIVERY", "SAÚDE", "EDUCAÇÃO", "FATURA CARTÃO", "MORADIA", "OUTROS"
    ]

    if categoria not in categorias_validas:
        cats = ", ".join(categorias_validas)
        await update.message.reply_text(
            f"⚠️ Categoria '{categoria}' não reconhecida.\nVálidas: {cats}"
        )
        return

    data = datetime.now().strftime("%d/%m/%Y")
    row = [data, descricao, categoria, "", pagamento, valor_float, cartao, "NÃO", "CONSUMO", ""]

    try:
        append_row("DADOS", row)
        await update.message.reply_text(
            f"✅ *R$ {valor_float:,.2f}* — {descricao} ({categoria})\n"
            f"💳 {pagamento}" + (f" — {cartao}" if cartao else ""),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Erro ao registrar: {e}")
        await update.message.reply_text(f"❌ Erro ao salvar: {e}")


async def resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar resumo financeiro."""
    try:
        data = read_sheet("RESUMO", "A1:B31")
        lines = ["📊 *Resumo Financeiro*\n"]
        for row in data:
            if len(row) >= 2 and row[0] and row[1]:
                lines.append(f"• *{row[0]}*: {row[1]}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {e}")


async def fixos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Listar gastos fixos mensais."""
    try:
        data = read_sheet("FIXOS", "A1:D16")
        lines = ["📌 *Gastos Fixos Mensais*\n"]
        total = 0
        for row in data[1:]:  # skip header
            if len(row) >= 4 and row[0]:
                try:
                    val = float(row[3].replace(",", ".")) if isinstance(row[3], str) else float(row[3])
                except (ValueError, TypeError):
                    val = 0
                total += val
                lines.append(f"• {row[0]} — R$ {val:,.2f}")
        lines.append(f"\n💰 *Total fixos: R$ {total:,.2f}*")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {e}")


async def parcelas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar parcelamentos pendentes."""
    try:
        data = read_sheet("PARCELAMENTOS", "A1:G15")
        lines = ["📅 *Parcelamentos*\n"]
        for row in data[1:]:
            if len(row) >= 7 and row[1]:
                code = row[0]
                desc = row[1]
                rest = row[4] if len(row) > 4 else ""
                saldo = row[6] if len(row) > 6 else ""
                if rest and saldo and rest != "0":
                    lines.append(f"*{desc}* — {rest} restantes — R$ {saldo}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {e}")


async def limite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar saldo livre e limite semanal."""
    try:
        data = read_sheet("RESUMO", "A1:B31")
        saldo = None
        limite_val = None
        receita = None
        for row in data:
            if len(row) >= 2:
                if "SALDO LIVRE REAL" in str(row[0]).upper():
                    saldo = row[1]
                elif "LIMITE SEMANAL" in str(row[0]).upper():
                    limite_val = row[1]
                elif "RECEITA PREVISTA" in str(row[0]).upper():
                    receita = row[1]

        msg = ["💸 *Controle*\n"]
        if receita:
            msg.append(f"📥 Receita: R$ {receita}")
        if saldo:
            msg.append(f"💰 Saldo livre: R$ {saldo}")
        if limite_val:
            msg.append(f"📅 Limite semanal: R$ {limite_val}")
        await update.message.reply_text("\n".join(msg), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {e}")


async def categorias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar gastos por categoria."""
    try:
        data = read_sheet("RESUMO", "A1:B31")
        lines = ["📂 *Gastos por Categoria*\n"]
        in_cat = False
        for row in data:
            if len(row) >= 2:
                if "CATEGORIAS" in str(row[0]).upper():
                    in_cat = True
                    continue
                if in_cat and row[0] and row[1]:
                    if "TOTAL" in str(row[0]).upper():
                        lines.append(f"• *{row[0]}*: {row[1]}")
                    else:
                        continue
                elif in_cat and not row[0]:
                    break
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {e}")


# ── Main ──────────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gasto", gasto))
    app.add_handler(CommandHandler("resumo", resumo))
    app.add_handler(CommandHandler("fixos", fixos))
    app.add_handler(CommandHandler("parcelas", parcelas))
    app.add_handler(CommandHandler("limite", limite))
    app.add_handler(CommandHandler("categorias", categorias))

    logger.info("Bot iniciado...")
    app.run_polling()


if __name__ == "__main__":
    main()
