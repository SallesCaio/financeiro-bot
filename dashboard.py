#!/usr/bin/env python3
"""
FinBot Dashboard — Servidor HTTP na porta 8888 com dashboard HTML interativo.
Lê dados da planilha Google Sheets do usuário e gera gráficos via Chart.js.

Uso:
    python dashboard.py

Variáveis de ambiente opcionais:
    DASHBOARD_PORT  — porta do servidor (padrão: 8888)
    USER_SPREADSHEET_ID — ID da planilha do usuário (padrão: planilha do Caio)
"""

import os
import json
import logging
import re
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger("FinBotDashboard")

# ════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", 8888))

# Planilha padrão (Caio)
DEFAULT_SPREADSHEET_ID = os.environ.get(
    "USER_SPREADSHEET_ID",
    "12M6Z0vc_E-jY6I_mMya7o-dn1NTppbXFcTu5cWytln4"
)

# ════════════════════════════════════════════════════════
# GOOGLE AUTH — reutiliza token.json do bot
# ════════════════════════════════════════════════════════
_sheets_service = None


def _get_credentials():
    """Carrega credenciais Google do token.json."""
    from google.oauth2.credentials import Credentials

    # Tenta múltiplos caminhos
    token_paths = [
        Path(__file__).parent / "google_token.json",
        Path.home() / "AppData" / "Local" / "hermes" / "google_token.json",
        Path.home() / ".hermes" / "financeiro-bot" / "google_token.json",
    ]

    for token_path in token_paths:
        if token_path.exists():
            with open(token_path) as f:
                d = json.load(f)
            return Credentials(
                token=d["token"],
                refresh_token=d["refresh_token"],
                token_uri=d["token_uri"],
                client_id=d["client_id"],
                client_secret=d["client_secret"],
                scopes=d["scopes"],
            )

    # Fallback: variáveis de ambiente
    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    token_uri = os.environ.get("GOOGLE_TOKEN_URI", "https://oauth2.googleapis.com/token")
    scopes = os.environ.get(
        "GOOGLE_SCOPES",
        "https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/drive.file"
    ).split()
    token = os.environ.get("GOOGLE_TOKEN", "")

    if refresh_token and client_id and client_secret:
        return Credentials(
            token=token, refresh_token=refresh_token,
            token_uri=token_uri, client_id=client_id,
            client_secret=client_secret, scopes=scopes,
        )

    raise RuntimeError("Credenciais Google não encontradas.")


def get_sheets_service():
    global _sheets_service
    if _sheets_service is None:
        from googleapiclient.discovery import build
        _sheets_service = build("sheets", "v4", credentials=_get_credentials())
    return _sheets_service


# ════════════════════════════════════════════════════════
# HELPER: parse_float (mesmo do bot.py)
# ════════════════════════════════════════════════════════
def parse_float(val) -> float:
    """Converte valor BR para float: 1.234,56 → 1234.56"""
    if val is None:
        return 0.0
    try:
        s = str(val).replace("R$", "").strip()
        if "," in s:
            s = s.replace(".", "")
            s = s.replace(",", ".")
        return float(s)
    except (ValueError, TypeError):
        return 0.0


# ════════════════════════════════════════════════════════
# GOOGLE SHEETS — Leitura de dados
# ════════════════════════════════════════════════════════
def read_range(spreadsheet_id: str, range_str: str):
    svc = get_sheets_service()
    r = svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=range_str
    ).execute()
    return r.get("values", [])


def get_month_sheet_data(spreadsheet_id: str, year_month: str) -> list:
    """Lê dados de um mês específico. Retorna lista de dicts."""
    try:
        data = read_range(spreadsheet_id, f"{year_month}!A1:J200")
    except Exception as e:
        logger.error(f"Erro ao ler mês {year_month}: {e}")
        return []

    if len(data) <= 1:
        return []

    rows = []
    for row in data[1:]:
        if len(row) > 5 and row[5]:
            rows.append({
                "data": row[0] if len(row) > 0 else "",
                "descricao": row[1] if len(row) > 1 else "",
                "categoria": row[2] if len(row) > 2 else "OUTROS",
                "subcategoria": row[3] if len(row) > 3 else "",
                "pagamento": row[4] if len(row) > 4 else "",
                "valor": parse_float(row[5]),
                "cartao": row[6] if len(row) > 6 else "",
                "necessario": row[7] if len(row) > 7 else "",
                "tipo": row[8] if len(row) > 8 else "",
                "obs": row[9] if len(row) > 9 else "",
            })
    return rows


def get_available_months(spreadsheet_id: str) -> list:
    """Retorna lista de abas que parecem ser meses (YYYY-MM)."""
    svc = get_sheets_service()
    try:
        meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = [s["properties"]["title"] for s in meta.get("sheets", [])]
        months = [s for s in sheets if re.match(r"^\d{4}-\d{2}$", s)]
        months.sort(reverse=True)
        return months
    except Exception as e:
        logger.error(f"Erro ao listar abas: {e}")
        return [datetime.now().strftime("%Y-%m")]


def get_fixos(spreadsheet_id: str) -> list:
    """Lê gastos fixos da aba FIXOS."""
    try:
        data = read_range(spreadsheet_id, "FIXOS!A1:F100")
    except Exception:
        return []
    if len(data) <= 1:
        return []
    items = []
    for row in data[1:]:
        if len(row) >= 2 and row[0]:
            items.append({
                "nome": row[0],
                "valor": parse_float(row[1]) if row[1] else 0,
                "dia": row[2] if len(row) > 2 else "",
                "categoria": row[3] if len(row) > 3 else "outros",
                "ativo": row[4].upper() == "SIM" if len(row) > 4 else True,
            })
    return items


# ════════════════════════════════════════════════════════
# AGREGAÇÃO DE DADOS
# ════════════════════════════════════════════════════════
def aggregate_by_category(rows: list) -> dict:
    """Agrupa gastos por categoria."""
    cats = {}
    for r in rows:
        cat = r["categoria"].strip() or "OUTROS"
        cats[cat] = cats.get(cat, 0) + r["valor"]
    return dict(sorted(cats.items(), key=lambda x: -x[1]))


def aggregate_by_day(rows: list) -> dict:
    """Agrupa gastos por dia do mês."""
    days = {}
    for r in rows:
        dia = "0"
        if r["data"]:
            # Tenta extrair o dia de formatos como DD/MM/YYYY
            m = re.match(r"(\d{1,2})[/\-]", r["data"])
            if m:
                dia = m.group(1).zfill(2)
        days[dia] = days.get(dia, 0) + r["valor"]
    return dict(sorted(days.items()))


def aggregate_by_payment(rows: list) -> dict:
    """Agrupa gastos por forma de pagamento."""
    pays = {}
    for r in rows:
        p = r["pagamento"].strip() or "OUTROS"
        pays[p] = pays.get(p, 0) + r["valor"]
    return dict(sorted(pays.items(), key=lambda x: -x[1]))


def compute_metrics(rows: list, fixos: list, income: float = 0) -> dict:
    """Calcula métricas principais."""
    total_gasto = sum(r["valor"] for r in rows)
    count = len(rows)
    maior_gasto = max((r["valor"] for r in rows), default=0)
    media_diaria = total_gasto / max(len(set(r["data"] for r in rows if r["data"])), 1)
    total_fixos = sum(f["valor"] for f in fixos if f.get("ativo", True))
    saldo = income - total_gasto

    # Necessário vs desnecessário
    necessario = sum(r["valor"] for r in rows if r.get("necessario", "").upper() == "SIM")
    desnecessario = total_gasto - necessario

    return {
        "total_gasto": round(total_gasto, 2),
        "total_fixos": round(total_fixos, 2),
        "saldo": round(saldo, 2),
        "maior_gasto": round(maior_gasto, 2),
        "media_diaria": round(media_diaria, 2),
        "num_gastos": count,
        "necessario": round(necessario, 2),
        "desnecessario": round(desnecessario, 2),
        "income": income,
    }


# ════════════════════════════════════════════════════════
# CORES PARA GRÁFICOS
# ════════════════════════════════════════════════════════
CHART_COLORS = [
    "#6366f1", "#8b5cf6", "#a78bfa", "#c084fc", "#e879f9",
    "#f472b6", "#fb7185", "#f87171", "#fb923c", "#fbbf24",
    "#a3e635", "#4ade80", "#2dd4bf", "#22d3ee", "#38bdf8",
    "#60a5fa", "#818cf8", "#a78bfa", "#c084fc", "#e879f9",
]

CHART_COLORS_ALPHA = [c + "33" for c in CHART_COLORS]


# ════════════════════════════════════════════════════════
# TEMPLATE HTML DO DASHBOARD
# ════════════════════════════════════════════════════════
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FinBot Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0f1117;
    --card: #1a1d2e;
    --card-hover: #222640;
    --border: #2a2d3e;
    --text: #e2e8f0;
    --text-dim: #94a3b8;
    --accent: #6366f1;
    --accent-light: #818cf8;
    --green: #4ade80;
    --red: #f87171;
    --yellow: #fbbf24;
    --orange: #fb923c;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
  }
  .header {
    background: linear-gradient(135deg, #1a1d2e 0%, #1e1b4b 100%);
    border-bottom: 1px solid var(--border);
    padding: 1.2rem 2rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 1rem;
  }
  .header h1 {
    font-size: 1.5rem;
    font-weight: 700;
    background: linear-gradient(135deg, #818cf8, #c084fc);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }
  .header .subtitle {
    color: var(--text-dim);
    font-size: 0.85rem;
  }
  .month-selector {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  .month-selector select {
    background: var(--card);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 0.5rem 1rem;
    font-size: 0.9rem;
    cursor: pointer;
    outline: none;
  }
  .month-selector select:focus { border-color: var(--accent); }
  .container {
    max-width: 1400px;
    margin: 0 auto;
    padding: 1.5rem;
  }
  /* Cards de métricas */
  .metrics-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1rem;
    margin-bottom: 1.5rem;
  }
  .metric-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.2rem;
    transition: transform 0.2s, box-shadow 0.2s;
  }
  .metric-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 25px rgba(99, 102, 241, 0.15);
  }
  .metric-card .label {
    font-size: 0.78rem;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 0.4rem;
  }
  .metric-card .value {
    font-size: 1.6rem;
    font-weight: 700;
  }
  .metric-card .sub {
    font-size: 0.75rem;
    color: var(--text-dim);
    margin-top: 0.3rem;
  }
  .metric-card.green .value { color: var(--green); }
  .metric-card.red .value { color: var(--red); }
  .metric-card.yellow .value { color: var(--yellow); }
  .metric-card.accent .value { color: var(--accent-light); }
  /* Grid de gráficos */
  .charts-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
    gap: 1.5rem;
    margin-bottom: 1.5rem;
  }
  .chart-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.5rem;
  }
  .chart-card h3 {
    font-size: 1rem;
    font-weight: 600;
    margin-bottom: 1rem;
    color: var(--text);
  }
  .chart-container {
    position: relative;
    width: 100%;
    min-height: 300px;
  }
  /* Tabela de gastos recentes */
  .table-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.5rem;
    overflow-x: auto;
  }
  .table-card h3 {
    font-size: 1rem;
    font-weight: 600;
    margin-bottom: 1rem;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
  }
  th {
    text-align: left;
    padding: 0.6rem 0.8rem;
    color: var(--text-dim);
    border-bottom: 1px solid var(--border);
    font-weight: 600;
    text-transform: uppercase;
    font-size: 0.72rem;
    letter-spacing: 0.05em;
  }
  td {
    padding: 0.6rem 0.8rem;
    border-bottom: 1px solid rgba(42, 45, 62, 0.5);
  }
  tr:hover td { background: rgba(99, 102, 241, 0.05); }
  .valor-cell { text-align: right; font-weight: 600; }
  .cat-badge {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 6px;
    font-size: 0.72rem;
    font-weight: 500;
    background: rgba(99, 102, 241, 0.15);
    color: var(--accent-light);
  }
  .nec-sim { color: var(--green); }
  .nec-nao { color: var(--red); }
  .loading {
    display: flex;
    justify-content: center;
    align-items: center;
    height: 200px;
    color: var(--text-dim);
  }
  .spinner {
    width: 30px; height: 30px;
    border: 3px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin-right: 0.8rem;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .error-msg {
    background: rgba(248, 113, 113, 0.1);
    border: 1px solid rgba(248, 113, 113, 0.3);
    border-radius: 8px;
    padding: 1rem;
    color: var(--red);
    text-align: center;
  }
  .footer {
    text-align: center;
    padding: 1.5rem;
    color: var(--text-dim);
    font-size: 0.78rem;
  }
  @media (max-width: 768px) {
    .header { padding: 1rem; }
    .header h1 { font-size: 1.2rem; }
    .container { padding: 1rem; }
    .charts-grid { grid-template-columns: 1fr; }
    .metrics-grid { grid-template-columns: repeat(2, 1fr); }
    .metric-card .value { font-size: 1.3rem; }
  }
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>💰 FinBot Dashboard</h1>
    <div class="subtitle">Gestão Financeira Pessoal — <span id="current-date"></span></div>
  </div>
  <div class="month-selector">
    <label for="month-select" style="color:var(--text-dim);font-size:0.85rem;">Mês:</label>
    <select id="month-select" onchange="loadDashboard()">
      <!-- preenchido via JS -->
    </select>
  </div>
</div>

<div class="container">
  <div id="loading-state" class="loading">
    <div class="spinner"></div> Carregando dados...
  </div>
  <div id="error-state" class="error-msg" style="display:none;"></div>

  <div id="dashboard-content" style="display:none;">
    <!-- Cards de métricas -->
    <div class="metrics-grid" id="metrics-grid"></div>

    <!-- Gráficos -->
    <div class="charts-grid">
      <div class="chart-card">
        <h3>📊 Gastos por Categoria</h3>
        <div class="chart-container">
          <canvas id="chart-pizza"></canvas>
        </div>
      </div>
      <div class="chart-card">
        <h3>📈 Gastos por Dia</h3>
        <div class="chart-container">
          <canvas id="chart-barras"></canvas>
        </div>
      </div>
      <div class="chart-card">
        <h3>💳 Forma de Pagamento</h3>
        <div class="chart-container">
          <canvas id="chart-pagamento"></canvas>
        </div>
      </div>
      <div class="chart-card">
        <h3>⭐ Necessário vs Supérfluo</h3>
        <div class="chart-container">
          <canvas id="chart-necessario"></canvas>
        </div>
      </div>
    </div>

    <!-- Tabela de gastos recentes -->
    <div class="table-card">
      <h3>📋 Últimos Gastos</h3>
      <table>
        <thead>
          <tr>
            <th>Data</th>
            <th>Descrição</th>
            <th>Categoria</th>
            <th>Pagamento</th>
            <th>Nec.?</th>
            <th style="text-align:right">Valor</th>
          </tr>
        </thead>
        <tbody id="gastos-tbody"></tbody>
      </table>
    </div>
  </div>
</div>

<div class="footer">
  FinBot Dashboard • Dados atualizados em tempo real via Google Sheets API
</div>

<script>
const COLORS = [
  '#6366f1','#8b5cf6','#a78bfa','#c084fc','#e879f9',
  '#f472b6','#fb7185','#f87171','#fb923c','#fbbf24',
  '#a3e635','#4ade80','#2dd4bf','#22d3ee','#38bdf8',
  '#60a5fa','#818cf8','#a78bfa','#c084fc','#e879f9'
];
const COLORS_ALPHA = COLORS.map(c => c + '33');

let charts = {};

document.getElementById('current-date').textContent = new Date().toLocaleDateString('pt-BR', {
  weekday:'long', year:'numeric', month:'long', day:'numeric'
});

async function loadDashboard() {
  const month = document.getElementById('month-select').value;
  document.getElementById('loading-state').style.display = 'flex';
  document.getElementById('dashboard-content').style.display = 'none';
  document.getElementById('error-state').style.display = 'none';

  try {
    const resp = await fetch(`/api/data?month=${month}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();

    if (data.error) throw new Error(data.error);

    renderMetrics(data.metrics);
    renderCharts(data);
    renderTable(data.rows);

    document.getElementById('loading-state').style.display = 'none';
    document.getElementById('dashboard-content').style.display = 'block';
  } catch (err) {
    document.getElementById('loading-state').style.display = 'none';
    document.getElementById('error-state').style.display = 'block';
    document.getElementById('error-state').textContent = '❌ Erro ao carregar dados: ' + err.message;
  }
}

function renderMetrics(m) {
  const fmt = v => 'R$ ' + v.toLocaleString('pt-BR', {minimumFractionDigits:2, maximumFractionDigits:2});
  const grid = document.getElementById('metrics-grid');
  grid.innerHTML = `
    <div class="metric-card red">
      <div class="label">Total Gasto</div>
      <div class="value">${fmt(m.total_gasto)}</div>
      <div class="sub">${m.num_gastos} transações</div>
    </div>
    <div class="metric-card accent">
      <div class="label">Saldo</div>
      <div class="value">${fmt(m.saldo)}</div>
      <div class="sub">Renda: ${fmt(m.income)}</div>
    </div>
    <div class="metric-card yellow">
      <div class="label">Maior Gasto</div>
      <div class="value">${fmt(m.maior_gasto)}</div>
      <div class="sub">transação única</div>
    </div>
    <div class="metric-card green">
      <div class="label">Média Diária</div>
      <div class="value">${fmt(m.media_diaria)}</div>
      <div class="sub">por dia com gasto</div>
    </div>
    <div class="metric-card accent">
      <div class="label">Gastos Fixos</div>
      <div class="value">${fmt(m.total_fixos)}</div>
      <div class="sub">recorrentes/mês</div>
    </div>
    <div class="metric-card green">
      <div class="label">Necessário</div>
      <div class="value">${fmt(m.necessario)}</div>
      <div class="sub">vs ${fmt(m.desnecessario)} supérfluo</div>
    </div>
  `;
}

function renderCharts(data) {
  // Destruir gráficos anteriores
  Object.values(charts).forEach(c => c.destroy());
  charts = {};

  // Pizza — Categorias
  const catData = data.by_category;
  const catLabels = Object.keys(catData);
  const catValues = Object.values(catData);
  charts.pizza = new Chart(document.getElementById('chart-pizza'), {
    type: 'doughnut',
    data: {
      labels: catLabels,
      datasets: [{
        data: catValues,
        backgroundColor: COLORS.slice(0, catLabels.length),
        borderColor: '#1a1d2e',
        borderWidth: 2,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'right',
          labels: { color: '#94a3b8', padding: 12, font: { size: 11 } }
        },
        tooltip: {
          callbacks: {
            label: ctx => ` R$ ${ctx.parsed.toLocaleString('pt-BR', {minimumFractionDigits:2})}`
          }
        }
      }
    }
  });

  // Barras — Por dia
  const dayData = data.by_day;
  const dayLabels = Object.keys(dayData).map(d => `Dia ${d}`);
  const dayValues = Object.values(dayData);
  charts.barras = new Chart(document.getElementById('chart-barras'), {
    type: 'bar',
    data: {
      labels: dayLabels,
      datasets: [{
        label: 'Gasto (R$)',
        data: dayValues,
        backgroundColor: 'rgba(99, 102, 241, 0.6)',
        borderColor: '#6366f1',
        borderWidth: 1,
        borderRadius: 4,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => ` R$ ${ctx.parsed.y.toLocaleString('pt-BR', {minimumFractionDigits:2})}`
          }
        }
      },
      scales: {
        x: {
          ticks: { color: '#94a3b8', font: { size: 10 } },
          grid: { color: 'rgba(42,45,62,0.5)' }
        },
        y: {
          ticks: {
            color: '#94a3b8',
            callback: v => 'R$ ' + v.toLocaleString('pt-BR')
          },
          grid: { color: 'rgba(42,45,62,0.5)' }
        }
      }
    }
  });

  // Pizza — Pagamento
  const payData = data.by_payment;
  const payLabels = Object.keys(payData);
  const payValues = Object.values(payData);
  charts.pagamento = new Chart(document.getElementById('chart-pagamento'), {
    type: 'pie',
    data: {
      labels: payLabels,
      datasets: [{
        data: payValues,
        backgroundColor: COLORS.slice(0, payLabels.length),
        borderColor: '#1a1d2e',
        borderWidth: 2,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'right',
          labels: { color: '#94a3b8', padding: 12, font: { size: 11 } }
        },
        tooltip: {
          callbacks: {
            label: ctx => ` R$ ${ctx.parsed.toLocaleString('pt-BR', {minimumFractionDigits:2})}`
          }
        }
      }
    }
  });

  // Barra horizontal — Necessário vs Supérfluo
  charts.necessario = new Chart(document.getElementById('chart-necessario'), {
    type: 'bar',
    data: {
      labels: ['Necessário', 'Supérfluo'],
      datasets: [{
        data: [data.metrics.necessario, data.metrics.desnecessario],
        backgroundColor: ['rgba(74, 222, 128, 0.6)', 'rgba(248, 113, 113, 0.6)'],
        borderColor: ['#4ade80', '#f87171'],
        borderWidth: 1,
        borderRadius: 6,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => ` R$ ${ctx.parsed.x.toLocaleString('pt-BR', {minimumFractionDigits:2})}`
          }
        }
      },
      scales: {
        x: {
          ticks: {
            color: '#94a3b8',
            callback: v => 'R$ ' + v.toLocaleString('pt-BR')
          },
          grid: { color: 'rgba(42,45,62,0.5)' }
        },
        y: {
          ticks: { color: '#94a3b8' },
          grid: { display: false }
        }
      }
    }
  });
}

function renderTable(rows) {
  const fmt = v => 'R$ ' + v.toLocaleString('pt-BR', {minimumFractionDigits:2, maximumFractionDigits:2});
  const tbody = document.getElementById('gastos-tbody');
  const recent = rows.slice(-30).reverse();
  tbody.innerHTML = recent.map(r => `
    <tr>
      <td>${r.data || '-'}</td>
      <td>${r.descricao || '-'}</td>
      <td><span class="cat-badge">${r.categoria || '-'}</span></td>
      <td>${r.pagamento || '-'}</td>
      <td class="${r.necessario === 'SIM' ? 'nec-sim' : 'nec-nao'}">${r.necessario || '-'}</td>
      <td class="valor-cell">${fmt(r.valor)}</td>
    </tr>
  `).join('');
}

// Carregar meses disponíveis e inicializar
async function init() {
  try {
    const resp = await fetch('/api/months');
    const months = await resp.json();
    const sel = document.getElementById('month-select');
    sel.innerHTML = months.map(m => {
      const [y, mo] = m.split('-');
      const nome = new Date(y, mo-1).toLocaleDateString('pt-BR', {month:'long', year:'numeric'});
      return `<option value="${m}">${nome.charAt(0).toUpperCase() + nome.slice(1)}</option>`;
    }).join('');
    if (months.length > 0) sel.value = months[0];
    await loadDashboard();
  } catch (e) {
    document.getElementById('loading-state').style.display = 'none';
    document.getElementById('error-state').style.display = 'block';
    document.getElementById('error-state').textContent = '❌ Erro ao inicializar: ' + e.message;
  }
}

init();
</script>
</body>
</html>
"""


# ════════════════════════════════════════════════════════
# HTTP HANDLER
# ════════════════════════════════════════════════════════
class DashboardHandler(BaseHTTPRequestHandler):
    """Handler HTTP que serve o dashboard e API de dados."""

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)

        if path == "/" or path == "/dashboard":
            self._serve_html(DASHBOARD_HTML)

        elif path == "/api/data":
            self._serve_data(params)

        elif path == "/api/months":
            self._serve_months()

        elif path == "/health":
            self._serve_health()

        else:
            self.send_response(404)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "Not found"}')

    def _serve_html(self, html_content: str):
        data = html_content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _serve_data(self, params: dict):
        month = params.get("month", [datetime.now().strftime("%Y-%m")])[0]
        spreadsheet_id = DEFAULT_SPREADSHEET_ID

        try:
            rows = get_month_sheet_data(spreadsheet_id, month)
            fixos = get_fixos(spreadsheet_id)
            by_category = aggregate_by_category(rows)
            by_day = aggregate_by_day(rows)
            by_payment = aggregate_by_payment(rows)
            metrics = compute_metrics(rows, fixos)

            result = {
                "month": month,
                "rows": rows,
                "by_category": by_category,
                "by_day": by_day,
                "by_payment": by_payment,
                "metrics": metrics,
            }
            self._json_response(result)
        except Exception as e:
            logger.error(f"Erro API data: {e}", exc_info=True)
            self._json_response({"error": str(e)}, status=500)

    def _serve_months(self):
        try:
            months = get_available_months(DEFAULT_SPREADSHEET_ID)
            self._json_response(months)
        except Exception as e:
            logger.error(f"Erro API months: {e}")
            self._json_response([datetime.now().strftime("%Y-%m")])

    def _serve_health(self):
        self._json_response({
            "status": "ok",
            "service": "FinBot Dashboard",
            "timestamp": datetime.now().isoformat(),
        })

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """Silencia logs HTTP para não poluir o console."""
        pass


# ════════════════════════════════════════════════════════
# SERVIDOR
# ════════════════════════════════════════════════════════
def start_dashboard(port: int = None, blocking: bool = True):
    """Inicia o servidor do dashboard.

    Args:
        port: Porta do servidor (padrão: DASHBOARD_PORT ou 8888)
        blocking: Se True, bloqueia a thread atual. Se False, roda em thread daemon.
    """
    if port is None:
        port = DASHBOARD_PORT

    server = HTTPServer(("0.0.0.0", port), DashboardHandler)

    if blocking:
        logger.info(f"🚀 FinBot Dashboard rodando em http://0.0.0.0:{port}/dashboard")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logger.info("Dashboard encerrado.")
            server.shutdown()
    else:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info(f"🚀 FinBot Dashboard iniciado em http://0.0.0.0:{port}/dashboard")
        return server


# ════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    start_dashboard()
