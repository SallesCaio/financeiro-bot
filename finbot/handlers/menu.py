"""FinBot - menu.py (split de bot.py)."""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from finbot.config import logger
from finbot.db import get_user
from finbot.keyboards import main_menu_keyboard
from finbot.handlers.relatorios import cmd_relatorio_completo, cmd_relatorio_fixos, cmd_relatorio_parcelamentos, cmd_relatorio_resumo


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

