"""FinBot - common.py (split de bot.py)."""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from finbot.db import get_user


# ═══════════════════════════════════════════════════════
# UTILS
# ═══════════════════════════════════════════════════════
def ensure_user(update: Update):
    user_id = update.effective_user.id
    user = get_user(user_id)
    return user and user.get("onboarding_done")



