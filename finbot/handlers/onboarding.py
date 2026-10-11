"""FinBot - onboarding.py (split de bot.py)."""
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from finbot.config import CARDS, GOAL, INCOME, NAME, logger
from finbot.db import get_user, upsert_user
from finbot.sheets import create_user_spreadsheet, get_or_create_month_sheet, save_user_to_master
from finbot.keyboards import main_menu_keyboard


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
