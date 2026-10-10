"""FinBot - keyboards.py (split de bot.py)."""
from finbot.config import CATEGORIES, PAYMENT_METHODS


# ═══════════════════════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════════════════════
def category_keyboard():
    buttons = []
    row = []
    for key, label in CATEGORIES.items():
        row.append(InlineKeyboardButton(label, callback_data=f"cat_{key}"))
        if len(row) == 3:
            buttons.append(row); row = []
    if row: buttons.append(row)
    return InlineKeyboardMarkup(buttons)

def payment_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(v, callback_data=f"pay_{k}")] for k, v in PAYMENT_METHODS.items()]
    )

def yes_no_keyboard(prefix: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sim", callback_data=f"{prefix}_sim"),
         InlineKeyboardButton("❌ Não", callback_data=f"{prefix}_nao")]
    ])

def main_menu_keyboard():
    """Menu principal com 5 categorias."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💸 Lançamentos", callback_data="menu_financas")],
        [InlineKeyboardButton("📊 Relatórios", callback_data="menu_relatorios")],
        [InlineKeyboardButton("🛒 Compras", callback_data="menu_compras")],
        [InlineKeyboardButton("👤 Perfil", callback_data="menu_perfil")],
        [InlineKeyboardButton("💵 Receita", callback_data="menu_receita")],
    ])

def financas_submenu_keyboard():
    """Sub-menu de Finanças."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💸 Lançamentos", callback_data="menu_lancamentos"),
         InlineKeyboardButton("📅 Parcelas", callback_data="menu_parcelas")],
        [InlineKeyboardButton("📱 Assinaturas", callback_data="menu_assinaturas"),
         InlineKeyboardButton("🔙 Voltar", callback_data="menu_voltar")],
    ])

def relatorios_submenu_keyboard():
    """Sub-menu de Relatórios."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Resumo", callback_data="menu_resumo"),
         InlineKeyboardButton("📈 Insights", callback_data="menu_insights")],
        [InlineKeyboardButton("📄 Relatório Completo", callback_data="menu_relatorio")],
        [InlineKeyboardButton("🔙 Voltar", callback_data="menu_voltar")],
    ])

