"""FinBot - conta.py (split de bot.py)."""
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from finbot.auth import get_sheets_service
from finbot.db import get_achievements, get_user, upsert_user
from finbot.sheets import append_gasto, get_or_create_month_sheet, save_user_to_master
from finbot.keyboards import main_menu_keyboard
from finbot.handlers.common import ensure_user


# ═══════════════════════════════════════════════════════
# /conquistas — Gamificação
# ═══════════════════════════════════════════════════════
async def cmd_conquistas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro."); return
    user = get_user(update.effective_user.id)
    achievements = get_achievements(update.effective_user.id)
    ACHIEVEMENT_NAMES = {
        "gastos_10": "📝 Primeiros Passos — 10 gastos registrados",
        "gastos_100": "🏆 Mestre dos Gastos — 100 gastos registrados",
    }

    lines = [
        f"🏆 *Suas Conquistas*\n",
        f"📝 Total de gastos: {user.get('gastos_count',0)}\n",
        "🔓 *Conquistas desbloqueadas:*"
    ]

    unlocked_keys = {a["key"] for a in achievements}
    found = False
    for key, name in ACHIEVEMENT_NAMES.items():
        if key in unlocked_keys:
            lines.append(f"  ✅ {name}")
            found = True
    if not found:
        lines.append("  (nenhuma ainda — continue usando o bot!)")

    # Mostrar próximas conquistas
    lines.append("\n🎯 *Próximas conquistas:*")
    if "gastos_10" not in unlocked_keys:
        lines.append(f"  🔒 {ACHIEVEMENT_NAMES['gastos_10']}")
    if "gastos_100" not in unlocked_keys and "gastos_10" in unlocked_keys:
        lines.append(f"  🔒 {ACHIEVEMENT_NAMES['gastos_100']}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# ═══════════════════════════════════════════════════════
# /perfil — Configurar Perfil
# ═══════════════════════════════════════════════════════
async def cmd_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra perfil e permite editar renda."""
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro.")
        return
    user = get_user(update.effective_user.id)
    args = context.args
    
    if not args:
        await update.message.reply_text(
            f"👤 *Seu Perfil*\n\n"
            f"📝 Nome: {user['name']}\n"
            f"💰 Renda: R$ {user['income']:,.2f}\n"
            f"💳 Cartões: {user.get('cards', 'nenhum')}\n"
            f"🎯 Objetivo: {user.get('goal', '')}\n\n"
            f"Para alterar sua renda: */perfil renda 3500*\n"
            f"Para alterar nome: */perfil nome Caio Salles*\n"
            f"Para alterar cartões: */perfil cards Nubank, Itau*",
            parse_mode="Markdown", reply_markup=main_menu_keyboard()
        )
        return
    
    sub = args[0].lower()
    if sub == "renda" and len(args) >= 2:
        try:
            nova_renda = float(args[1].replace(",", "."))
        except ValueError:
            await update.message.reply_text("❌ Valor inválido. Use: /perfil renda 3500")
            return
        if nova_renda <= 0:
            await update.message.reply_text("❌ Renda deve ser maior que zero.")
            return
        upsert_user(update.effective_user.id, income=nova_renda)
        save_user_to_master(update.effective_user.id, user.get("username",""), user.get("first_name",""),
                           user["name"], nova_renda, user.get("cards",""), user.get("goal",""), user["spreadsheet_id"])
        await update.message.reply_text(f"✅ Renda atualizada para R$ {nova_renda:,.2f}!", parse_mode="Markdown", reply_markup=main_menu_keyboard())
    elif sub == "nome" and len(args) >= 2:
        novo_nome = " ".join(args[1:])
        upsert_user(update.effective_user.id, name=novo_nome)
        await update.message.reply_text(f"✅ Nome atualizado para *{novo_nome}*!", parse_mode="Markdown", reply_markup=main_menu_keyboard())
    elif sub == "cards" and len(args) >= 2:
        novos_cards = " ".join(args[1:])
        upsert_user(update.effective_user.id, cards=novos_cards)
        await update.message.reply_text(f"✅ Cartões atualizados: *{novos_cards}*", parse_mode="Markdown", reply_markup=main_menu_keyboard())
    else:
        await update.message.reply_text(
            "Use: */perfil renda 3500*\n*/perfil nome Caio*\n*/perfil cards Nubank, Itau*",
            parse_mode="Markdown"
        )

# ═══════════════════════════════════════════════════════
# /receita — Registrar Renda Extra
# ═══════════════════════════════════════════════════════
async def cmd_receita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registra uma receita extra na planilha."""
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "💵 *Registrar Receita Extra*\n\n"
            "Uso: */receita <valor> <descrição>*\n"
            "Ex: */receita 500 freela*\n*/receita 1500 bonus*\n*/receita 200 ifood*",
            parse_mode="Markdown"
        )
        return
    
    try:
        valor = float(args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ Valor inválido. Ex: /receita 500 freela")
        return
    
    desc = " ".join(args[1:])
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("❌ User não encontrado. Use /start."); return
    sid = user.get("spreadsheet_id", "")
    if not sid:
        await update.message.reply_text("❌ Planilha não configurada. Use /start."); return
    ym = datetime.now().strftime("%Y-%m")
    get_or_create_month_sheet(sid, ym)
    
    # Add a row with type "RECEITA" instead of "CONSUMO"
    row = [
        datetime.now().strftime("%d/%m/%Y"),
        desc, "RECEITA", "", "PIX",
        valor, "", "SIM", "RECEITA", ""
    ]
    append_gasto(sid, ym, row)
    
    # Also ensure INCOME tab exists
    svc = get_sheets_service()
    meta = svc.spreadsheets().get(spreadsheetId=sid).execute()
    sheets_list = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if "RECEITAS" not in sheets_list:
        svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={
            "requests": [{"addSheet": {"properties": {"title": "RECEITAS"}}}]
        }).execute()
        svc.spreadsheets().values().update(
            spreadsheetId=sid, range="RECEITAS!A1:E1",
            valueInputOption="USER_ENTERED",
            body={"values": [["DATA","DESCRIÇÃO","VALOR","CATEGORIA","OBS"]]}
        ).execute()
    
    svc.spreadsheets().values().append(
        spreadsheetId=sid, range="RECEITAS!A:E",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": [[datetime.now().strftime("%d/%m/%Y"), desc, valor, "EXTRA", ""]]}
    ).execute()
    
    await update.message.reply_text(
        f"💵 *Receita de R$ {valor:,.2f}* registrada!\n📝 {desc}",
        parse_mode="Markdown", reply_markup=main_menu_keyboard()
    )

