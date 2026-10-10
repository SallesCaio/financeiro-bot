"""FinBot - cadastros.py (split de bot.py)."""
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from finbot.config import CATEGORIES, FIXO_CATEGORIA, FIXO_DIA, FIXO_NOME, FIXO_VALOR, META_CATEGORIA_META, META_NOME, META_TARGET, PARC_CATEGORIA, PARC_NOME, PARC_NPARC, PARC_TOTAL, PARC_VALOR_PARC
from finbot.db import get_metas_from_db, get_user, upsert_meta_db
from finbot.sheets import append_fixo, append_meta, append_parcela, read_fixos, read_metas, read_parcelas
from finbot.keyboards import category_keyboard, main_menu_keyboard
from finbot.handlers.common import ensure_user


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

