#!/usr/bin/env python3
"""
FinBot — Módulo de Insights Financeiros Automáticos
Gera alertas inteligentes baseados nos dados da planilha Google Sheets.
"""

import logging
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger("FinBot.Insights")

# Reutiliza funções do bot.py
from bot import read_range, parse_float, get_sheets_service


def _get_prev_month(year_month: str) -> str:
    """Retorna o mês anterior no formato YYYY-MM."""
    y, m = map(int, year_month.split("-"))
    if m == 1:
        return f"{y - 1}-12"
    return f"{y}-{m - 1:02d}"


def _parse_date(date_str: str) -> datetime | None:
    """Tenta parsear data nos formatos comuns: DD/MM/YYYY, YYYY-MM-DD, DD-MM-YYYY."""
    if not date_str or not date_str.strip():
        return None
    s = date_str.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _weekday_name(dt: datetime) -> str:
    """Retorna nome do dia da semana em PT-BR."""
    names = {
        0: "Segunda",
        1: "Terça",
        2: "Quarta",
        3: "Quinta",
        4: "Sexta",
        5: "Sábado",
        6: "Domingo",
    }
    return names.get(dt.weekday(), "Desconhecido")


def _fmt(valor: float) -> str:
    """Formata valor como moeda BR."""
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct_change(current: float, previous: float) -> float | None:
    """Retorna variação percentual. Se previous == 0, retorna None."""
    if previous == 0:
        return None
    return ((current - previous) / previous) * 100


def _load_month_data(spreadsheet_id: str, year_month: str) -> list[dict]:
    """
    Lê os dados de uma aba de mês e retorna lista de dicts com:
    data (datetime|None), descricao, categoria, subcategoria, pagamento, valor (float)
    """
    range_str = f"{year_month}!A:F"
    try:
        rows = read_range(spreadsheet_id, range_str)
    except Exception as e:
        logger.warning(f"Nao foi possivel ler aba {year_month}: {e}")
        return []
    if not rows or len(rows) <= 1:
        return []

    records = []
    for row in rows[1:]:
        if not row or not row[0]:
            continue
        data = _parse_date(row[0]) if len(row) > 0 else None
        descricao = row[1] if len(row) > 1 else ""
        categoria = (row[2] if len(row) > 2 else "outros").strip().lower()
        subcategoria = row[3] if len(row) > 3 else ""
        pagamento = row[4] if len(row) > 4 else ""
        valor = parse_float(row[5]) if len(row) > 5 else 0.0

        records.append(
            {
                "data": data,
                "descricao": descricao,
                "categoria": categoria,
                "subcategoria": subcategoria,
                "pagamento": pagamento,
                "valor": valor,
            }
        )
    return records


def _group_by_week(records: list[dict]) -> dict[int, list[dict]]:
    """Agrupa registros por número da semana do ano (ISO)."""
    weeks = defaultdict(list)
    for r in records:
        if r["data"]:
            week_num = r["data"].isocalendar()[1]
            weeks[week_num].append(r)
    return dict(weeks)


def _detect_weekly_spending_increase(records: list[dict]) -> list[str]:
    """
    Detecta aumento de gastos semanais.
    Compara semana atual com anterior e gera alerta se aumento > 20%.
    """
    insights = []
    if not records:
        return insights

    weeks = _group_by_week(records)
    if len(weeks) < 2:
        return insights

    sorted_weeks = sorted(weeks.keys())
    for i in range(1, len(sorted_weeks)):
        prev_w = sorted_weeks[i - 1]
        curr_w = sorted_weeks[i]
        prev_total = sum(r["valor"] for r in weeks[prev_w])
        curr_total = sum(r["valor"] for r in weeks[curr_w])

        pct = _pct_change(curr_total, prev_total)
        if pct is not None and pct > 20:
            insights.append(
                f"⚠️ Seus gastos na semana {curr_w} foram {pct:.0f}% maiores que na semana {prev_w} "
                f"({_fmt(prev_total)} → {_fmt(curr_total)})"
            )
    return insights


def _detect_top_categories(records: list[dict], top_n: int = 5) -> list[str]:
    """
    Identifica as categorias que mais gastaram no mês.
    """
    insights = []
    if not records:
        return insights

    cat_totals = defaultdict(float)
    for r in records:
        cat_totals[r["categoria"]] += r["valor"]

    if not cat_totals:
        return insights

    sorted_cats = sorted(cat_totals.items(), key=lambda x: x[1], reverse=True)
    total_geral = sum(v for _, v in sorted_cats)

    lines = ["📊 **Top categorias do mês:**"]
    for cat, val in sorted_cats[:top_n]:
        pct = (val / total_geral * 100) if total_geral > 0 else 0
        emoji = {
            "alimentacao": "🍽️",
            "mercado": "🛒",
            "moto": "🏍️",
            "transporte": "🚌",
            "pessoal": "👤",
            "saude": "🏥",
            "assinaturas": "📱",
            "dividas": "💰",
            "delivery": "🛵",
            "educacao": "📚",
            "moradia": "🏠",
            "lazer": "🎮",
            "outros": "📦",
        }.get(cat, "📌")
        lines.append(f"  {emoji} {cat.capitalize()}: {_fmt(val)} ({pct:.1f}%)")

    insights.append("\n".join(lines))
    return insights


def _detect_weekday_spending(records: list[dict]) -> list[str]:
    """
    Identifica os dias da semana com mais gastos.
    """
    insights = []
    dated_records = [r for r in records if r["data"]]
    if not dated_records:
        return insights

    day_totals = defaultdict(float)
    day_counts = defaultdict(int)
    for r in dated_records:
        wd = _weekday_name(r["data"])
        day_totals[wd] += r["valor"]
        day_counts[wd] += 1

    if not day_totals:
        return insights

    sorted_days = sorted(day_totals.items(), key=lambda x: x[1], reverse=True)
    top_day, top_val = sorted_days[0]

    lines = ["📅 **Dias da semana com mais gastos:**"]
    day_order = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
    for day_name in day_order:
        if day_name in day_totals:
            count = day_counts[day_name]
            val = day_totals[day_name]
            marker = " 🔴" if day_name == top_day else ""
            lines.append(f"  {day_name}: {_fmt(val)} ({count} transações){marker}")

    insights.append("\n".join(lines))
    return insights


def _detect_category_weekly_change(records: list[dict]) -> list[str]:
    """
    Detecta categorias com aumento significativo de gastos semana a semana.
    Ex: 'Você gastou 40% mais em delivery essa semana'
    """
    insights = []
    if not records:
        return insights

    weeks = _group_by_week(records)
    if len(weeks) < 2:
        return insights

    sorted_weeks = sorted(weeks.keys())
    prev_w = sorted_weeks[-2]
    curr_w = sorted_weeks[-1]

    prev_cats = defaultdict(float)
    curr_cats = defaultdict(float)

    for r in weeks[prev_w]:
        prev_cats[r["categoria"]] += r["valor"]
    for r in weeks[curr_w]:
        curr_cats[r["categoria"]] += r["valor"]

    all_cats = set(list(prev_cats.keys()) + list(curr_cats.keys()))

    for cat in all_cats:
        prev_v = prev_cats.get(cat, 0)
        curr_v = curr_cats.get(cat, 0)

        if prev_v == 0 and curr_v > 0:
            insights.append(
                f"🆕 Nova despesa na semana {curr_w}: {cat.capitalize()} ({_fmt(curr_v)})"
            )
        elif prev_v > 0:
            pct = _pct_change(curr_v, prev_v)
            if pct is not None and pct > 25:
                emoji = "🛵" if cat == "delivery" else "📈"
                insights.append(
                    f"{emoji} Você gastou {pct:.0f}% mais em {cat} essa semana "
                    f"({_fmt(prev_v)} → {_fmt(curr_v)})"
                )
            elif pct is not None and pct < -25:
                insights.append(
                    f"✅ Você economizou {abs(pct):.0f}% em {cat} essa semana "
                    f"({_fmt(prev_v)} → {_fmt(curr_v)})"
                )

    return insights


def _compare_with_previous_month(
    spreadsheet_id: str, year_month: str, current_records: list[dict]
) -> list[str]:
    """
    Compara gastos do mês atual com o mês anterior.
    """
    insights = []
    prev_month = _get_prev_month(year_month)
    prev_records = _load_month_data(spreadsheet_id, prev_month)

    current_total = sum(r["valor"] for r in current_records)
    prev_total = sum(r["valor"] for r in prev_records)

    if prev_total > 0:
        pct = _pct_change(current_total, prev_total)
        if pct is not None:
            if pct > 0:
                insights.append(
                    f"📈 Seus gastos totais aumentaram {pct:.0f}% comparado a {prev_month} "
                    f"({_fmt(prev_total)} → {_fmt(current_total)})"
                )
            elif pct < 0:
                economia = abs(current_total - prev_total)
                insights.append(
                    f"📉 Seus gastos totais diminuíram {abs(pct):.0f}% comparado a {prev_month} "
                    f"({_fmt(prev_total)} → {_fmt(current_total)}). Economia: {_fmt(economia)}"
                )
            else:
                insights.append(
                    f"➡️ Seus gastos totais se mantiveram estáveis comparado a {prev_month} "
                    f"({_fmt(current_total)})"
                )

    # Comparação por categoria entre meses
    current_cats = defaultdict(float)
    prev_cats = defaultdict(float)
    for r in current_records:
        current_cats[r["categoria"]] += r["valor"]
    for r in prev_records:
        prev_cats[r["categoria"]] += r["valor"]

    significant_changes = []
    for cat in set(list(current_cats.keys()) + list(prev_cats.keys())):
        c = current_cats.get(cat, 0)
        p = prev_cats.get(cat, 0)
        if p > 0 and c > 0:
            pct = _pct_change(c, p)
            if pct is not None and abs(pct) > 25:
                direction = "aumentou" if pct > 0 else "caiu"
                significant_changes.append(
                    f"  • {cat.capitalize()}: {direction} {abs(pct):.0f}% ({_fmt(p)} → {_fmt(c)})"
                )

    if significant_changes:
        insights.append(
            f"🔄 **Mudanças significativas vs {prev_month}:**\n"
            + "\n".join(significant_changes)
        )

    return insights


def _detect_monthly_economy(
    spreadsheet_id: str, year_month: str, current_records: list[dict]
) -> list[str]:
    """
    Calcula economia do mês: renda - gastos totais.
    Tenta ler a renda da aba RESUMO ou do perfil do usuário.
    """
    insights = []
    total_gastos = sum(r["valor"] for r in current_records)

    # Tenta ler renda da aba RESUMO ou dos registros do mês
    renda = 0.0
    try:
        for r in current_records:
            if r.get("descricao", "").lower() in ["renda", "salario", "salário"] and r.get("valor", 0) > 0:
                renda = r.get("valor", 0)
                break
    except Exception:
        pass

    # Se não encontrou na aba, tenta ler da aba RESUMO geral
    if renda == 0:
        try:
            resumo_rows = read_range(spreadsheet_id, "RESUMO!A:B")
            for row in resumo_rows:
                if row and len(row) >= 2:
                    label = str(row[0]).strip().lower() if row[0] else ""
                    if "renda" in label or "salario" in label or "salário" in label:
                        renda = parse_float(row[1])
                        break
        except Exception:
            pass

    if renda > 0:
        economia = renda - total_gastos
        pct_economia = (economia / renda * 100) if renda > 0 else 0
        if economia >= 0:
            insights.append(
                f"💰 **Economia do mês:** {_fmt(economia)} ({pct_economia:.1f}% da renda de {_fmt(renda)})"
            )
        else:
            insights.append(
                f"🚨 **Déficit do mês:** {_fmt(abs(economia))} (gastou {_fmt(total_gastos)} "
                f"com renda de {_fmt(renda)})"
            )
    else:
        insights.append(
            f"💡 Total gasto no mês: {_fmt(total_gastos)} "
            f"({len(current_records)} transações)"
        )

    return insights


def _detect_subcategory_alerts(records: list[dict]) -> list[str]:
    """
    Detecta alertas por subcategoria (ex: moto aumentou 25%).
    """
    insights = []
    if not records:
        return insights

    weeks = _group_by_week(records)
    if len(weeks) < 2:
        return insights

    sorted_weeks = sorted(weeks.keys())
    prev_w = sorted_weeks[-2]
    curr_w = sorted_weeks[-1]

    prev_subs = defaultdict(float)
    curr_subs = defaultdict(float)

    for r in weeks[prev_w]:
        sub = r["subcategoria"].strip().lower() if r["subcategoria"] else r["categoria"]
        prev_subs[sub] += r["valor"]
    for r in weeks[curr_w]:
        sub = r["subcategoria"].strip().lower() if r["subcategoria"] else r["categoria"]
        curr_subs[sub] += r["valor"]

    for sub in curr_subs:
        if sub in prev_subs and prev_subs[sub] > 0:
            pct = _pct_change(curr_subs[sub], prev_subs[sub])
            if pct is not None and pct > 20:
                insights.append(
                    f"🔔 Seus gastos com {sub} aumentaram {pct:.0f}% "
                    f"({_fmt(prev_subs[sub])} → {_fmt(curr_subs[sub])})"
                )

    return insights


def _detect_spending_velocity(records: list[dict]) -> list[str]:
    """
    Detecta se o ritmo de gastos está acelerando.
    Compara média diária da primeira metade vs segunda metade do mês.
    """
    insights = []
    dated = [r for r in records if r["data"]]
    if not dated or len(dated) < 4:
        return insights

    dated.sort(key=lambda r: r["data"])
    mid = len(dated) // 2

    first_half = dated[:mid]
    second_half = dated[mid:]

    first_total = sum(r["valor"] for r in first_half)
    second_total = sum(r["valor"] for r in second_half)

    first_days = (first_half[-1]["data"] - first_half[0]["data"]).days + 1 if len(first_half) > 1 else 1
    second_days = (second_half[-1]["data"] - second_half[0]["data"]).days + 1 if len(second_half) > 1 else 1

    first_daily = first_total / max(first_days, 1)
    second_daily = second_total / max(second_days, 1)

    if first_daily > 0:
        pct = _pct_change(second_daily, first_daily)
        if pct is not None and pct > 15:
            insights.append(
                f"⚡ Seu ritmo de gastos acelerou {pct:.0f}% na segunda metade do mês "
                f"(média diária: {_fmt(first_daily)} → {_fmt(second_daily)})"
            )
        elif pct is not None and pct < -15:
            insights.append(
                f"🐢 Seu ritmo de gastos desacelerou {abs(pct):.0f}% na segunda metade do mês "
                f"(média diária: {_fmt(first_daily)} → {_fmt(second_daily)})"
            )

    return insights


def _detect_large_transactions(records: list[dict]) -> list[str]:
    """
    Detecta transações significativamente acima da média.
    """
    insights = []
    if len(records) < 3:
        return insights

    valores = [r["valor"] for r in records if r["valor"] > 0]
    if not valores:
        return insights

    media = sum(valores) / len(valores)
    desvio = (sum((v - media) ** 2 for v in valores) / len(valores)) ** 0.5
    threshold = media + 2 * desvio

    outliers = [
        r for r in records
        if r["valor"] > threshold and r["valor"] > media * 2
    ]

    if outliers:
        lines = ["🚨 **Transações acima do normal:**"]
        for r in sorted(outliers, key=lambda x: x["valor"], reverse=True)[:5]:
            data_str = r["data"].strftime("%d/%m") if r["data"] else "??"
            lines.append(
                f"  • {data_str} - {r['descricao']}: {_fmt(r['valor'])} ({r['categoria']})"
            )
        insights.append("\n".join(lines))

    return insights


def _detect_payment_method_change(records: list[dict]) -> list[str]:
    """
    Detecta mudanças nos métodos de pagamento (ex: mais gastos no crédito).
    """
    insights = []
    if not records:
        return insights

    payment_totals = defaultdict(float)
    for r in records:
        if r["pagamento"]:
            payment_totals[r["pagamento"].strip().lower()] += r["valor"]

    if not payment_totals:
        return insights

    total = sum(payment_totals.values())
    credito = payment_totals.get("credito", 0) + payment_totals.get("crédito", 0)

    if total > 0 and credito / total > 0.5:
        pct = credito / total * 100
        insights.append(
            f"💳 {pct:.0f}% dos seus gastos foram no crédito ({_fmt(credito)} de {_fmt(total)}). "
            f"Fique de olho na fatura!"
        )

    return insights


def gerar_insights(spreadsheet_id: str, year_month: str) -> list[str]:
    """
    Função principal: gera todos os insights financeiros para um mês.

    Args:
        spreadsheet_id: ID da planilha Google Sheets do usuário.
        year_month: Mês de referência no formato "YYYY-MM".

    Returns:
        Lista de strings formatadas para exibição no Telegram.
    """
    all_insights = []

    # Carregar dados do mês atual
    current_records = _load_month_data(spreadsheet_id, year_month)

    if not current_records:
        return [f"ℹ️ Nenhum dado encontrado para {year_month}. Registre gastos para ver insights!"]

    # Header
    total_gastos = sum(r["valor"] for r in current_records)
    all_insights.append(
        f"🔍 **Insights Financeiros — {year_month}**\n"
        f"📋 {len(current_records)} transações | Total: {_fmt(total_gastos)}\n"
        f"{'─' * 30}"
    )

    # 1. Economia do mês
    all_insights.extend(_detect_monthly_economy(spreadsheet_id, year_month, current_records))

    # 2. Comparação com mês anterior
    all_insights.extend(_compare_with_previous_month(spreadsheet_id, year_month, current_records))

    # 3. Top categorias
    all_insights.extend(_detect_top_categories(current_records))

    # 4. Dias da semana com mais gastos
    all_insights.extend(_detect_weekday_spending(current_records))

    # 5. Aumento de gastos semanais
    all_insights.extend(_detect_weekly_spending_increase(current_records))

    # 6. Mudanças por categoria semana a semana
    all_insights.extend(_detect_category_weekly_change(current_records))

    # 7. Alertas por subcategoria
    all_insights.extend(_detect_subcategory_alerts(current_records))

    # 8. Velocidade de gastos
    all_insights.extend(_detect_spending_velocity(current_records))

    # 9. Transações acima do normal
    all_insights.extend(_detect_large_transactions(current_records))

    # 10. Métodos de pagamento
    all_insights.extend(_detect_payment_method_change(current_records))

    # Footer
    all_insights.append(f"{'─' * 30}\n🤖 Gerado pelo FinBot em {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    return all_insights


if __name__ == "__main__":
    # Teste rápido
    import sys

    if len(sys.argv) >= 3:
        sid = sys.argv[1]
        ym = sys.argv[2]
    else:
        sid = "12M6Z0vc_E-jY6I_mMya7o-dn1NTppbXFcTu5cWytln4"
        ym = "2026-06"

    print(f"Gerando insights para {ym}...")
    results = gerar_insights(sid, ym)
    for insight in results:
        print(insight)
        print()
