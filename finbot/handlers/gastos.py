"""FinBot - gastos.py (split de bot.py)."""
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from finbot.config import AMOUNT, CARD_SEL, CATEGORIES, CATEGORY, DESC, INSTALMENT_QTY, IS_INSTALMENT, IS_SUBSCRIPTION, NECESSARY, OBS, PAYMENT, PAYMENT_METHODS, SUBSCRIPTION_NAME, SUBSCRIPTION_VALOR, logger
from finbot.db import get_user, upsert_user
from finbot.sheets import _calc_prox_ref_month, append_fixo, append_gasto, append_parcela, ensure_fixos_sheet, ensure_parcelas_sheet, get_or_create_month_sheet, update_fatura_total
from finbot.keyboards import category_keyboard, main_menu_keyboard, payment_keyboard, yes_no_keyboard
from finbot.handlers.common import ensure_user


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

