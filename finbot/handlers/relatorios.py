"""FinBot - relatorios.py (split de bot.py)."""
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from finbot.config import logger
from finbot.db import get_user
from finbot.sheets import parse_float, read_fixos, read_parcelas, read_range
from finbot.keyboards import main_menu_keyboard
from finbot.handlers.common import ensure_user


# ═══════════════════════════════════════════════════════
# /relatorio — Relatório Financeiro
# ═══════════════════════════════════════════════════════
async def cmd_relatorio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro."); return
    user = get_user(update.effective_user.id)
    sid = user["spreadsheet_id"]; ym = datetime.now().strftime("%Y-%m")
    income = user["income"]

    try:
        data = read_range(sid, f"{ym}!A1:J50")
        fixos = read_fixos(sid)
        parcelas = read_parcelas(sid)
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao ler dados: {e}"); return

    if len(data) <= 1:
        await update.message.reply_text("📭 Nenhum gasto no mês para gerar relatório."); return

    total = sum(parse_float(r[5]) for r in data[1:] if len(r) > 5 and r[5])
    cats = {}
    for r in data[1:]:
        if len(r) > 5 and r[2] and r[5]:
            cats[r[2]] = cats.get(r[2], 0) + parse_float(r[5])

    # Calcular gastos necessários vs supérfluos
    necessarios = sum(parse_float(r[5]) for r in data[1:] if len(r) > 7 and r[7] == "SIM" and r[5])
    superfluos = total - necessarios

    # Gastos fixos
    total_fixos = sum(f["valor"] for f in fixos if f.get("ativo", True))

    # Parcelas
    total_parcelas_mensal = sum(p["valor_parcela"] for p in parcelas if p.get("ativo", True))
    total_restante = sum(
        (p["n_parcelas"] - p.get("pagas", 0)) * p["valor_parcela"]
        for p in parcelas if p.get("ativo", True)
    )

    dia = datetime.now().day
    projecao = (total / dia) * 30 if dia > 0 else total
    saldo_projetado = income - projecao

    lines = [
        f"📄 *Relatório Financeiro — {ym}*\n",
        f"📥 *Receita:* R$ {income:,.2f}",
        f"📤 *Gastos:* R$ {total:,.2f} ({total/income*100:.0f}% da renda)" if income > 0 else f"📤 *Gastos:* R$ {total:,.2f}",
        f"💰 *Saldo:* R$ {income - total:,.2f}",
        f"✅ *Necessário:* R$ {necessarios:,.2f} | ❌ *Supérfluo:* R$ {superfluos:,.2f}\n",
        f"📌 *Fixos:* R$ {total_fixos:,.2f}/mês",
        f"📅 *Parcelas:* R$ {total_parcelas_mensal:,.2f}/mês",
        f"💳 *Dívidas restantes:* R$ {total_restante:,.2f}\n",
        f"🔮 *Projeção fim do mês:* R$ {projecao:,.2f}",
    ]
    if income > 0:
        if saldo_projetado < 0:
            lines.append(f"⚠️ *Alerta:* Projeção de déficit de R$ {abs(saldo_projetado):,.2f}!")
        else:
            lines.append(f"💪 *Saldo projetado:* R$ {saldo_projetado:,.2f}")

    lines.append(f"\n📂 *Gastos por categoria:*")
    for cat, val in sorted(cats.items(), key=lambda x: -x[1])[:5]:
        pct = val / total * 100 if total > 0 else 0
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        lines.append(f"{bar} {cat[:15]}: R$ {val:,.2f} ({pct:.0f}%)")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    await update.message.reply_text(f"📊 Planilha: https://docs.google.com/spreadsheets/d/{sid}", parse_mode="Markdown")
    await update.message.reply_text("👇", reply_markup=main_menu_keyboard())

# ═══════════════════════════════════════════════════════
# /insights — Análise Inteligente de Gastos
# ═══════════════════════════════════════════════════════
async def cmd_insights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gera insights financeiros automáticos."""
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro.")
        return
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("❌ User não encontrado. Use /start."); return
    sid = user.get("spreadsheet_id", "")
    if not sid:
        await update.message.reply_text("❌ Planilha não configurada. Use /start."); return
    ym = datetime.now().strftime("%Y-%m")
    
    try:
        from insights import gerar_insights
        insights_list = gerar_insights(sid, ym)
    except Exception as e:
        logger.error(f"Erro insights: {e}")
        await update.message.reply_text(f"❌ Erro ao gerar insights: {e}")
        return
    
    if not insights_list:
        await update.message.reply_text("📈 Nenhum insight disponível ainda. Registre mais gastos!", parse_mode="Markdown", reply_markup=main_menu_keyboard())
        return
    
    lines = ["📈 *Seus Insights Financeiros*\n"]
    for insight in insights_list:
        lines.append(insight)
    
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu_keyboard())

# ═══════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════
# RELATÓRIOS — Imprimem dados diretamente das abas do Sheets
# ═══════════════════════════════════════════════════════
async def cmd_relatorio_parcelamentos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Relatório de parcelamentos da aba PARCELAMENTOS."""
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro."); return
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("❌ User não encontrado. Use /start."); return
    sid = user.get("spreadsheet_id", "")
    if not sid:
        await update.message.reply_text("❌ Planilha não configurada. Use /start."); return
    try:
        parcelas = read_parcelas(sid)
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao ler parcelamentos: {e}"); return
    if not parcelas:
        await update.message.reply_text("📅 Nenhum parcelamento cadastrado.", reply_markup=main_menu_keyboard()); return
    lines = ["📅 *RELATÓRIO DE PARCELAMENTOS*\n"]
    total_pago = 0
    total_restante = 0
    for p in parcelas:
        total_pago += p["valor_pago"]
        total_restante += p["valor_restante"]
        pct = int(p["pagas"] / p["total_parcelas"] * 100) if p["total_parcelas"] > 0 else 0
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        lines.append(f"*{p['cod']}* — {p['descricao']}")
        lines.append(f"  R$ {p['valor_parcela']:,.2f}/mês | {p['pagas']}/{p['total_parcelas']} pagas")
        lines.append(f"  {bar} {pct}% | Pago: R$ {p['valor_pago']:,.2f} | Resta: R$ {p['valor_restante']:,.2f}")
        lines.append("")
    lines.append(f"💰 *Total Pago:* R$ {total_pago:,.2f}")
    lines.append(f"💳 *Total Restante:* R$ {total_restante:,.2f}")
    lines.append(f"📊 *Total Geral:* R$ {total_pago + total_restante:,.2f}")
    lines.append(f"\n📊 Planilha: https://docs.google.com/spreadsheets/d/{sid}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu_keyboard())

async def cmd_relatorio_fixos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Relatório de gastos fixos da aba FIXOS."""
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro."); return
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("❌ User não encontrado. Use /start."); return
    sid = user.get("spreadsheet_id", "")
    if not sid:
        await update.message.reply_text("❌ Planilha não configurada. Use /start."); return
    try:
        fixos = read_fixos(sid)
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao ler fixos: {e}"); return
    if not fixos:
        await update.message.reply_text("📌 Nenhum gasto fixo cadastrado.", reply_markup=main_menu_keyboard()); return
    ativos = [f for f in fixos if f.get("ativo", True)]
    total = sum(f["valor"] for f in ativos)
    lines = ["📌 *RELATÓRIO DE GASTOS FIXOS*\n"]
    for f in ativos:
        dia = f"dia {f['dia']}" if f.get("dia") else "s/dia"
        lines.append(f"• *{f['nome']}* — R$ {f['valor']:,.2f}/mês — {dia}")
        if f.get("obs"):
            lines.append(f"  _{f['obs']}_")
    lines.append(f"\n💰 *Total mensal:* R$ {total:,.2f}")
    lines.append(f"📊 *Total anual (est.):* R$ {total * 12:,.2f}")
    lines.append(f"\n📊 Planilha: https://docs.google.com/spreadsheets/d/{sid}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu_keyboard())

async def cmd_relatorio_resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Relatório resumo do mês (aba YYYY-MM)."""
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro."); return
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("❌ User não encontrado. Use /start."); return
    sid = user.get("spreadsheet_id", "")
    if not sid:
        await update.message.reply_text("❌ Planilha não configurada. Use /start."); return
    ym = datetime.now().strftime("%Y-%m")
    try:
        data = read_range(sid, f"{ym}!A1:J50")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao ler planilha: {e}"); return
    if len(data) <= 1:
        await update.message.reply_text("📭 Nenhum gasto registrado este mês.", reply_markup=main_menu_keyboard()); return
    total = sum(parse_float(r[5]) for r in data[1:] if len(r) > 5 and r[5])
    cats = {}
    for r in data[1:]:
        if len(r) > 5 and r[2] and r[5]:
            cats[r[2]] = cats.get(r[2], 0) + parse_float(r[5])
    income = user.get("income", 0)
    saldo = income - total
    lines = [f"📊 *RESUMO FINANCEIRO — {ym}*\n"]
    lines.append(f"📥 Receita: R$ {income:,.2f}")
    lines.append(f"📤 Gastos: R$ {total:,.2f} ({total/income*100:.0f}% da renda)" if income > 0 else f"📤 Gastos: R$ {total:,.2f}")
    lines.append(f"💰 Saldo: R$ {saldo:,.2f}")
    lines.append(f"📂 {len(data)-1} lançamentos\n")
    lines.append("📂 *Por categoria:*")
    for cat, val in sorted(cats.items(), key=lambda x: -x[1]):
        pct = val / total * 100 if total > 0 else 0
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        lines.append(f"{bar} {cat[:15]}: R$ {val:,.2f} ({pct:.0f}%)")
    lines.append(f"\n📊 Planilha: https://docs.google.com/spreadsheets/d/{sid}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu_keyboard())

async def cmd_relatorio_completo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Relatório completo: resumo + fixos + parcelamentos."""
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro."); return
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("❌ User não encontrado. Use /start."); return
    sid = user.get("spreadsheet_id", "")
    if not sid:
        await update.message.reply_text("❌ Planilha não configurada. Use /start."); return
    ym = datetime.now().strftime("%Y-%m")
    income = user.get("income", 0)

    # ── Resumo do mês ──
    try:
        data = read_range(sid, f"{ym}!A1:J50")
        total_gastos = sum(parse_float(r[5]) for r in data[1:] if len(r) > 5 and r[5]) if len(data) > 1 else 0
        cats = {}
        for r in data[1:]:
            if len(r) > 5 and r[2] and r[5]:
                cats[r[2]] = cats.get(r[2], 0) + parse_float(r[5])
    except:
        total_gastos = 0
        cats = {}

    # ── Fixos ──
    try:
        fixos = read_fixos(sid)
        total_fixos = sum(f["valor"] for f in fixos if f.get("ativo", True))
    except:
        total_fixos = 0

    # ── Parcelamentos ──
    try:
        parcelas = read_parcelas(sid)
        total_parcelas_pago = sum(p["valor_pago"] for p in parcelas)
        total_parcelas_restante = sum(p["valor_restante"] for p in parcelas)
    except:
        total_parcelas_pago = 0
        total_parcelas_restante = 0

    # ── Montar relatório ──
    lines = [f"📄 *RELATÓRIO COMPLETO — {ym}*\n"]
    lines.append("═" * 30)
    lines.append("📊 *RESUMO DO MÊS*")
    lines.append(f"📥 Receita: R$ {income:,.2f}")
    lines.append(f"📤 Gastos: R$ {total_gastos:,.2f}")
    lines.append(f"💰 Saldo: R$ {income - total_gastos:,.2f}\n")

    if cats:
        lines.append("📂 *Categorias:*")
        for cat, val in sorted(cats.items(), key=lambda x: -x[1])[:5]:
            pct = val / total_gastos * 100 if total_gastos > 0 else 0
            lines.append(f"  • {cat[:15]}: R$ {val:,.2f} ({pct:.0f}%)")
        lines.append("")

    lines.append("═" * 30)
    lines.append("📌 *GASTOS FIXOS*")
    lines.append(f"💰 Total mensal: R$ {total_fixos:,.2f}")
    lines.append(f"📊 Total anual (est.): R$ {total_fixos * 12:,.2f}\n")

    lines.append("═" * 30)
    lines.append("📅 *PARCELAMENTOS*")
    lines.append(f"💰 Total já pago: R$ {total_parcelas_pago:,.2f}")
    lines.append(f"💳 Total restante: R$ {total_parcelas_restante:,.2f}")
    lines.append(f"📊 Total geral: R$ {total_parcelas_pago + total_parcelas_restante:,.2f}\n")

    lines.append("═" * 30)
    total_comprometido = total_gastos + total_fixos + total_parcelas_restante
    lines.append("🔮 *PROJEÇÃO*")
    lines.append(f"💸 Total comprometido: R$ {total_comprometido:,.2f}")
    if income > 0:
        lines.append(f"📈 % da renda comprometida: {total_comprometido/income*100:.0f}%")
        lines.append(f"💰 Saldo livre: R$ {income - total_comprometido:,.2f}")
    lines.append(f"\n📊 Planilha: https://docs.google.com/spreadsheets/d/{sid}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu_keyboard())

