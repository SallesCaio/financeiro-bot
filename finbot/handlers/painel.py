"""FinBot - painel.py (split de bot.py)."""
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from finbot.config import logger
from finbot.auth import get_sheets_service
from finbot.db import get_user
from finbot.sheets import ensure_fatura_sheet, get_fatura_row, get_or_create_month_sheet, parse_float, read_range, update_fatura_cell
from finbot.keyboards import main_menu_keyboard
from finbot.handlers.common import ensure_user


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

