"""FinBot - busca.py (split de bot.py)."""
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from finbot.db import get_user
from finbot.sheets import parse_float, read_range
from finbot.keyboards import main_menu_keyboard
from finbot.handlers.common import ensure_user


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

