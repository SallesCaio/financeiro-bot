# 📊 Guia do Dashboard FinBot

## O que é?
Um dashboard HTML interativo que mostra gráficos dos seus gastos.

## Como acessar

### Opção 1: Local (desenvolvimento)
```bash
cd ~/.hermes/financeiro-bot
python dashboard.py
```
Acesse: http://localhost:8888/dashboard

### Opção 2: Você pode hospedar em qualquer servidor
Basta rodar `python dashboard.py` em qualquer máquina com Python.

## Não está no Render?
Correto! O dashboard roda apenas localmente porque:
1. O Render usa a porta 8080 para o health check do bot
2. O dashboard usa a porta 8888
3. Só uma porta pode ser exposta por serviço no Render Free

## Funcionalidades do Dashboard
- Gráfico de pizza (gastos por categoria)
- Gráfico de barras (gastos por dia)
- Gráfico de pagamento (forma de pagamento)
- Cards de métricas (total, saldo, maior gasto, etc.)
- Tabela de gastos recentes
