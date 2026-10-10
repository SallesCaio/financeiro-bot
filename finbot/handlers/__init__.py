"""FinBot - __init__.py (split de bot.py)."""
from datetime import datetime, timedelta
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from finbot.config import AMOUNT, CARDS, CARD_SEL, CATEGORY, DESC, FIXO_CATEGORIA, FIXO_DIA, FIXO_NOME, FIXO_VALOR, GOAL, INCOME, INSTALMENT_QTY, IS_INSTALMENT, IS_SUBSCRIPTION, NAME, NECESSARY, OBS, PARC_CATEGORIA, PARC_NOME, PARC_NPARC, PARC_TOTAL, PARC_VALOR_PARC, PAYMENT, SUBSCRIPTION_NAME, SUBSCRIPTION_VALOR, TOKEN, logger
from finbot.notifications import budget_warning, lembrete_registro, monthly_reset
from finbot.handlers.onboarding import onboarding_cards, onboarding_goal, onboarding_income, onboarding_name, start
from finbot.handlers.gastos import gasto_amount, gasto_card, gasto_card_text, gasto_category, gasto_desc, gasto_instalment_qty, gasto_is_instalment, gasto_is_subscription, gasto_necessary, gasto_obs, gasto_obs_pular, gasto_payment, gasto_quick, gasto_start, gasto_subscription_name, gasto_subscription_valor
from finbot.handlers.painel import cmd_fatura, cmd_limite, cmd_novomes, cmd_pagar_fatura, cmd_resumo
from finbot.handlers.cadastros import cmd_fixo, cmd_parcela, fixo_categoria, fixo_dia, fixo_nome, fixo_valor, parcela_categoria, parcela_nome, parcela_nparc, parcela_total, parcela_valor_parc
from finbot.handlers.busca import cmd_busca
from finbot.handlers.relatorios import cmd_insights, cmd_relatorio, cmd_relatorio_completo, cmd_relatorio_fixos, cmd_relatorio_parcelamentos, cmd_relatorio_resumo
from finbot.handlers.conta import cmd_perfil, cmd_receita
from finbot.handlers.compras import cmd_compras
from finbot.handlers.menu import error_handler, menu_handler


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



def build_app():
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
    return app
