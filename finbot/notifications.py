"""FinBot - notifications.py (split de bot.py)."""
from datetime import datetime, timedelta
from finbot.config import logger
from finbot.db import get_all_users
from finbot.sheets import get_or_create_month_sheet, parse_float, read_range


# ═══════════════════════════════════════════════════════
# NOTIFICAÇÕES (2 tipos implementados com cron real)
# ═══════════════════════════════════════════════════════
async def budget_warning(context: ContextTypes.DEFAULT_TYPE):
    """Alerta de orçamento — todo dia às 10h BRT."""
    users = get_all_users()
    for user in users:
        try:
            ym = datetime.now().strftime("%Y-%m")
            data = read_range(user["spreadsheet_id"], f"{ym}!A1:J200")
            total = sum(parse_float(r[5]) for r in data[1:] if len(r) > 5 and r[5]) if len(data) > 1 else 0
            pct = total / user["income"] * 100 if user["income"] > 0 else 0

            if pct >= 80:
                days_left = 30 - datetime.now().day
                limite = (user["income"] - total) / max(days_left, 1)
                await context.bot.send_message(
                    user["user_id"],
                    f"🔴 *Alerta de orçamento!*\n\n"
                    f"Gasto: R$ {total:,.2f} de R$ {user['income']:,.2f} ({pct:.0f}%)\n"
                    f"Restam {days_left} dias\nLimite diário: R$ {limite:,.2f}\n\n⚠️ Atenção!",
                    parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Erro budget_warning user {user['user_id']}: {e}")

async def lembrete_registro(context: ContextTypes.DEFAULT_TYPE):
    """Lembrete diário de registro de gastos — todo dia às 20h BRT."""
    users = get_all_users()
    today = datetime.now().strftime("%Y-%m-%d")
    for user in users:
        try:
            if user.get("last_gasto_date") != today:
                await context.bot.send_message(
                    user["user_id"],
                    f"🔥 *{user['name']}, não esqueça de registrar seus gastos hoje!*",
                    parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Erro lembrete user {user['user_id']}: {e}")

async def monthly_reset(context: ContextTypes.DEFAULT_TYPE):
    """Cria aba do novo mês — dia 1 às 00:05 BRT."""
    ym = datetime.now().strftime("%Y-%m")
    users = get_all_users()
    for user in users:
        try:
            get_or_create_month_sheet(user["spreadsheet_id"], ym)
            await context.bot.send_message(
                user["user_id"],
                f"📅 *Novo mês: {ym}*\n"
                f"Sua planilha está pronta! Bons hábitos financeiros! 💪",
                parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Erro monthly_reset user {user['user_id']}: {e}")

